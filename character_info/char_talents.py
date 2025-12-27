from collections import defaultdict
from dataclasses import dataclass
from functools import cache

from utils.stat_utils import StatBonus
from character_info.characters import Character, id_to_char
from utils.data_utils import autoload
from utils.stat_utils import parse_effect, get_stat_bonus


@dataclass
class TalentLevel:
    stat_bonuses: StatBonus


@cache
def get_talent_levels() -> dict[Character, list[TalentLevel]]:
    result: dict[Character, list[TalentLevel]] = defaultdict(list)
    data = autoload("Talent")
    char_groups: dict[int, dict[int, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for _, v in data.items():
        group_id = v['GroupId']
        char_id = int(str(group_id)[:3])
        talent_level = int(str(group_id)[3:]) * 2 + (0 if v['Sort'] <= 5 else 1)
        char_groups[char_id][talent_level].append(v)
    for char_id, talent_groups in char_groups.items():
        char = id_to_char(char_id)
        if not char:
            continue
        current_bonus = StatBonus()
        result[char].append(TalentLevel(current_bonus))
        for level, talent_list in talent_groups.items():
            effect_ids = []
            for t in talent_list:
                effect_ids.extend(t.get('EffectId', []))
            # Talent tonuses are additive
            current_bonus = current_bonus + get_stat_bonus(effect_ids, strict=False)
            result[char].append(TalentLevel(current_bonus))
    return result


def main():
    get_talent_levels()


if __name__ == '__main__':
    main()
