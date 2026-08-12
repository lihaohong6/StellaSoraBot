from dataclasses import dataclass
from functools import cache

from wikitextparser import parse

from character_info.characters import get_character_pages, get_characters
from story.export_story import (
    episode_to_messenger_template,
    save_story_pages,
    StoryEntry,
    story_nav_template,
    with_tyrant_gender_selector,
)
from story.parse_story import (
    load_story_config,
    normalize_story_id,
    parse_story_config,
    StoryEpisode,
)
from story.story_assets import export_story_assets
from utils.wiki_utils import force_section_text, save_page

CHARACTER_STORY_SECTION = "Character stories"


@dataclass
class CharacterStoryEntry(StoryEntry):
    char_name: str
    act_title: str


@cache
def get_char_story_entries() -> list[CharacterStoryEntry]:
    entries: list[CharacterStoryEntry] = []
    for char in get_characters().values():
        act = 0
        while True:
            act += 1
            story_id = f"cg_{char.id}_{act:02d}"
            if load_story_config(story_id) is None:
                break
            act_title = f"Act {act}"
            entries.append(
                CharacterStoryEntry(
                    page_title=f"{char.name}/story/{act_title}",
                    episode_id=normalize_story_id(story_id),
                    parent_episode_ids=(),
                    char_name=char.name,
                    act_title=act_title,
                )
            )
    return entries


@cache
def get_char_story_episodes() -> dict[str, StoryEpisode]:
    episodes: dict[str, StoryEpisode] = {}
    for entry in get_char_story_entries():
        if entry.episode_id in episodes:
            continue
        episode = parse_story_config(entry.episode_id)
        if episode is None:
            continue
        episodes[entry.episode_id] = episode
    return episodes


def _entries_by_character() -> dict[str, list[CharacterStoryEntry]]:
    episodes = get_char_story_episodes()
    result: dict[str, list[CharacterStoryEntry]] = {}
    for entry in get_char_story_entries():
        if entry.episode_id in episodes:
            result.setdefault(entry.char_name, []).append(entry)
    return result


def build_char_story_pages() -> dict[str, str]:
    episodes = get_char_story_episodes()
    pages: dict[str, str] = {}
    for entries in _entries_by_character().values():
        for i, entry in enumerate(entries):
            prev_page = entries[i - 1].page_title if i > 0 else None
            next_page = entries[i + 1].page_title if i < len(entries) - 1 else None
            top = story_nav_template("CharacterStoryTop", prev_page, next_page)
            bottom = story_nav_template("CharacterStoryBottom", prev_page, next_page)
            content = episode_to_messenger_template(episodes[entry.episode_id])
            pages[entry.page_title] = (
                f"{top}\n{with_tyrant_gender_selector(content)}\n{bottom}"
            )
    return pages


def build_char_story_section(
    entries: list[CharacterStoryEntry],
    episodes: dict[str, StoryEpisode],
) -> str:
    lines = []
    for entry in entries:
        episode = episodes.get(entry.episode_id)
        if episode is None:
            continue
        summary = episode.description.strip()
        line = f"* [[{entry.page_title}|{entry.act_title}]]"
        if summary:
            line += f": {summary}"
        lines.append(line)
    return "\n".join(lines)


def build_char_story_sections() -> dict[str, str]:
    episodes = get_char_story_episodes()
    return {
        char_name: build_char_story_section(entries, episodes)
        for char_name, entries in _entries_by_character().items()
    }


def save_char_stories() -> None:
    save_story_pages(build_char_story_pages(), "update character story")


def save_char_story_sections() -> None:
    sections = build_char_story_sections()
    for char, page in get_character_pages("/story").items():
        section_text = sections.get(char.name)
        if section_text is None:
            continue
        parsed = parse(page.text)
        if not force_section_text(
            parsed,
            CHARACTER_STORY_SECTION,
            section_text,
            prepend="Invitation stories",
        ):
            print(f"WARNING: Could not find Invitation stories section on {page.title()}")
            continue
        save_page(page, str(parsed), "update character story links")


def main():
    export_story_assets(get_char_story_episodes())
    save_char_stories()
    save_char_story_sections()


if __name__ == "__main__":
    main()
