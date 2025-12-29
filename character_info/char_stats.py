from collections import defaultdict
from dataclasses import dataclass

from wikitextparser import Template, parse

from character_info.char_advance import AdvanceMaterial, get_char_advance_material, upgrade_material_to_string
from character_info.char_affinity import get_affinity_levels
from character_info.char_talents import get_talent_levels
from character_info.characters import Character, id_to_char, get_character_pages, CharacterRarity
from utils.data_utils import autoload
from utils.stat_utils import StatBonus
from utils.wiki_utils import set_arg, force_section_text, save_page


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
    for index, material in enumerate(advancement_materials, 1):
        upgrade_items = upgrade_material_to_string(material)
        if upgrade_items == "":
            text = "<div></div>"
        else:
            text = f"<div>Breakthrough material at level {index * 10}: {upgrade_items}</div>"
        set_arg(t, str(index), text)
    result.append(str(t))

    t = Template("{{StatDisplay\n}}")
    t.set_arg("1", "\n".join(result))
    return str(t)


def update_character_stats():
    for char, page in get_character_pages().items():
        stats = get_char_stats()[char]
        adv_materials = get_char_advance_material()[char.id]
        # This doesn't change depending on char rarity but is the same for everyone
        affinity_levels = [l.stat_bonuses for l in get_affinity_levels()[CharacterRarity.NORMAL.value]]
        talent_levels = [t.stat_bonuses for t in get_talent_levels()[char]]
        t = char_stats_to_template(stats, adv_materials, affinity_levels, talent_levels)
        parsed = parse(page.text)
        force_section_text(parsed, "Stats", t, prepend="Skills")
        save_page(page, str(parsed), summary="update stats section")


if __name__ == '__main__':
    update_character_stats()