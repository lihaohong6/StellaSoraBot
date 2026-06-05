from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from character_info.characters import Character, get_id_to_char
from tools.live2d_browser import DEFAULT_VIEWER_PATH, REPO_ROOT
from tools.live2d_screenshots import (
    DEFAULT_FIT_MARGIN,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_SCALE,
    DEFAULT_VIEWPORT,
    MAX_FIT_ATTEMPTS,
    MIN_OUTPUT_SIZE,
    capture_talent_screenshots,
    discover_talent_models,
)
from utils.upload_utils import UploadRequest, process_uploads


FILE_TEXT = "[[Category:Talent images]]"
UPLOAD_SUMMARY = "batch upload talent l2d images"


@dataclass(frozen=True)
class Live2DTalentImage:
    skin_id: str
    character: Character
    source: Path
    target: str


def _skin_id_to_character(skin_id: str) -> Character:
    char_id = int(skin_id[:-2])
    character = get_id_to_char().get(char_id)
    if character is None:
        raise RuntimeError(f"No character data found for Live2D skin ID {skin_id}")
    return character


def _target_filename(character: Character) -> str:
    return f"{character.name}_Talent.png"


def get_live2d_talent_images(
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    skin_ids: list[str] | set[str] | None = None,
    limit: int | None = None,
    require_files: bool = True,
) -> list[Live2DTalentImage]:
    models = discover_talent_models(set(skin_ids) if skin_ids else None)
    if limit is not None:
        models = models[:limit]
    if not models:
        raise RuntimeError("No talent Live2D models were found")

    images = []
    seen_targets: dict[str, str] = {}
    output_root = output_root.resolve()
    for model in models:
        character = _skin_id_to_character(model.skin_id)
        source = output_root / model.output_name
        if require_files and not source.exists():
            raise FileNotFoundError(f"Live2D talent screenshot does not exist: {source}")

        target = _target_filename(character)
        if target in seen_targets:
            raise RuntimeError(
                f"Live2D talent upload filename collision: {target} "
                f"for skin IDs {seen_targets[target]} and {model.skin_id}",
            )
        seen_targets[target] = model.skin_id
        images.append(Live2DTalentImage(
            skin_id=model.skin_id,
            character=character,
            source=source,
            target=target,
        ))
    return images


def generate_live2d_talent_images(
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
) -> None:
    capture_talent_screenshots(
        root=root,
        host=host,
        port=port,
        viewer_path=viewer_path,
        output_root=output_root,
        skin_ids=skin_ids,
        limit=limit,
        scale=scale,
        viewport=viewport,
        fit_margin=fit_margin,
        min_size=min_size,
        alpha_threshold=alpha_threshold,
        crop_padding=crop_padding,
        max_fit_attempts=max_fit_attempts,
        device_scale_factor=device_scale_factor,
        timeout=timeout,
        settle=settle,
        headed=headed,
    )


def upload_live2d_talent_images(
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    skin_ids: list[str] | set[str] | None = None,
    limit: int | None = None,
    overwrite: bool = False,
    force: bool = False,
) -> None:
    images = get_live2d_talent_images(
        output_root=output_root,
        skin_ids=skin_ids,
        limit=limit,
    )
    upload_requests = [
        UploadRequest(image.source, image.target, FILE_TEXT, UPLOAD_SUMMARY)
        for image in images
    ]
    process_uploads(upload_requests, overwrite=overwrite, force=force)


def live2d_talent_images_main(
    overwrite: bool = False,
    force: bool = False,
    **generate_kwargs,
) -> None:
    generate_live2d_talent_images(
        **generate_kwargs,
    )
    upload_live2d_talent_images(
        overwrite=overwrite,
        force=force,
    )


def main() -> None:
    live2d_talent_images_main()


if __name__ == "__main__":
    main()
