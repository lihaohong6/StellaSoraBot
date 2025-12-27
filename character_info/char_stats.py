from collections import defaultdict
from dataclasses import dataclass

from wikitextparser import Template

from character_info.char_advance import AdvanceMaterial, get_char_advance_material
from character_info.char_affinity import AffinityLevel, get_affinity_levels
from character_info.char_talents import get_talent_levels, TalentLevel
from character_info.characters import Character, id_to_char, get_characters, get_character_pages
from page_generators.items import make_item_template, get_all_items
from utils.data_utils import autoload
from utils.stat_utils import StatBonus
from utils.wiki_utils import set_arg


@dataclass
class LevelStats:
    level: int
    breakthrough: int
    attack: int
    hp: int
    defense: int


def get_char_stats() -> dict[Character, list[LevelStats]]:
    data = autoload("Attribute")
    result = defaultdict(list)
    for _, v in data.items():
        char = id_to_char(v['GroupId'])
        if char is None:
            continue
        stats = LevelStats(
            level=v['lvl'],
            breakthrough=v.get('Break', 0),
            attack=v['Atk'],
            hp=v['Hp'],
            defense=v['Def'],
        )
        result[char].append(stats)
    return result


def join_on_attribute(lst: list[StatBonus], attrib: str) -> str:
    return ",".join(str(getattr(b, attrib)) for b in lst)


def char_stats_to_template(stats: list[LevelStats],
                           advancement_materials: list[AdvanceMaterial],
                           affinity_levels: list[StatBonus],
                           talent_levels: list[StatBonus]) -> str:
    result = []

    control = Template("{{StatDisplay/control\n}}")
    set_arg(control, "name", "level")
    set_arg(control, "label", "Level: ")
    levels = [str(stat.level) for stat in stats if stat.level < 91]
    levels = [(level if levels[i - 1] != level else level + "+") for i, level in enumerate(levels)]
    set_arg(control, "levels", ",".join(levels))
    result.append(str(control))

    control = Template("{{StatDisplay/control\n}}")
    set_arg(control, "name", "affinity")
    set_arg(control, "label", "Affinity: ")
    set_arg(control, "levels", ",".join(str(i) for i in range(0, 51)))
    result.append(str(control))

    control = Template("{{StatDisplay/control\n}}")
    set_arg(control, "name", "talent")
    set_arg(control, "label", "Talent: ")
    set_arg(control, "levels", ",".join(str(i // 2 if i % 2 == 0 else i / 2) for i in range(0, 11)))
    result.append(str(control))

    result.append("<hr/>")
    result.append('<div class="stat-data-container">')
    for attr, label, name in [
        ('hp', 'HP', 'level'),
        ('attack', 'Attack', 'level'),
        ('defense', 'Defense', 'level'),
    ]:
        t = Template("{{StatDisplay/value\n}}")
        set_arg(t, "label", label)
        set_arg(t, "name1", name)
        set_arg(t, "values1", ",".join(str(getattr(stat, attr)) for stat in stats))
        if attr == 'attack':
            index = 2
            for arg_name, arg_values in [
                ('affinity1', join_on_attribute(affinity_levels, 'attack')),
                ('affinity2', join_on_attribute(affinity_levels, 'attack_pct')),
                ('talent1', join_on_attribute(talent_levels, 'attack')),
                ('talent2', join_on_attribute(talent_levels, 'attack_pct'))
            ]:
                set_arg(t, f"name{index}", arg_name)
                set_arg(t, f"values{index}", arg_values)
                index += 1
            # Round down
            set_arg(t, 'formula', '(level + affinity1 + talent1) * (1 + affinity2 + talent2) - 0.5')
        if attr == 'hp':
            set_arg(t, "name2", 'affinity')
            set_arg(t, 'values2', join_on_attribute(affinity_levels, 'hp'))
            set_arg(t, 'name3', 'talent')
            set_arg(t, 'values3', join_on_attribute(talent_levels, 'hp'))
            set_arg(t, "formula", 'level + affinity + talent')
        if attr == 'defense':
            set_arg(t, "name2", "talent")
            set_arg(t, "values2", join_on_attribute(talent_levels, "defense"))
            set_arg(t, "formula", "level + talent")
        result.append(str(t))
    result.append("</div>")

    t = Template("{{StatDisplay/children\n}}")
    set_arg(t, "name", "level")
    set_arg(t, "children", ",".join(str(stat.breakthrough + 1) for stat in stats))
    items = get_all_items()
    for index, material in enumerate(advancement_materials, 1):
        if len(material.items) == 0:
            break
        item_list = []
        for item_id, quantity in material.items:
            item_list.append(str(make_item_template(items[item_id], quantity)))
        item_list.append(str(make_item_template(items[1], material.gold)))
        set_arg(t, str(index), f"<div>Breakthrough material at level {index * 10}: " + "".join(item_list) + "</div>")
    result.append(str(t))

    t = Template("{{StatDisplay\n}}")
    t.set_arg("1", "\n".join(result))
    return str(t)


def main():
    for char, page in get_character_pages().items():
        stats = get_char_stats()[char]
        adv_materials = get_char_advance_material()[char.id]
        affinity_levels = [l.stat_bonuses for l in get_affinity_levels()[char.rarity.value]]
        talent_levels = [t.stat_bonuses for t in get_talent_levels()[char]]
        t = char_stats_to_template(stats, adv_materials, affinity_levels, talent_levels)
        if char.name == 'Amber':
            print(t)


if __name__ == '__main__':
    main()