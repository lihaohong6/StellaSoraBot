from dataclasses import dataclass
from functools import cache

from wikitextparser import parse

from character_info.characters import get_characters, id_to_char, Character, get_character_pages
from page_generators.items import make_item_pages, Item, get_all_items
from utils.data_utils import autoload
from utils.wiki_utils import find_template_by_name, save_page


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
            # Highest rarity gifts don't exist yet
            if item.rarity < 2:
                continue
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


def save_character_favourite_gifts():
    fav_gifts = get_character_favourite_gift_items()
    for char, page in get_character_pages().items():
        gifts = fav_gifts[char]
        parsed = parse(page.text)
        t = find_template_by_name(parsed, "TrekkerGifts")
        assert t is not None
        t.string = "{{TrekkerGifts|" + "|".join(g.title for g in gifts) + "}}"
        save_page(page, str(parsed))


def gifts_main():
    gifts = get_gifts()
    make_item_pages([g.id for g in gifts], content="is a [[gift]].\n==Trekkers==\n{{GiftTrekkers}}", overwrite=True, category="Gift")
    save_character_favourite_gifts()


def main():
    gifts_main()


if __name__ == '__main__':
    main()
