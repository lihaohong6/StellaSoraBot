import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import UnityPy
from PIL import Image
from UnityPy.enums import ClassIDType

from unpack.unpack_paths import data_dir
from unpack.unpack_utils import get_unity3d_files
from utils.data_utils import assets_root

ROOT_SIZE = (2400.0, 1700.0)
MIN_SPRITE_AREA = 500_000
MIN_OUTPUT_AREA = 800_000


@dataclass
class RectNode:
    path_id: int
    game_object_id: int
    name: str
    rect: dict[str, Any]
    parent_id: int | None
    child_ids: list[int] = field(default_factory=list)


@dataclass
class SpriteInfo:
    name: str
    image: Image.Image


@dataclass
class ImageNode:
    game_object_id: int
    sprite_id: int
    color: tuple[float, float, float, float]


@dataclass
class Layout:
    left: float
    top: float
    width: float
    height: float
    pivot_x: float
    pivot_y: float


def _ptr_id(value: dict[str, Any] | None) -> int | None:
    if not value:
        return None
    path_id = value.get("m_PathID")
    return path_id if path_id else None


def _vec2(value: dict[str, Any], default_x: float = 0.0, default_y: float = 0.0) -> tuple[float, float]:
    return float(value.get("x", default_x)), float(value.get("y", default_y))


def _color(value: dict[str, Any] | None) -> tuple[float, float, float, float]:
    if not value:
        return 1.0, 1.0, 1.0, 1.0
    return (
        float(value.get("r", 1.0)),
        float(value.get("g", 1.0)),
        float(value.get("b", 1.0)),
        float(value.get("a", 1.0)),
    )


def _safe_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip("/"))
    return value.strip("_") or "background"


def _read_bundle(bundle: Path) -> tuple[dict[int, RectNode], dict[int, int], dict[int, ImageNode], dict[int, SpriteInfo]]:
    env = UnityPy.load(str(bundle))
    game_object_names: dict[int, str] = {}
    rects: dict[int, RectNode] = {}
    rect_by_game_object: dict[int, int] = {}
    images: dict[int, ImageNode] = {}
    sprites: dict[int, SpriteInfo] = {}

    for obj in env.objects:
        if obj.type == ClassIDType.GameObject:
            data = obj.read_typetree()
            game_object_names[obj.path_id] = data.get("m_Name", "")

    for obj in env.objects:
        if obj.type == ClassIDType.RectTransform:
            data = obj.read_typetree()
            game_object_id = _ptr_id(data.get("m_GameObject"))
            if game_object_id is None:
                continue
            parent_id = _ptr_id(data.get("m_Father"))
            child_ids = [_ptr_id(child) for child in data.get("m_Children", [])]
            child_ids = [child_id for child_id in child_ids if child_id is not None]
            rects[obj.path_id] = RectNode(
                path_id=obj.path_id,
                game_object_id=game_object_id,
                name=game_object_names.get(game_object_id, ""),
                rect=data,
                parent_id=parent_id,
                child_ids=child_ids,
            )
            rect_by_game_object[game_object_id] = obj.path_id

    for obj in env.objects:
        if obj.type != ClassIDType.MonoBehaviour:
            continue
        try:
            data = obj.read_typetree()
        except Exception:
            continue
        sprite_id = _ptr_id(data.get("m_Sprite"))
        game_object_id = _ptr_id(data.get("m_GameObject"))
        if sprite_id is None or game_object_id is None:
            continue
        images[game_object_id] = ImageNode(
            game_object_id=game_object_id,
            sprite_id=sprite_id,
            color=_color(data.get("m_Color")),
        )

    wanted_sprite_ids = {image.sprite_id for image in images.values()}
    load_all_sprites = not wanted_sprite_ids
    for obj in env.objects:
        if obj.type != ClassIDType.Sprite:
            continue
        if not load_all_sprites and obj.path_id not in wanted_sprite_ids:
            continue
        try:
            data = obj.read()
            image = data.image.convert("RGBA")
        except Exception as e:
            print(f"WARNING: Could not read sprite {obj.path_id} from {bundle.name}: {e}")
            continue
        sprites[obj.path_id] = SpriteInfo(name=data.m_Name, image=image)

    return rects, rect_by_game_object, images, sprites


def _node_path(node_id: int, rects: dict[int, RectNode]) -> str:
    parts: list[str] = []
    current_id: int | None = node_id
    while current_id in rects:
        node = rects[current_id]
        if node.name:
            parts.append(node.name)
        current_id = node.parent_id
    return "/".join(reversed(parts))


def _subtree_ids(root_id: int, rects: dict[int, RectNode]) -> list[int]:
    result: list[int] = []

    def visit(node_id: int) -> None:
        if node_id not in rects:
            return
        result.append(node_id)
        for child_id in rects[node_id].child_ids:
            visit(child_id)

    visit(root_id)
    return result


def _has_large_background(
    root_id: int,
    rects: dict[int, RectNode],
    images: dict[int, ImageNode],
    sprites: dict[int, SpriteInfo],
) -> bool:
    for node_id in _subtree_ids(root_id, rects):
        image = images.get(rects[node_id].game_object_id)
        if not image:
            continue
        sprite = sprites.get(image.sprite_id)
        if not sprite:
            continue
        width, height = sprite.image.size
        if sprite.name.startswith("bg_") and width * height >= MIN_SPRITE_AREA:
            return True
    return False


def _is_background_root(node_id: int, rects: dict[int, RectNode]) -> bool:
    name = rects[node_id].name.lower()
    path = _node_path(node_id, rects).lower()
    if name in {"bg", "imgbg", "bgroot"}:
        return True
    if "----bg----" in name or "---bg---" in name:
        return True
    return "/bg" in path or "bgroot" in path


def _find_roots(
    rects: dict[int, RectNode],
    images: dict[int, ImageNode],
    sprites: dict[int, SpriteInfo],
) -> list[int]:
    candidates = [
        node_id
        for node_id in rects
        if _is_background_root(node_id, rects) and _has_large_background(node_id, rects, images, sprites)
    ]
    candidate_set = set(candidates)
    roots: list[int] = []
    for node_id in candidates:
        parent_id = rects[node_id].parent_id
        has_candidate_parent = False
        while parent_id in rects:
            if parent_id in candidate_set:
                has_candidate_parent = True
                break
            parent_id = rects[parent_id].parent_id
        if not has_candidate_parent:
            roots.append(node_id)
    return sorted(roots, key=lambda root_id: _node_path(root_id, rects))


def _root_size(root: RectNode) -> tuple[float, float]:
    width, height = _vec2(root.rect.get("m_SizeDelta", {}), *ROOT_SIZE)
    if width < 1000 or height < 700:
        return ROOT_SIZE
    return width, height


def _child_layout(parent_layout: Layout, child: RectNode) -> Layout:
    anchor_min_x, anchor_min_y = _vec2(child.rect.get("m_AnchorMin", {}), 0.5, 0.5)
    anchor_max_x, anchor_max_y = _vec2(child.rect.get("m_AnchorMax", {}), 0.5, 0.5)
    anchored_x, anchored_y = _vec2(child.rect.get("m_AnchoredPosition", {}))
    size_delta_x, size_delta_y = _vec2(child.rect.get("m_SizeDelta", {}))
    pivot_x, pivot_y = _vec2(child.rect.get("m_Pivot", {}), 0.5, 0.5)
    scale_x, scale_y = _vec2(child.rect.get("m_LocalScale", {}), 1.0, 1.0)

    width = parent_layout.width * (anchor_max_x - anchor_min_x) + size_delta_x
    height = parent_layout.height * (anchor_max_y - anchor_min_y) + size_delta_y
    width = abs(width * scale_x)
    height = abs(height * scale_y)

    parent_pivot_x = parent_layout.left + parent_layout.pivot_x * parent_layout.width
    parent_pivot_y = parent_layout.top + (1.0 - parent_layout.pivot_y) * parent_layout.height
    anchor_ref_x = ((anchor_min_x + anchor_max_x) / 2.0 - parent_layout.pivot_x) * parent_layout.width
    anchor_ref_y = ((anchor_min_y + anchor_max_y) / 2.0 - parent_layout.pivot_y) * parent_layout.height
    child_pivot_x = parent_pivot_x + anchor_ref_x + anchored_x
    child_pivot_y = parent_pivot_y - anchor_ref_y - anchored_y

    return Layout(
        left=child_pivot_x - pivot_x * width,
        top=child_pivot_y - (1.0 - pivot_y) * height,
        width=width,
        height=height,
        pivot_x=pivot_x,
        pivot_y=pivot_y,
    )


def _tint(image: Image.Image, color: tuple[float, float, float, float]) -> Image.Image:
    r, g, b, a = color
    if (r, g, b, a) == (1.0, 1.0, 1.0, 1.0):
        return image
    tinted = image.copy()
    red, green, blue, alpha = tinted.split()
    red = red.point(lambda value: round(value * r))
    green = green.point(lambda value: round(value * g))
    blue = blue.point(lambda value: round(value * b))
    alpha = alpha.point(lambda value: round(value * a))
    return Image.merge("RGBA", (red, green, blue, alpha))


def _draw_node(
    canvas: Image.Image,
    node_id: int,
    layout: Layout,
    rects: dict[int, RectNode],
    images: dict[int, ImageNode],
    sprites: dict[int, SpriteInfo],
) -> None:
    node = rects[node_id]
    image_node = images.get(node.game_object_id)
    if image_node:
        sprite = sprites.get(image_node.sprite_id)
        if sprite and layout.width > 1 and layout.height > 1:
            width = max(1, round(layout.width))
            height = max(1, round(layout.height))
            image = sprite.image.resize((width, height), Image.Resampling.LANCZOS)
            image = _tint(image, image_node.color)
            _, max_alpha = image.split()[3].getextrema()
            if max_alpha >= 200:
                canvas.alpha_composite(image, (round(layout.left), round(layout.top)))
    for child_id in node.child_ids:
        if child_id not in rects:
            continue
        _draw_node(canvas, child_id, _child_layout(layout, rects[child_id]), rects, images, sprites)


def _export_root(
    bundle: Path,
    root_id: int,
    rects: dict[int, RectNode],
    images: dict[int, ImageNode],
    sprites: dict[int, SpriteInfo],
    output_dir: Path,
) -> Path | None:
    path_name = _safe_name(_node_path(root_id, rects))
    output_path = output_dir / bundle.stem / f"{path_name}.png"
    if output_path.exists():
        return output_path

    root = rects[root_id]
    width, height = _root_size(root)
    if width * height < MIN_OUTPUT_AREA:
        return None
    canvas = Image.new("RGBA", (round(width), round(height)), (0, 0, 0, 0))
    root_pivot_x, root_pivot_y = _vec2(root.rect.get("m_Pivot", {}), 0.5, 0.5)
    layout = Layout(0.0, 0.0, width, height, root_pivot_x, root_pivot_y)
    _draw_node(canvas, root_id, layout, rects, images, sprites)
    if not canvas.getbbox():
        return None

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
    return output_path


def _export_sprites_directly(
    bundle: Path,
    sprites: dict[int, SpriteInfo],
    output_dir: Path,
    exclude: set[str] | None = None,
) -> list[Path]:
    written: list[Path] = []
    for sprite in sprites.values():
        if exclude and sprite.name in exclude:
            continue
        width, height = sprite.image.size
        if not sprite.name.startswith("bg_") or width * height < MIN_OUTPUT_AREA:
            continue
        output_path = output_dir / bundle.stem / f"{_safe_name(sprite.name)}.png"
        if not output_path.exists():
            output_path.parent.mkdir(parents=True, exist_ok=True)
            sprite.image.save(output_path)
        written.append(output_path)
    return written


def _find_variant_groups(sprites: dict[int, SpriteInfo]) -> dict[int, list[int]]:
    """Return {base_id: [variant_id, ...]} for sprites named bg_X + bg_X_N (all-digit suffix)."""
    names_to_ids: dict[str, int] = {s.name: sid for sid, s in sprites.items() if s.name}
    groups: dict[int, list[int]] = {}
    for sid, s in sprites.items():
        m = re.match(r"^(.+)_\d+$", s.name)
        if not m:
            continue
        parent_id = names_to_ids.get(m.group(1))
        if parent_id is None:
            continue
        groups.setdefault(parent_id, []).append(sid)
    return groups


def _is_legacy_bg_root(node: RectNode) -> bool:
    name = node.name.lower()
    return "---bg---" in name or "----bg----" in name or name in {"bgroot", "bg", "imgbgroot"}


def _looks_like_image_node(name: str) -> bool:
    """Return True for nodes that are likely Unity Image holders, not layout containers."""
    n = name.lower()
    if n.endswith("root"):
        return False
    if n.startswith("uiparticle") or n.startswith("light"):
        return False
    return "img" in n or (n.startswith("bg") and "---" not in n)


def _match_sprites_to_layouts(
    root_id: int,
    rects: dict[int, RectNode],
    root_layout: Layout,
    sprites: dict[int, SpriteInfo],
    candidate_ids: set[int] | None = None,
) -> list[tuple[SpriteInfo, Layout]]:
    """Walk the subtree (skipping root itself) and match bg_ sprites to image-bearing nodes."""
    candidates = [
        (sid, s) for sid, s in sprites.items()
        if s.name.startswith("bg_") and s.image.size[0] * s.image.size[1] >= MIN_SPRITE_AREA
        and (candidate_ids is None or sid in candidate_ids)
    ]
    used: set[int] = set()
    result: list[tuple[SpriteInfo, Layout]] = []

    def visit(node_id: int, layout: Layout, is_root: bool) -> None:
        if node_id not in rects:
            return
        node = rects[node_id]
        w, h = layout.width, layout.height
        if not is_root and _looks_like_image_node(node.name) and w > 10 and h > 10:
            best_sid: int | None = None
            best_score = float("inf")
            node_ratio = w / h if h else 0.0
            for sid, s in candidates:
                if sid in used:
                    continue
                sw, sh = s.image.size
                size_diff = abs(sw - w) + abs(sh - h)
                if size_diff < 10 and size_diff < best_score:
                    best_score, best_sid = size_diff, sid
            if best_sid is None:
                for sid, s in candidates:
                    if sid in used:
                        continue
                    sw, sh = s.image.size
                    sprite_ratio = sw / sh if sh else 0.0
                    ratio_err = abs(sprite_ratio - node_ratio) / node_ratio if node_ratio else 1.0
                    if ratio_err < 0.015 and ratio_err < best_score:
                        best_score, best_sid = ratio_err, sid
            if best_sid is not None:
                used.add(best_sid)
                result.append((sprites[best_sid], layout))
        for child_id in node.child_ids:
            if child_id in rects:
                visit(child_id, _child_layout(layout, rects[child_id]), False)

    visit(root_id, root_layout, True)
    return result


def _export_legacy_composites(
    bundle: Path,
    rects: dict[int, RectNode],
    sprites: dict[int, SpriteInfo],
    output_dir: Path,
) -> tuple[list[Path], set[str]]:
    """
    For old bundles where Image components can't be read, reconstruct backgrounds
    via size/ratio matching.  Returns (paths_written, sprite_names_used).

    Pass 1 — naming-group composites: sprites named bg_X plus bg_X_1, bg_X_2 …
    are composited together (base at canvas origin, variants layout-matched).

    Pass 2 — root-based composites: any remaining sprites are matched to Unity
    RectTransform subtrees hanging off legacy bg-root nodes.
    """
    written: list[Path] = []
    used_sprite_names: set[str] = set()
    used_sprite_ids: set[int] = set()
    seen_sprite_sets: set[frozenset[str]] = set()

    bg_root_ids = [nid for nid, node in rects.items() if _is_legacy_bg_root(node)]

    def _root_canvas(root_id: int) -> tuple[float, float]:
        node = rects[root_id]
        sd = node.rect.get("m_SizeDelta", {})
        anchor_min_x, anchor_min_y = _vec2(node.rect.get("m_AnchorMin", {}), 0.5, 0.5)
        anchor_max_x, anchor_max_y = _vec2(node.rect.get("m_AnchorMax", {}), 0.5, 0.5)
        if anchor_max_x - anchor_min_x > 0.5 or anchor_max_y - anchor_min_y > 0.5:
            return ROOT_SIZE
        canvas_w = abs(sd.get("x", 0.0)) or ROOT_SIZE[0]
        canvas_h = abs(sd.get("y", 0.0)) or ROOT_SIZE[1]
        return canvas_w, canvas_h

    def _write_composite(layers: list[tuple[SpriteInfo, Layout]], canvas_w: float, canvas_h: float, output_path: Path) -> None:
        if output_path.exists():
            return
        canvas = Image.new("RGBA", (round(canvas_w), round(canvas_h)), (0, 0, 0, 0))
        for sprite, layout in layers:
            if layout.width < 1 or layout.height < 1:
                continue
            img = sprite.image.resize(
                (max(1, round(layout.width)), max(1, round(layout.height))),
                Image.Resampling.LANCZOS,
            )
            canvas.alpha_composite(img, (round(layout.left), round(layout.top)))
        if not canvas.getbbox():
            return
        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output_path)

    # === Pass 1: naming-group composites ===
    # Group sprites by naming convention: bg_X is the base of bg_X_1, bg_X_2, …
    groups = _find_variant_groups(sprites)
    for base_id, variant_ids in groups.items():
        base_sprite = sprites[base_id]

        # Among all bg_roots, find the one whose subtree best matches the variants.
        best_matches: list[tuple[SpriteInfo, Layout]] = []
        best_canvas: tuple[float, float] = ROOT_SIZE

        for root_id in bg_root_ids:
            canvas_w, canvas_h = _root_canvas(root_id)
            if canvas_w < 1000 or canvas_h < 700:
                continue
            node = rects[root_id]
            piv_x, piv_y = _vec2(node.rect.get("m_Pivot", {}), 0.5, 0.5)
            root_layout = Layout(0.0, 0.0, canvas_w, canvas_h, piv_x, piv_y)
            matches = _match_sprites_to_layouts(
                root_id, rects, root_layout, sprites,
                candidate_ids=set(variant_ids),
            )
            if len(matches) > len(best_matches):
                best_matches = matches
                best_canvas = (canvas_w, canvas_h)

        if not best_matches:
            continue

        canvas_w, canvas_h = best_canvas
        base_layout = Layout(0.0, 0.0, canvas_w, canvas_h, 0.5, 0.5)
        all_layers = [(base_sprite, base_layout)] + best_matches

        sprite_key = frozenset(s.name for s, _ in all_layers)
        if sprite_key in seen_sprite_sets:
            used_sprite_names.update(sprite_key)
            used_sprite_ids.add(base_id)
            used_sprite_ids.update(variant_ids)
            continue
        seen_sprite_sets.add(sprite_key)

        output_path = output_dir / bundle.stem / f"{_safe_name(base_sprite.name)}.png"
        _write_composite(all_layers, canvas_w, canvas_h, output_path)
        written.append(output_path)
        used_sprite_names.update(sprite_key)
        used_sprite_ids.add(base_id)
        used_sprite_ids.update(variant_ids)

    # === Pass 2: root-based composites (remaining sprites only) ===
    remaining_sprites = {sid: s for sid, s in sprites.items() if sid not in used_sprite_ids}
    for root_id in bg_root_ids:
        canvas_w, canvas_h = _root_canvas(root_id)
        if canvas_w < 1000 or canvas_h < 700:
            continue
        node = rects[root_id]
        pivot_x, pivot_y = _vec2(node.rect.get("m_Pivot", {}), 0.5, 0.5)
        root_layout = Layout(0.0, 0.0, canvas_w, canvas_h, pivot_x, pivot_y)
        matched = _match_sprites_to_layouts(root_id, rects, root_layout, remaining_sprites)
        if not matched:
            continue

        sprite_key = frozenset(s.name for s, _ in matched)
        if sprite_key in seen_sprite_sets:
            used_sprite_names.update(sprite_key)
            continue
        seen_sprite_sets.add(sprite_key)

        path_name = _safe_name(_node_path(root_id, rects))
        output_path = output_dir / bundle.stem / f"{path_name}.png"
        _write_composite(matched, canvas_w, canvas_h, output_path)
        written.append(output_path)
        used_sprite_names.update(sprite_key)

    return written, used_sprite_names


def _activity_bundles() -> list[Path]:
    bundles = [
        bundle
        for bundle in get_unity3d_files() + list((data_dir.parent / "OldAssets").glob("*.unity3d"))
        if bundle.name.startswith("ui_activity")
        and bundle.suffix == ".unity3d"
        and not bundle.name.endswith(".en.unity3d")
    ]
    return sorted(bundles, key=lambda path: path.name)


def export_event_images() -> list[Path]:
    output_dir = Path("assets") / "event_bgs"
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    bundles = _activity_bundles()
    print(f"Processing {len(bundles)} ui_activity bundles...")
    for index, bundle in enumerate(bundles, start=1):
        try:
            rects, _, images, sprites = _read_bundle(bundle)
            roots = _find_roots(rects, images, sprites)
            bundle_written: list[Path] = []
            for root_id in roots:
                output_path = _export_root(bundle, root_id, rects, images, sprites, output_dir)
                if output_path:
                    bundle_written.append(output_path)
                    written.append(output_path)
            if not bundle_written and not images:
                composites, used_names = _export_legacy_composites(bundle, rects, sprites, output_dir)
                leftovers = _export_sprites_directly(bundle, sprites, output_dir, exclude=used_names)
                bundle_written = composites + leftovers
                written.extend(bundle_written)
            if bundle_written:
                print(f"[{index}/{len(bundles)}] {bundle.name}: wrote {len(bundle_written)} images")
            else:
                print(f"[{index}/{len(bundles)}] {bundle.name}: no large backgrounds found")
        except Exception as e:
            print(f"WARNING: Failed to process {bundle.name}: {e}")
    print(f"Wrote {len(written)} images to {output_dir}")
    return written


def main() -> None:
    export_event_images()


if __name__ == "__main__":
    main()
