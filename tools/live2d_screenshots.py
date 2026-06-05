from __future__ import annotations

import argparse
import struct
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from playwright.sync_api import Page

from tools.live2d_browser import (
    DEFAULT_VIEWER_PATH,
    REPO_ROOT,
    ServerInfo,
    _close_browser,
    _launch_browser,
    _parse_viewport,
    _static_server,
    _viewer_url,
    _wait_until_loaded,
    _with_query_param,
)


CHARACTER_ROOT = REPO_ROOT / "assets/assetbundles/actor2d/character"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "assets/l2d"
DEFAULT_VIEWPORT = (4096, 4096)
DEFAULT_RENDER_RESOLUTION = "4"
DEFAULT_SCALE = 0.9
DEFAULT_FIT_MARGIN = 0.9
MIN_OUTPUT_SIZE = 2048
MAX_FIT_ATTEMPTS = 6


@dataclass(frozen=True)
class AlphaBounds:
    left: int
    top: int
    right: int
    bottom: int
    image_width: int
    image_height: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def touches_edge(self) -> bool:
        return (
            self.left == 0
            or self.top == 0
            or self.right == self.image_width
            or self.bottom == self.image_height
        )


@dataclass(frozen=True)
class TalentModel:
    skin_id: str
    model_path: Path

    @property
    def viewer_path(self) -> str:
        return "/" + self.model_path.relative_to(REPO_ROOT).as_posix()

    @property
    def output_name(self) -> str:
        return f"{self.skin_id}.png"


@dataclass(frozen=True)
class ScreenshotResult:
    skin_id: str
    model_path: Path
    output_path: Path
    skipped: bool
    image_width: int | None = None
    image_height: int | None = None


def _discover_talent_models(skin_ids: set[str] | None) -> list[TalentModel]:
    models = []
    for model_path in sorted(CHARACTER_ROOT.glob("*/live2d/talent/*.model3.json")):
        skin_id = model_path.parts[-4]
        if skin_ids is not None and skin_id not in skin_ids:
            continue
        models.append(TalentModel(skin_id=skin_id, model_path=model_path))
    return models


def discover_talent_models(skin_ids: set[str] | None = None) -> list[TalentModel]:
    return _discover_talent_models(skin_ids)


def _png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as file:
        header = file.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG file")
    return struct.unpack(">II", header[16:24])


def _read_image_and_alpha_bounds(path: Path, alpha_threshold: int) -> tuple[np.ndarray, AlphaBounds]:
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise RuntimeError(f"Could not read screenshot {path}")
    if image.ndim != 3 or image.shape[2] != 4:
        raise RuntimeError(f"Screenshot {path} does not have an alpha channel")

    alpha = image[:, :, 3]
    ys, xs = np.where(alpha > alpha_threshold)
    if not len(xs) or not len(ys):
        raise RuntimeError(f"Screenshot {path} is fully transparent")

    height, width = alpha.shape
    bounds = AlphaBounds(
        left=int(xs.min()),
        top=int(ys.min()),
        right=int(xs.max()) + 1,
        bottom=int(ys.max()) + 1,
        image_width=width,
        image_height=height,
    )
    return image, bounds


def _trim_transparent_borders(
    path: Path,
    alpha_threshold: int,
    padding: int,
) -> tuple[int, int]:
    image, bounds = _read_image_and_alpha_bounds(path, alpha_threshold)
    if bounds.touches_edge:
        raise RuntimeError(
            f"Live2D pixels touch screenshot edge; raw bounds are "
            f"{bounds.left},{bounds.top}-{bounds.right},{bounds.bottom} "
            f"inside {bounds.image_width}x{bounds.image_height}",
        )

    crop_left = max(0, bounds.left - padding)
    crop_top = max(0, bounds.top - padding)
    crop_right = min(bounds.image_width, bounds.right + padding)
    crop_bottom = min(bounds.image_height, bounds.bottom + padding)
    cropped = image[crop_top:crop_bottom, crop_left:crop_right]
    if not cv2.imwrite(str(path), cropped):
        raise RuntimeError(f"Could not write cropped screenshot {path}")
    return _png_size(path)


def _select_last_talent_phase(page: Page, timeout_ms: int) -> str:
    page.wait_for_selector("#phaseSelect option", state="attached", timeout=timeout_ms)
    options = page.locator("#phaseSelect option").evaluate_all(
        """(nodes) => nodes.map((node) => ({
            value: node.value,
            text: node.textContent || "",
            disabled: node.disabled
        }))"""
    )
    selectable = [option for option in options if not option["disabled"] and option["value"] != ""]
    if not selectable:
        raise RuntimeError("No talent phase options are available")

    selected = next((option for option in selectable if option["text"].startswith("3+")), selectable[-1])
    page.select_option("#phaseSelect", value=selected["value"])
    return str(selected["text"])


def _fit_rendered_bounds(page: Page, margin: float) -> None:
    page.evaluate(
        """(margin) => {
            if (typeof currentModel === "undefined" || typeof app === "undefined" || !currentModel || !app) {
              throw new Error("Viewer model globals are not available");
            }

            const fitOnce = () => {
              const bounds = currentModel.getBounds();
              if (!bounds.width || !bounds.height) {
                throw new Error("Rendered Live2D bounds are empty");
              }

              const scaleFactor = Math.min(
                (window.innerWidth * margin) / bounds.width,
                (window.innerHeight * margin) / bounds.height
              );
              currentModel.scale.set(
                currentModel.scale.x * scaleFactor,
                currentModel.scale.y * scaleFactor
              );

              const fitted = currentModel.getBounds();
              currentModel.position.set(
                currentModel.position.x + window.innerWidth / 2 - (fitted.x + fitted.width / 2),
                currentModel.position.y + window.innerHeight / 2 - (fitted.y + fitted.height / 2)
              );
            };

            fitOnce();
            fitOnce();
            app.renderer.render(app.stage);
        }""",
        margin,
    )


def _adjust_to_alpha_bounds(page: Page, bounds: AlphaBounds, fit_margin: float, min_size: int) -> None:
    scale_factor = 1.0
    max_side = max(bounds.width, bounds.height)
    if bounds.touches_edge:
        scale_factor = min(
            0.82,
            (bounds.image_width * fit_margin) / max(bounds.width, 1),
            (bounds.image_height * fit_margin) / max(bounds.height, 1),
        )
    elif max_side < min_size:
        scale_factor = min(
            1.5,
            (min_size * 1.05) / max(max_side, 1),
            (bounds.image_width * fit_margin) / max(bounds.width, 1),
            (bounds.image_height * fit_margin) / max(bounds.height, 1),
        )
    elif bounds.width > bounds.image_width * fit_margin or bounds.height > bounds.image_height * fit_margin:
        scale_factor = min(
            (bounds.image_width * fit_margin) / max(bounds.width, 1),
            (bounds.image_height * fit_margin) / max(bounds.height, 1),
        )

    center_x = bounds.left + bounds.width / 2
    center_y = bounds.top + bounds.height / 2
    page.evaluate(
        """({ dx, dy, scaleFactor }) => {
            if (typeof currentModel === "undefined" || !currentModel) {
              throw new Error("Viewer model globals are not available");
            }

            currentModel.scale.set(
              currentModel.scale.x * scaleFactor,
              currentModel.scale.y * scaleFactor
            );
            currentModel.position.set(
              currentModel.position.x + dx,
              currentModel.position.y + dy
            );
        }""",
        {
            "dx": bounds.image_width / 2 - center_x,
            "dy": bounds.image_height / 2 - center_y,
            "scaleFactor": scale_factor,
        },
    )


def _load_model_url(server: ServerInfo, viewer_path: str, model: TalentModel, scale: float) -> str:
    url = _viewer_url(server.url, viewer_path)
    for name, value in (
        ("model", model.viewer_path),
        ("scale", str(scale)),
        ("renderResolution", DEFAULT_RENDER_RESOLUTION),
    ):
        url = _with_query_param(url, name, value)
    return url


def _capture_model(
    page: Page,
    server: ServerInfo,
    viewer_path: str,
    model: TalentModel,
    output: Path,
    scale: float,
    timeout_ms: int,
    settle_ms: int,
    alpha_threshold: int,
    crop_padding: int,
    fit_margin: float,
    min_size: int,
    max_fit_attempts: int,
) -> tuple[int, int]:
    page.goto(_load_model_url(server, viewer_path, model, scale), wait_until="domcontentloaded", timeout=timeout_ms)
    _wait_until_loaded(page, timeout_ms)
    selected_phase = _select_last_talent_phase(page, timeout_ms)
    if not selected_phase.startswith("3+"):
        raise RuntimeError(f"Expected phase 3+, got {selected_phase!r}")

    page.add_style_tag(
        content="""
            html,
            body {
              background: transparent !important;
            }

            #controls,
            #status {
              display: none !important;
            }
        """,
    )
    page.wait_for_timeout(settle_ms)
    _fit_rendered_bounds(page, fit_margin)
    output.parent.mkdir(parents=True, exist_ok=True)

    for attempt in range(max_fit_attempts + 1):
        page.screenshot(path=str(output), full_page=False, omit_background=True)
        _, bounds = _read_image_and_alpha_bounds(output, alpha_threshold)
        if not bounds.touches_edge and max(bounds.width, bounds.height) >= min_size:
            break
        if attempt == max_fit_attempts:
            break

        _adjust_to_alpha_bounds(
            page=page,
            bounds=bounds,
            fit_margin=fit_margin,
            min_size=min_size,
        )
        page.wait_for_timeout(100)

    return _trim_transparent_borders(
        path=output,
        alpha_threshold=alpha_threshold,
        padding=crop_padding,
    )


def capture_talent_screenshots(
    *,
    root: Path = REPO_ROOT,
    host: str = "127.0.0.1",
    port: int = 0,
    viewer_path: str = DEFAULT_VIEWER_PATH,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    skin_ids: list[str] | set[str] | None = None,
    limit: int | None = None,
    scale: float = DEFAULT_SCALE,
    viewport: tuple[int, int] = DEFAULT_VIEWPORT,
    fit_margin: float = DEFAULT_FIT_MARGIN,
    min_size: int = MIN_OUTPUT_SIZE,
    alpha_threshold: int = 0,
    crop_padding: int = 16,
    max_fit_attempts: int = MAX_FIT_ATTEMPTS,
    device_scale_factor: float = 1,
    timeout: int = 60000,
    settle: int = 1500,
    headed: bool = False,
) -> list[ScreenshotResult]:
    if min_size < MIN_OUTPUT_SIZE:
        raise ValueError(f"--min-size must be at least {MIN_OUTPUT_SIZE}")
    if not 0 < fit_margin <= 1:
        raise ValueError("--fit-margin must be greater than 0 and no more than 1")
    if not 0 <= alpha_threshold <= 255:
        raise ValueError("--alpha-threshold must be between 0 and 255")
    if crop_padding < 0:
        raise ValueError("--crop-padding must be non-negative")
    if max_fit_attempts < 0:
        raise ValueError("--max-fit-attempts must be non-negative")

    models = _discover_talent_models(set(skin_ids) if skin_ids else None)
    if limit is not None:
        models = models[:limit]
    if not models:
        raise RuntimeError("No talent Live2D models were found")

    output_root = output_root.resolve()
    width, height = viewport
    if width < min_size or height < min_size:
        raise ValueError(f"Viewport must be at least {min_size}x{min_size}")

    print(f"Found {len(models)} talent Live2D models")
    pending: list[tuple[int, TalentModel, Path]] = []
    failures: list[tuple[TalentModel, str]] = []
    results: list[ScreenshotResult] = []

    for index, model in enumerate(models, start=1):
        output = output_root / model.output_name
        if output.exists():
            print(f"[{index}/{len(models)}] Skipping {model.skin_id}: {output}")
            results.append(ScreenshotResult(
                skin_id=model.skin_id,
                model_path=model.model_path,
                output_path=output,
                skipped=True,
            ))
            continue
        pending.append((index, model, output))

    if not pending:
        print(f"Wrote screenshots to {output_root}")
        return results

    with _static_server(root, host, port) as server:
        browser = _launch_browser(headed)
        try:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=device_scale_factor,
            )
            page = context.new_page()

            for index, model, output in pending:
                print(f"[{index}/{len(models)}] Capturing {model.skin_id}: {output}")
                try:
                    image_width, image_height = _capture_model(
                        page=page,
                        server=server,
                        viewer_path=viewer_path,
                        model=model,
                        output=output,
                        scale=scale,
                        timeout_ms=timeout,
                        settle_ms=settle,
                        alpha_threshold=alpha_threshold,
                        crop_padding=crop_padding,
                        fit_margin=fit_margin,
                        min_size=min_size,
                        max_fit_attempts=max_fit_attempts,
                    )
                    if max(image_width, image_height) < min_size:
                        raise RuntimeError(
                            f"Trimmed screenshot is {image_width}x{image_height}, below {min_size}px minimum",
                        )
                    print(f"  wrote {image_width}x{image_height}")
                    results.append(ScreenshotResult(
                        skin_id=model.skin_id,
                        model_path=model.model_path,
                        output_path=output,
                        skipped=False,
                        image_width=image_width,
                        image_height=image_height,
                    ))
                except Exception as error:
                    failures.append((model, str(error)))
                    print(f"  ERROR: {error}")
        finally:
            _close_browser(browser)

    if failures:
        print("\nLive2D screenshots with errors:")
        for model, error in failures:
            print(f"- {model.skin_id}: {model.viewer_path}: {error}")
        raise RuntimeError(f"Live2D screenshot capture failed for {len(failures)} model(s)")

    print(f"Wrote screenshots to {output_root}")
    return results


def _run(args: argparse.Namespace) -> None:
    try:
        capture_talent_screenshots(
            root=args.root,
            host=args.host,
            port=args.port,
            viewer_path=args.viewer_path,
            output_root=args.output_root,
            skin_ids=args.skin_id,
            limit=args.limit,
            scale=args.scale,
            viewport=args.viewport,
            fit_margin=args.fit_margin,
            min_size=args.min_size,
            alpha_threshold=args.alpha_threshold,
            crop_padding=args.crop_padding,
            max_fit_attempts=args.max_fit_attempts,
            device_scale_factor=args.device_scale_factor,
            timeout=args.timeout,
            settle=args.settle,
            headed=args.headed,
        )
    except RuntimeError as error:
        raise SystemExit(str(error)) from None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture high-resolution phase 3+ talent Live2D screenshots into assets/l2d.",
    )
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="Static server root")
    parser.add_argument("--host", default="127.0.0.1", help="Static server host")
    parser.add_argument("--port", type=int, default=0, help="Static server port, or 0 for any free port")
    parser.add_argument("--viewer-path", default=DEFAULT_VIEWER_PATH, help="Viewer HTML path under the static root")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT, help="Screenshot output directory")
    parser.add_argument("--skin-id", action="append", help="Only capture this character/skin ID; may be repeated")
    parser.add_argument("--limit", type=int, help="Capture only the first N matching models")
    parser.add_argument("--scale", type=float, default=DEFAULT_SCALE, help="Viewer scale slider value")
    parser.add_argument("--viewport", type=_parse_viewport, default=DEFAULT_VIEWPORT, help="Viewport size, e.g. 2048x2048")
    parser.add_argument("--fit-margin", type=float, default=DEFAULT_FIT_MARGIN, help="Fraction of the raw viewport occupied by rendered Live2D bounds")
    parser.add_argument("--min-size", type=int, default=MIN_OUTPUT_SIZE, help="Minimum output longest side after trimming")
    parser.add_argument("--alpha-threshold", type=int, default=0, help="Alpha threshold used for transparent-border cropping")
    parser.add_argument("--crop-padding", type=int, default=16, help="Transparent pixels to preserve around the cropped bounds")
    parser.add_argument("--max-fit-attempts", type=int, default=MAX_FIT_ATTEMPTS, help="Maximum alpha-feedback fit attempts before cropping")
    parser.add_argument("--device-scale-factor", type=float, default=1, help="Browser device scale factor")
    parser.add_argument("--timeout", type=int, default=60000, help="Navigation and selector timeout in milliseconds")
    parser.add_argument("--settle", type=int, default=1500, help="Milliseconds to wait before screenshot")
    parser.add_argument("--headed", action="store_true", help="Show the browser window")
    args = parser.parse_args()

    _run(args)


if __name__ == "__main__":
    main()
