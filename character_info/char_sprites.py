import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from PIL import Image
from wikitextparser import Template, parse

from character_info.characters import id_to_char, Character, get_character_pages, get_characters
from utils.data_utils import assets_root, sprite_root, load_lua_table, lua_root
from utils.upload_utils import UploadRequest, process_uploads
from utils.wiki_utils import save_json_page, set_arg, save_page, PageCreationRequest, process_page_creation_requests, \
    find_templates_by_name, find_section


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


def compute_offsets(base: SpriteData, top: SpriteData, bh: float, th: float) -> tuple[int, int]:
    off_x = top.x - base.x
    off_y = (bh - th) + (base.y - top.y)
    return int(round(off_x)), int(round(off_y))


def compose(base: Sprite, top: Sprite, out: Path) -> None:
    base_image = Image.open(base.source).convert("RGBA")
    top_image = Image.open(top.source).convert("RGBA")

    canvas_size = (4096, 4096)
    canvas_color = (0, 0, 0, 0)

    anchor_x, anchor_y = 1024, 1024
    canvas1 = Image.new("RGBA", canvas_size, canvas_color)
    canvas1.paste(base_image, (anchor_x, anchor_y))

    if base_image.size == top_image.size:
        off_x, off_y = 0, 0
    else:
        base_height = base_image.size[1]
        top_height = top_image.size[1]
        off_x, off_y = compute_offsets(base.json_data, top.json_data, base_height, top_height)
    canvas2 = Image.new("RGBA", canvas_size, canvas_color)
    canvas2.paste(top_image, (anchor_x + off_x, anchor_y + off_y))

    combined = Image.alpha_composite(canvas1, canvas2)
    bbox = combined.getbbox()
    if bbox:
        combined = combined.crop(bbox)
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
    "Aeloria Rose": {"a"},
    "Albedo": {"a"},
    "Amber": {"a", "b", "c", "d", "e", "f", "g", },
    "Angie": {"a", "b"},
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
    "Cosson": {"a"},
    "Darcia": {"a", "b", "c", "d"},
    "Donna": {"a"},
    "Eleanor": {"b"},
    "Fannie": {"a"},
    "Feagin": {"a"},
    "Female tyrant": {"a", "b", "c", "d", "e", "f", "g", "h", "i", "l"},
    "Firefly": {"a", "b"},
    "Firenze": {"a", "b", "c", "d"},
    "Flora": {"b"},
    "Freesia": {"a", "b", "c", "d"},
    "Fuyuka": {"a", "b", },
    "Gerie": {"a", },
    "Horizon": {"a"},
    "Igna": {"a"},
    "Iris": {"a", "b", "c", "d", "e"},
    "Isaki": {"a"},
    "Jayhawk": {"a"},
    "Jinglin": {"a"},
    "Kaede": {"a"},
    "Karin": {"a", "b", "c", "d"},
    "Kaydoke": {"a"},
    "Kasimira": {"a"},
    "Lady Gray": {"a"},
    "Laru": {"a", "b"},
    "Leafia": {"a"},
    "Male tyrant": {"a", "b", "c", "d", "e", "f", "g", "h", "i", "l"},
    "Marlene": {"a", "b"},
    "Mina": {"a"},
    "Minova": {"a", "b"},
    "Miss Witch": {"a"},
    "Mistique": {"a", "b", "c", "e", },
    "Nanoha": {"a", "b"},
    "Nazuka": {"a", "c"},
    "Nazuna": {"a", "b"},
    "Neuvira": {"a", },
    "Noya": {"a", "b", "c", "d", "e", },
    "Nuz": {"a"},
    "Nyx": {"a", "b"},
    "Okra": {"a"},
    "Ophir": {"a"},
    "Portia": {"a"},
    "Ridge": {"a"},
    "Ruby": {"a"},
    "Sapphire": {"a"},
    "Serena": {"a"},
    "Shia": {"a", "b"},
    "Shimiao": {"a"},
    "Snowish Laru": {"a", "b"},
    "Teresa": {"a"},
    "Tilia": {"a", "b", "c", "d", "e", },
    "Noctiluna": {"a"},
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
    data: list[dict] = load_lua_table("game/ui/avg/_en/preset/avgcharacter.lua")
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


def find_sprites_in_dir(variant_dir: Path, variant_name: str) -> list[Sprite]:
    sprites = []
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
    return sprites


def process_char_sprites(char: Character | AvgCharacter, char_dir: Path) -> dict[str, list[Sprite]]:
    image_dir = char_dir / "atlas_png"
    images: dict[str, list[Sprite]] = {}
    for variant_dir in image_dir.iterdir():
        if not variant_dir.is_dir():
            continue
        variant_name = variant_dir.name
        sprites = find_sprites_in_dir(variant_dir, variant_name)
        if len(sprites) == 0:
            continue
        images[variant_name] = sprites
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
    root2 = assets_root / "actor2d/character"
    assert root2.exists()
    for char_name, char in get_characters().items():
        for dir_suffix, variant_name in [('02', 'awakened'), ('03', 'skin1')]:
            char_dir = root2 / f'{char.id}{dir_suffix}' / 'atlas_png' / 'a'
            if not char_dir.exists():
                continue
            sprites = find_sprites_in_dir(char_dir, variant_name)
            if len(sprites) == 0:
                continue
            char_sprites[char.name][variant_name] = sprites
            process_assets(sprites, char, variant_name)
    return char_sprites


def filter_sprites(char_name: str, sprite_dict: dict[str, list[Sprite]]) -> dict[str, list[Sprite]]:
    result = {}
    for variant in sorted(sprite_dict.keys()):
        if len(variant) == 1 and variant not in variant_whitelist[char_name]:
            continue
        sprites = sprite_dict[variant]
        # Manually exclude a bad image
        if char_name == "Tilia" and variant == "awakened":
            sprites = [sp for sp in sprites if sp.number != 4]
        result[variant] = sprites
    return result


@cache
def get_char_sprites() -> dict[str, dict[str, list[Sprite]]]:
    result: dict[str, dict[str, list[Sprite]]] = {}
    sprites = export_sprites()
    for char_name, sprite_dict in sprites.items():
        if char_name not in variant_whitelist:
            continue
        result[char_name] = filter_sprites(char_name, sprite_dict)
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
            page=f"Category:{char_name} images",
            text="{{Catnav|Images by character}}\n[[Category:Images by character]]",
            summary="create character image categories"
        ))
        page_creation_requests.append(PageCreationRequest(
            page=f"Category:{char_name} sprites",
            text="{{Catnav|Sprites by character}}\n[[Category:Sprites by character]]\n"
                 f"[[Category:{char_name} images]]",
            summary="create sprite categories"
        ))
    process_uploads(upload_requests)
    process_page_creation_requests(page_creation_requests, overwrite=True)
    save_json_page("Module:Sprite/data.json", json_data, summary="update json page")


def sprites_to_template(char: str, sprites: dict[str, list[Sprite]], skip: set[str]) -> str:
    result = []
    sprites = dict((k, v) for k, v in sprites.items() if len(v) > 0)
    for variant_name in sprites.keys():
        if variant_name in skip:
            continue
        t = Template("{{Sprite\n}}")
        set_arg(t, "char", char)
        set_arg(t, "variant", variant_name)
        if len(variant_name) == 1:
            name = f"Variant {variant_name.upper()}"
        else:
            name = variant_name.capitalize()
        if len(sprites) == 1:
            name = "Default"
        set_arg(t, "name", name)
        result.append(str(t))
    return "\n\n".join(result)


def create_gallery_pages():
    all_sprites = get_char_sprites()
    for char, page in get_character_pages("/gallery", must_exist=False).items():
        if char.name not in all_sprites:
            continue
        char_sprites = all_sprites[char.name]
        parsed = parse(page.text)
        sprite_templates = find_templates_by_name(parsed, "Sprite")
        skip: set[str] = set()
        for sprite in sprite_templates:
            variant = sprite.get_arg("variant").value.strip()
            skip.add(variant)
        templates = sprites_to_template(char.name, char_sprites, skip)
        if not page.exists():
            save_page(page, f"""{{{{GalleryTop}}}}
==Sprites==
{templates}
{{{{GalleryBottom}}}}
""", "batch update gallery page")
        elif len(char_sprites) - len(skip) > 0:
            # There are new sprites. Do an incremental update.
            if len(sprite_templates) > 0:
                sprite_templates[-1].string = sprite_templates[-1].string.rstrip() + "\n\n" + str(templates)
            else:
                find_section(parsed, "Sprites").contents = str(templates)
            save_page(page, str(parsed), "batch update gallery page")


def char_gallery_page():
    upload_sprites()
    create_gallery_pages()


def main():
    char_gallery_page()


if __name__ == '__main__':
    main()
