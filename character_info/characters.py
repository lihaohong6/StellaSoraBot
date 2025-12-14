from dataclasses import dataclass
from enum import Enum
from functools import cache

from pywikibot import Page
from pywikibot.pagegenerators import PreloadingGenerator

from utils.data_utils import autoload, load_json
from utils.wiki_utils import s


class ElementType(Enum):
    aqua = 1
    ignis = 2
    terra = 3
    ventus = 4
    lux = 5
    umbra = 6
    neutral = 7


def common_name_to_element_type(name: str) -> ElementType:
    return {
        "fire": ElementType.ignis,
        "wind": ElementType.ventus,
        "light": ElementType.lux,
        "earth": ElementType.terra,
        "dark": ElementType.umbra,
        "water": ElementType.aqua,
    }[name]


@cache
def get_char_element_type(char_id: int) -> ElementType:
    data = load_json("HitDamage")
    element_type: list[int] = []
    for k, v in data.items():
        if k.startswith(str(char_id)):
            if "ElementType" in v:
                element_type.append(v['ElementType'])
    if len(element_type) == 0:
        return None
    # assert all(t == element_type[0] for t in element_type)
    return ElementType(element_type[0])


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
    element: ElementType = None

    def __hash__(self) -> int:
        return hash(self.id)


@cache
def get_characters() -> dict[str, Character]:
    data = autoload("Character")
    base_info = autoload("CharacterArchiveBaseInfo")
    result = {}
    for k, v in data.items():
        name = v["Name"]
        if name == "???":
            continue
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
            key = f"{c.id}{num}"
            value = base_info.get(key, {}).get('Content', None)
            if not value:
                continue
            update_content = base_info[key]["UpdateContent1"]
            if key not in update_content:
                value = f"Original: {value}\nUpdated: {update_content}"
            setattr(c, attr, value)
        c.element = ElementType(v['EET'])
        if c.affiliation == "???":
            continue
        result[name] = c
    return result


def get_character_pages(suffix: str = "", must_exist: bool = True) -> dict[Character, Page]:
    characters = get_characters()
    gen = PreloadingGenerator(Page(s, c.name + suffix) for c in characters.values())
    result: dict[Character, Page] = {}
    for page in gen:
        if page.exists() or not must_exist:
            char_name = page.title().split("/")[0]
            result[characters[char_name]] = page
    return result


@cache
def get_id_to_char() -> dict[int, Character]:
    chars = get_characters()
    return dict((c.id, c) for c in chars.values())


def id_to_char(char_id: int | str) -> Character | None:
    char_id = int(char_id)
    return get_id_to_char().get(char_id, None)


def main():
    for k, v in get_characters().items():
        print(v)


if __name__ == "__main__":
    main()
