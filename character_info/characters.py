from dataclasses import dataclass
from functools import cache

from pywikibot import Page
from pywikibot.pagegenerators import PreloadingGenerator

from utils.data_utils import load_json_pair, autoload
from utils.wiki_utils import s


@dataclass
class Character:
    id: int
    name: str
    birthday: str = None
    experience: str = None
    rate: str = None
    skills: str = None
    weapon: str = None
    address: str = None
    affiliation: str = None


@cache
def get_characters() -> dict[str, Character]:
    data = autoload("Character")
    base_info = autoload("CharacterArchiveBaseInfo")
    result = {}
    for k, v in data.items():
        name = v["Name"]
        c = Character(v["Id"], name)
        pairs = [
            ("birthday", "02"),
            ("affiliation", "03"),
            ("skills", "04"),
            ("address", "05"),
            ("experience", "06"),
            ("weapon", "07"),
            ("rate", "08")
        ]
        for attr, num in pairs:
            value = base_info.get(f"{c.id}{num}", {}).get('Content', None)
            if value:
               setattr(c, attr, value)
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


def get_id_to_char() -> dict[int, Character]:
    chars = get_characters()
    return dict((c.id, c) for c in chars.values())
