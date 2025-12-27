from collections import defaultdict
from dataclasses import dataclass
from functools import cache

from wikitextparser import parse, Template

from character_info.characters import id_to_char, Character, get_character_pages
from page_generators.items import make_item_pages, Item, get_all_items
from utils.stat_utils import StatBonus, get_stat_bonus
from utils.data_utils import autoload
from utils.wiki_utils import save_page, find_section, set_arg


@cache
def get_character_favourite_gifts() -> dict[Character, list[int]]:
    data = autoload("CharacterDes")
    result: dict[Character, list[int]] = {}
    for char_id, v in data.items():
        char = id_to_char(char_id)
        if not char:
            continue
        result[char] = v['PreferTags']
    return result

@cache
def get_character_favourite_gift_items() -> dict[Character, list[Item]]:
    favourite_gifts = get_character_favourite_gifts()
    gifts = get_gifts()
    result: dict[Character, list[Item]] = {}
    for char, tags in favourite_gifts.items():
        result[char] = []
        for gift in gifts:
            if gift.tags[0] not in tags:
                continue
            item = get_all_items()[gift.id]
            result[char].append(item)
    return result


@dataclass
class Gift:
    id: int
    affinity: int
    tags: list[int]


@cache
def get_gifts() -> list[Gift]:
    data = autoload("AffinityGift")
    result = []
    for _, v in data.items():
        result.append(Gift(v['Id'], v['BaseAffinity'], v['Tags']))
    result.sort(key=lambda g: (g.tags[0], g.id))
    return result


def save_character_favourite_gifts(t: Template, char: Character) -> None:
    fav_gifts = get_character_favourite_gift_items()
    gifts = fav_gifts[char]
    t.string = "{{TrekkerGifts|" + "|".join(g.title for g in gifts) + "}}"


def gifts_main():
    gifts = get_gifts()
    make_item_pages([g.id for g in gifts], content="is a [[gift]].\n==Trekkers==\n{{GiftTrekkers}}", overwrite=True, category="Gift")


@dataclass
class AffinityQuest:
    desc: str
    exp: int


@cache
def get_affinity_quests():
    result: dict[Character, list[AffinityQuest]] = defaultdict(list)
    for k, v in autoload("AffinityQuest").items():
        char = id_to_char(v['CharId'])
        if char is None:
            continue
        desc = v['Desc']
        for i in range(1, 10):
            if f"{{{i}}}" in desc:
                desc = desc.replace(f"{{{i}}}", v[f'Param{i}'])
        result[char].append(AffinityQuest(desc, v['AffinityExp']))
    return result


def save_affinity_quests(t: Template, char: Character) -> None:
    quests = get_affinity_quests()[char]
    for i, q in enumerate(quests, 1):
        set_arg(t, f"text{i}", q.desc)
        set_arg(t, f"exp{i}", q.exp)


@dataclass
class AffinityLevel:
    level: int
    exp: int
    name: str
    stat_bonuses: StatBonus


def get_affinity_levels() -> dict[int, list[AffinityLevel]]:
    data = autoload("AffinityLevel")
    result: dict[int, list[AffinityLevel]] = defaultdict(list)
    for _, v in data.items():
        rarity = v['TemplateId']
        stat_bonus = get_stat_bonus(v.get('Effect', []))
        result[rarity].append(AffinityLevel(v.get('AffinityLevel', 1), v.get('NeedExp', 0), v['AffinityLevelName'], stat_bonus))
    return result


def affinity_main():
    gifts_main()
    for char, page in get_character_pages().items():
        parsed = parse(page.text)
        section = find_section(parsed, "Affinity")
        gifts = Template("{{TrekkerGifts}}")
        save_character_favourite_gifts(gifts, char)
        affinity = Template("{{TrekkerAffinityTasks}}")
        save_affinity_quests(affinity, char)
        section.contents = "\n".join([str(gifts), str(affinity)]) + "\n"
        save_page(page, str(parsed), "update affinity section")


if __name__ == '__main__':
    affinity_main()
