from collections import defaultdict
from dataclasses import dataclass

from wikitextparser import Template

from character_info.char_advance import AdvanceMaterial, get_char_advance_material
from character_info.char_affinity import AffinityLevel, get_affinity_levels
from character_info.characters import Character, id_to_char, get_characters
from page_generators.items import make_item_template, get_all_items
from utils.data_utils import autoload
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


def char_stats_to_template(stats: list[LevelStats],
                           advancement_materials: list[AdvanceMaterial],
                           affinity_levels: list[AffinityLevel]) -> str:
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

    result.append("<hr/>")
    result.append('<div class="stat-data-container">')
    for attr, label, name in [
        ('attack', 'Attack', 'level'),
        ('hp', 'HP', 'level'),
        ('defense', 'Defense', 'level'),
    ]:
        t = Template("{{StatDisplay/value\n}}")
        set_arg(t, "label", label)
        set_arg(t, "name1", name)
        set_arg(t, "values1", ",".join(str(getattr(stat, attr)) for stat in stats))
        if attr == 'attack':
            set_arg(t, "name2", 'affinity1')
            set_arg(t, 'values2', ','.join(str(level.stat_bonuses.attack) for level in affinity_levels))
            set_arg(t, "name3", 'affinity2')
            set_arg(t, 'values3', ','.join(str(level.stat_bonuses.attack_pct) for level in affinity_levels))
            # Round down
            set_arg(t, 'formula', '(level + affinity1) * (1 + affinity2) - 0.5')
        if attr == 'hp':
            set_arg(t, "name2", 'affinity')
            set_arg(t, 'values2', ','.join(str(level.stat_bonuses.hp) for level in affinity_levels))
            set_arg(t, "formula", 'level + affinity')
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
    char = get_characters()['Chitose']
    print(char_stats_to_template(get_char_stats()[char], get_char_advance_material()[char.id], get_affinity_levels()[2]))


if __name__ == '__main__':
    main()