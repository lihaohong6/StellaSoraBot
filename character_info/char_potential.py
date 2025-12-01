from dataclasses import dataclass
from functools import cache

from character_info.char_skills import parse_params, SkillParam
from character_info.characters import get_id_to_char
from utils.data_utils import autoload, data_to_dict
from utils.skill_utils import skill_escape


@dataclass
class CharPotential:
    id: int
    name: str
    brief: str
    desc: str
    rarity: int
    build: int
    branch_type: int
    max_level: int
    params: list[SkillParam]


@cache
def get_potentials() -> dict[str, list[CharPotential]]:
    items = autoload("Item")
    potentials_raw = autoload("Potential")
    result: dict[str, list[CharPotential]] = {}
    chars = get_id_to_char()
    for k, v in potentials_raw.items():
        char_id = v['CharId']
        if char_id not in chars:
            continue
        char = chars[char_id]
        char_name = char.name
        if char_name not in result:
            result[char_name] = []
        potential_id = v['Id']
        item = items[str(potential_id)]
        name = item['Title']
        rarity = item['Rarity']
        brief = skill_escape(v['BriefDesc'])
        attrs = data_to_dict(v, ["max_level", "branch_type", "build", "desc"])
        attrs['desc'] = skill_escape(attrs['desc'])
        params = parse_params(v, max_params=100)
        result[char_name].append(CharPotential(
            id=potential_id,
            name=name,
            rarity=rarity,
            brief=brief,
            params=params,
            **attrs)
        )
    return result

def main():
    for p in get_potentials()['Minova']:
        print(p)

if __name__ == '__main__':
    main()