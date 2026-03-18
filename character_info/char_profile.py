from functools import cache

from wikitextparser import parse

from character_info.characters import Character, id_to_char, get_character_pages
from utils.data_utils import autoload
from utils.wiki_utils import find_section, save_page


@cache
def get_character_profile() -> dict[Character, str]:
    data = autoload("CharacterDes")
    result: dict[Character, str] = {}
    for char_id, v in data.items():
        char = id_to_char(char_id)
        if not char:
            continue
        result[char] = v['CharDes']
    return result


def update_character_profile():
    profiles = get_character_profile()
    for char, page in get_character_pages().items():
        parsed = parse(page.text)
        profile_section = find_section(parsed, "Profile")
        assert profile_section is not None
        if len(profile_section.contents.strip()) <= 20:
            profile_section.contents = f"''\"{profiles[char]}\"''\n\n"
            save_page(page, str(parsed), summary="Add in-game profile")


def main():
    update_character_profile()


if __name__ == "__main__":
    main()