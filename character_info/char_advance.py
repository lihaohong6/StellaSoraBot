from dataclasses import field, dataclass
from functools import cache

from wikitextparser import Template, parse

from character_info.characters import get_character_pages, get_characters, Character
from page_generators.items import get_all_items, make_item_template
from utils.data_utils import autoload
from utils.wiki_utils import set_arg, force_section_text, save_page


@dataclass
class AdvanceMaterial:
    gold: int
    items: list[tuple[int, int]] = field(default_factory=list)


@cache
def get_char_advance_material() -> dict[int, list[AdvanceMaterial]]:
    data = autoload("CharacterAdvance")
    result: dict[int, list[AdvanceMaterial]] = {}
    for k, v in data.items():
        char = v['Group']
        if char not in result:
            result[char] = []
        material = AdvanceMaterial(v['GoldQty'])
        for index in range(1, 10):
            item_id = v.get(f"Tid{index}", None)
            if item_id is None:
                break
            quantity = v[f'Qty{index}']
            material.items.append((item_id, quantity))
        result[char].append(material)
    return result


def update_character_advancement_material():
    chars = get_characters()
    for char_name, page in get_character_pages().items():
        char = chars[char_name]
        parsed = parse(page.text)
        t = make_character_advancement_template(char)
        force_section_text(parsed, "Upgrade materials", str(t), "Gallery")
        save_page(page, str(parsed), "update character upgrade material")


def make_character_advancement_template(char: Character) -> Template:
    items = get_all_items()
    material_list = get_char_advance_material()[char.id]
    t = Template("{{TrekkerUpgradeMaterials\n}}")
    for index, material in enumerate(material_list, 1):
        if len(material.items) == 0:
            break
        item_list = []
        for item_id, quantity in material.items:
            item_list.append(str(make_item_template(items[item_id], quantity)))
        item_list.append(str(make_item_template(items[1], material.gold)))
        set_arg(t, f"level{index}", " ".join(item_list))
    return t


def main():
    update_character_advancement_material()


if __name__ == '__main__':
    main()
