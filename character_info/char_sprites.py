import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from PIL import Image
from wikitextparser import Template

from character_info.characters import id_to_char, Character, get_character_pages
from utils.data_utils import assets_root, sprite_root, load_lua_table, lua_root
from utils.upload_utils import UploadRequest, process_uploads
from utils.wiki_utils import save_json_page, set_arg, save_page, PageCreationRequest, process_page_creation_requests


@dataclass
class SpriteData:
    x: float
    y: float
    width: float
    height: float


@dataclass
class Sprite:
    number: int
    source: Path
    json_data: SpriteData
    combined: Path | None = None

    def get_sprite_path(self, char_name: str, sprite_name: str) -> Path:
        base = sprite_root / char_name
        return base / f"{char_name}_{sprite_name}_{self.number:02d}.png"


def compute_offsets(base: SpriteData, top: SpriteData) -> tuple[int, int]:
    """
    Compute the sprite layout offset. Idea and code came from Hiro (Hiro420).
    :param base:
    :param top:
    :return:
    """
    center_x1 = base.x + base.width / 2.0
    center_y1 = base.y + base.height / 2.0
    center_x2 = top.x + top.width / 2.0
    center_y2 = top.y + top.height / 2.0

    dx = center_x2 - center_x1
    dy = center_y2 - center_y1

    # Base/top image sizes (should match bw/bh and tw/th closely)
    base_w, base_h = int(round(base.width)), int(round(base.height))
    top_w, top_h = int(round(top.width)), int(round(top.height))

    base_center_x = base_w / 2.0
    base_center_y = base_h / 2.0
    top_pivot_x = top_w / 2.0
    top_pivot_y = top_h / 2.0

    # Final offsets, matching the derived formulas
    offset_x = int(round(base_center_x + dx - top_pivot_x))
    offset_y = int(round(base_center_y - dy - top_pivot_y))

    return offset_x, offset_y


def compose(base: Sprite, top: Sprite, out: Path) -> None:
    base_image = Image.open(base.source).convert("RGBA")
    top_image = Image.open(top.source).convert("RGBA")

    offset_x, offset_y = compute_offsets(base.json_data, top.json_data)
    overlay_layer = Image.new("RGBA", base_image.size, (0, 0, 0, 0))
    overlay_layer.paste(top_image, (offset_x, offset_y))
    combined = Image.alpha_composite(base_image, overlay_layer)
    combined.save(out)
    print(f"Saved {out}")


def process_assets(sprites: list[Sprite], char: Character, variant_name: str) -> None:
    assert sprites[0].number == 1
    base = sprites[0]
    for top in sprites[1:]:
        out = top.get_sprite_path(char.name, variant_name)
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.exists():
            compose(base, top, out)
        top.combined = out


def retrieve_sprite_json_data(f: Path) -> SpriteData | None:
    data = json.load(open(f, "r", encoding="utf-8"))
    try:
        data = data['m_RD']['textureRect']
    except KeyError:
        print(f"Failed to retrieve sprite json data on {f}")
        return None
    return SpriteData(data['x'], data['y'], data['width'], data['height'])


variant_whitelist: dict[str, set[str]] = {
    "Aeloria": {"a", "b"},
    "Albedo": {"a"},
    "Amber": {"a", "b", "c", "f", "g", },
    "Ann": {"a"},
    "Bastelina": {"a"},
    "Beatrixa": {"a"},
    "Bernina": {"a", },
    "Bloc": {"a"},
    "Canace": {"a", },
    "Caramel": {"a"},
    "Chitose": {"a", "b"},
    "Chixia": {"a"},
    "Claire": {"a"},
    "Coronis": {"a"},
    "Cosette": {"a", "b"},
    "Donna": {"a"},
    "Eleanor": {"b"},
    "Fannie": {"a"},
    "Feagin": {"a"},
    "Female tyrant": {"a", "b", "c", "f", "g", "h", "i", },
    "Firenze": {"c"},
    "Flora": {"b"},
    "Freesia": {"a", "b"},
    "Fuyuka": {"a"},
    "Gerie": {"a", },
    "Horizon": {"a"},
    "Iris": {"a", "b", "d", "e"},
    "Isaki": {"a"},
    "Jinglin": {"a"},
    "Kaede": {"a"},
    "Karin": {"a", "d"},
    "Kaydoke": {"a"},
    "Kasimira": {"a"},
    "Laru": {"a"},
    "Leafia": {"a"},
    "Male tyrant": {"a", "b", "c", "f", "g", "h", "i", },
    "Marlene": {"a", "b"},
    "Minova": {"a", "b"},
    "Mistique": {"a", "c"},
    "Nanoha": {"a", "b"},
    "Nazuka": {"a", },
    "Nazuna": {"a", "b"},
    "Neuvira": {"a", },
    "Noya": {"a", "b", "d", "e", },
    "Okra": {"a"},
    "Ophir": {"a"},
    "Portia": {"a"},
    "Ridge": {"a"},
    "Serena": {"a"},
    "Shia": {"a", },
    "Shimiao": {"a"},
    "Teresa": {"a"},
    "Tilia": {"a", "b", "c", "d", "e", },
    "Virigia": {"a"},
    "Vollara": {"a"},
    "Willow": {"a", },
}


@dataclass
class AvgCharacter:
    id: str
    name: str
    bg_color: str | None = None
    reuse: str | None = None


@cache
def get_avg_characters() -> tuple[dict[str, AvgCharacter], dict[str, str]]:
    file = lua_root / "game/ui/avg/_en/preset/avgcharacter.lua"
    data: list[dict] = load_lua_table(file)
    result: dict[str, AvgCharacter] = {}
    reuse_table: dict[str, str] = {}
    for row in data:
        char_id = row['id']
        name = row['name']
        if char_id == 'avg3_100':
            name = 'Female tyrant'
        if char_id == 'avg3_101':
            name = 'Male tyrant'
        reuse: str | None = row.get('reuse', None)
        result[char_id] = AvgCharacter(char_id, name, row['name_bg_color'], reuse)
        if reuse is not None:
            reuse_table[char_id] = reuse
    return result, reuse_table


def process_char_sprites(char: Character | AvgCharacter, char_dir: Path) -> dict[str, list[Sprite]]:
    image_dir = char_dir / "atlas_png"
    images: dict[str, list[Sprite]] = {}
    for variant_dir in image_dir.iterdir():
        if not variant_dir.is_dir():
            continue
        sprites = []
        variant_name = variant_dir.name
        images[variant_name] = sprites
        for f in variant_dir.glob("*.png"):
            m = re.search(r"_(\d{3})\.", f.name)
            if not m:
                continue
            num = int(m.group(1))
            json_file = f.with_suffix(".json")
            if not json_file.exists():
                print(f"skipping {variant_name}/{f.name} because the json file does not exist")
                continue
            sprites.append(Sprite(num, f, retrieve_sprite_json_data(json_file)))
        sprites.sort(key=lambda s: s.number)
        if len(sprites) == 0:
            continue
        process_assets(sprites, char, variant_name)
    return images


def export_sprites() -> dict[str, dict[str, list[Sprite]]]:
    root = assets_root / "actor2d/characteravg"
    avg_chars, reuse_table = get_avg_characters()
    char_sprites: dict[str, dict[str, list[Sprite]]] = {}
    for char_dir in sorted(root.iterdir(), key=lambda p: p.name):
        if not char_dir.is_dir():
            continue
        char_id_match = re.search(r"avg1_(\d{3})", char_dir.name)
        char: Character | AvgCharacter | None = None
        if char_id_match:
            char_id = char_id_match.group(1)
            char = id_to_char(int(char_id))
        dir_name = char_dir.name
        if char is None:
            char = avg_chars.get(dir_name)
        if char is None and dir_name in reuse_table:
            char = avg_chars.get(reuse_table[dir_name])
        if char is None:
            char = AvgCharacter(char_dir.name, char_dir.name)
        if char.name in char_sprites:
            continue
        char_sprites[char.name] = process_char_sprites(char, char_dir)
    return char_sprites


@cache
def get_char_sprites() -> dict[str, dict[str, list[Sprite]]]:
    result: dict[str, dict[str, list[Sprite]]] = {}
    sprites = export_sprites()
    for char_name, sprite_dict in sprites.items():
        if char_name not in variant_whitelist:
            continue
        result[char_name] = dict(
            (variant, sprite_dict[variant])
            for variant in sorted(sprite_dict.keys())
            if variant in variant_whitelist[char_name]
        )
    return result


def upload_sprites():
    sprites = get_char_sprites()
    upload_requests = []
    page_creation_requests = []
    json_data: dict[str, dict[str, list[str]]] = {}
    for char_name, sprite_dict in sprites.items():
        json_data[char_name] = {}
        for variant_name, sprite_list in sprite_dict.items():
            json_data[char_name][variant_name] = []
            for sprite in sprite_list:
                if sprite.number == 1:
                    continue
                assert sprite.combined is not None
                upload_requests.append(UploadRequest(
                    sprite.combined,
                    sprite.combined.name,
                    f'[[Category:{char_name} sprites]]',
                    summary='batch upload sprites'
                ))
                json_data[char_name][variant_name].append(sprite.combined.stem.split("_")[-1])
        page_creation_requests.append(PageCreationRequest(
            page=f"Category:{char_name} sprites",
            text="[[Category:Sprites by character]]",
            summary="create sprite categories"
        ))
    process_uploads(upload_requests)
    process_page_creation_requests(page_creation_requests)
    save_json_page("Module:Sprite/data.json", json_data, summary="update json page")


def sprites_to_template(char: str, sprites: dict[str, list[Sprite]]) -> str:
    result = []
    sprites = dict((k, v) for k, v in sprites.items() if len(v) > 0)
    for variant_name in sprites.keys():
        t = Template("{{Sprite\n}}")
        set_arg(t, "char", char)
        set_arg(t, "variant", variant_name)
        name = f"Variant {variant_name.upper()}"
        if len(sprites) == 1:
            name = "Default"
        set_arg(t, "name", name)
        result.append(str(t))
    return "\n\n".join(result)


def create_gallery_pages():
    sprites = get_char_sprites()
    for char, page in get_character_pages("/gallery", must_exist=False).items():
        templates = sprites_to_template(char.name, sprites[char.name])
        if not page.exists():
            save_page(page, f"""{{{{GalleryTop}}}}
==Sprites==
{templates}
{{{{GalleryBottom}}}}
""", "batch update gallery page")


def main():
    upload_sprites()
    create_gallery_pages()


if __name__ == '__main__':
    main()
