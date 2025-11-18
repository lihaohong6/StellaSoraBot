from dataclasses import dataclass
from functools import cache

from wikitextparser import parse

from character_info.characters import get_characters, get_character_pages
from utils.data_utils import autoload
from utils.wiki_utils import find_template_by_name, save_page, set_arg


@dataclass
class CharacterTag:
    id: int
    name: str
    type: int


@cache
def get_character_tag_dict() -> dict[int, CharacterTag]:
    data = autoload("CharacterTag")
    result: dict[int, CharacterTag] = dict()
    for k, v in data.items():
        result[int(k)] = CharacterTag(v['Id'], v['Title'], v['TagType'])
    return result


def get_character_tags(char_id: int) -> list[CharacterTag]:
    data = autoload("CharacterDes")
    tag_dict = get_character_tag_dict()
    return [tag_dict[tag_id]
            for tag_id in data[str(char_id)]['Tag']]


def update_infobox():
    auto_link = ["Lucky Oasis"]
    chars = get_characters()
    pages = get_character_pages()
    for char_name, page in pages.items():
        char = chars[char_name]
        parsed = parse(page.text)
        target = find_template_by_name(parsed, "TrekkerData")
        if not target:
            continue
        pairs = [
            ("birthday", char.birthday),
            ("affiliation", char.affiliation),
            ("skills", char.skills),
            ("address", char.address),
            ("experience", char.experience),
            ("weapon", char.weapon),
            ("rate", char.rate),
            ("element", char.element.name.capitalize()),
        ]
        for arg, value in pairs:
            for link in auto_link:
                value = value.replace(link, f"[[{link}]]")
            set_arg(target, arg, value)
        tags = get_character_tags(char.id)
        set_arg(target, "role", tags[0].name)
        set_arg(target, "style", tags[1].name)
        set_arg(target, "faction", tags[2].name)
        save_page(page, str(parsed), "update infobox")


def main():
    update_infobox()


if __name__ == "__main__":
    main()
