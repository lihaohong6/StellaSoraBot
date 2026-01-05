from collections import defaultdict
from dataclasses import field, dataclass
from functools import cache

from wikitextparser import Template, parse

from character_info.characters import get_character_pages, Character
from page_generators.items import get_all_items, make_item_template
from utils.data_utils import autoload
from utils.wiki_utils import set_arg, force_section_text, save_page, find_section


@dataclass
class AdvanceMaterial:
    gold: int = 0
    items: list[tuple[int, int]] = field(default_factory=list)

    def __add__(self, other):
        if isinstance(other, AdvanceMaterial):
            items: dict[int, int] = defaultdict(int)
            for item_id, quantity in self.items + other.items:
                items[item_id] += quantity
            return AdvanceMaterial(self.gold + other.gold, [(k, v) for k, v in items.items()])
        raise NotImplementedError()


@cache
def get_advancement_material(file: str) -> dict[int, list[AdvanceMaterial]]:
    data = autoload(file)
    result: dict[int, list[AdvanceMaterial]] = {}
    for k, v in data.items():
        char = v['Group']
        if char not in result:
            result[char] = []
        gold = v.get('GoldQty', None)
        if gold is None:
            continue
        material = AdvanceMaterial(gold)
        for index in range(1, 10):
            item_id = v.get(f"Tid{index}", None)
            if item_id is None:
                break
            quantity = v[f'Qty{index}']
            material.items.append((item_id, quantity))
        result[char].append(material)
    return result


def get_char_advance_material() -> dict[int, list[AdvanceMaterial]]:
    return get_advancement_material("CharacterAdvance")


def get_char_skill_material() -> dict[int, list[AdvanceMaterial]]:
    return get_advancement_material("CharacterSkillUpgrade")


def make_character_skill_advancement_template(char: Character) -> Template:
    material_list = get_char_skill_material()[char.id]
    t = Template("{{TrekkerSkillMaterials\n}}")
    return material_list_to_template(t, material_list)


def make_character_advancement_template(char: Character) -> Template:
    material_list = get_char_advance_material()[char.id]
    t = Template("{{TrekkerUpgradeMaterials\n}}")
    return material_list_to_template(t, material_list)


def upgrade_material_to_string(material: AdvanceMaterial) -> str:
    if len(material.items) == 0:
        return ""
    items = get_all_items()
    item_list = []
    for item_id, quantity in material.items:
        item_list.append(str(make_item_template(items[item_id], quantity)))
    item_list.append(str(make_item_template(items[1], material.gold)))
    return " ".join(item_list)


def material_list_to_template(t: Template, material_list: list[AdvanceMaterial]) -> Template:
    for index, material in enumerate(material_list, 1):
        material_string = upgrade_material_to_string(material)
        set_arg(t, f"level{index}", material_string)
    return t


def main():
    pass


if __name__ == '__main__':
    main()
