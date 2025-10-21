import re
from dataclasses import dataclass
from functools import cache

from wikitextparser import parse

from character_info.characters import get_characters, get_character_pages
from utils.data_utils import autoload
from utils.wiki_utils import force_section_text, save_page


@dataclass
class AffinityArchive:
    id: int
    title: str
    content: str


@cache
def get_affinity_archives() -> dict[str, list[AffinityArchive]]:
    chars = get_characters()
    result = {}
    data = autoload("CharacterArchiveContent")
    for name, char in chars.items():
        lst = []
        for i in range(3, 11):  # 14
            key = f"{char.id}{i:02}"
            if key not in data:
                break
            row = data[key]
            content = row['Content']
            content = content.replace("\n", "<br/>").replace("==PLAYER_NAME==", "<player name>")
            # FIXME: should be replaced with icons, but we don't know where they are for now
            content = re.sub("<sprite[^>]+>", "", content)
            lst.append(AffinityArchive(
                id=row['Id'],
                title=row['Title'],
                content=content
            ))
        else:
            result[name] = lst
    return result


def story_to_tabs(stories: list[AffinityArchive]):
    result = ["<tabber>"]
    for story in stories:
        result.append(f"|-|{story.title}=")
        result.append(story.content)
    result.append("</tabber>")
    return "\n".join(result)


def save_affinity_archives():
    affinity_archives = get_affinity_archives()
    for char_name, page in get_character_pages().items():
        parsed = parse(page.text)
        text = story_to_tabs(affinity_archives[char_name])
        force_section_text(parsed, "Story", text, "Gallery")
        save_page(page, str(parsed), "update character story in affinity archive")


def main():
    save_affinity_archives()


if __name__ == '__main__':
    main()
