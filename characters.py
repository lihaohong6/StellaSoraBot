from dataclasses import dataclass
from functools import cache

from pywikibot import Page
from pywikibot.pagegenerators import PreloadingGenerator

from data_utils import load_json
from wiki_utils import s


@dataclass
class Character:
    id: int
    name: str
    birthday: str = None


@cache
def get_characters() -> dict[str, Character]:
    data, i18n = load_json("Character")
    base_info, base_info_i18n = load_json("CharacterArchiveBaseInfo")
    result = {}
    for k, v in data.items():
        name = i18n[v["Name"]]
        c = Character(v["Id"], name)
        c.birthday = base_info_i18n.get(f"CharacterArchiveBaseInfo.{c.id}02.2", None)
        result[name] = c
    return result


def get_character_pages() -> dict[str, Page]:
    characters = get_characters()
    gen = PreloadingGenerator(Page(s, c.name) for c in characters.values())
    result: dict[str, Page] = {}
    for page in gen:
        if page.exists():
            result[page.title()] = page
    return result
