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
        for i in range(3, 14):
            key = f"{char.id}{i:02}"
            if key not in data:
                break
            row = data[key]
            content = row['Content']
            content = content.replace("\n", "<br/>").replace("==PLAYER_NAME==", "<player name>")
            filename = ""
            if "acrchives_certified" in content:
                filename = "certified"
            if "acrchives_falsified" in content:
                filename = "falsified"
            if filename != "":
                repl = f"[[File:Archive {filename}.png|30px|link=]]"
                content = re.sub("<sprite[^>]+>", repl, content)
            lst.append(AffinityArchive(
                id=row['Id'],
                title=row['Title'],
                content=content
            ))
        else:
            result[name] = lst
    return result


def affinity_archive_sections(stories: list[AffinityArchive]) -> str:
    result = []
    for story in stories:
        result.append(f"==={story.title}===")
        result.append(story.content)
    return "\n".join(result)


def save_affinity_archives():
    affinity_archives = get_affinity_archives()
    for char_name, page in get_story_pages().items():
        parsed = parse(page.text)
        text = affinity_archive_sections(affinity_archives[char_name])
        force_section_text(parsed, "Affinity archives", text)
        save_page(page, str(parsed), "update character story in affinity archive")


def get_story_pages():
    return get_character_pages(suffix="/story", must_exist=False)


def create_story_pages():
    for char_name, page in get_story_pages().items():
        if not page.exists():
            page.text = """{{StoryTop}}
==Affinity archives==
==Invitation stories==
"""
            page.save("batch create story pages")


def main():
    create_story_pages()
    save_affinity_archives()


if __name__ == '__main__':
    main()
