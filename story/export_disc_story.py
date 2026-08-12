from dataclasses import dataclass
from functools import cache

from pywikibot import Page
from wikitextparser import parse

from page_generators.discs import Disc, get_discs
from story.export_story import episode_to_messenger_template, with_tyrant_gender_selector
from story.parse_story import (
    load_story_config,
    normalize_story_id,
    parse_story_config,
    StoryEpisode,
)
from story.story_assets import export_story_assets
from utils.data_utils import autoload
from utils.wiki_utils import force_section_text, save_page, s


@dataclass
class DiscStoryEntry:
    disc_id: int
    page_title: str
    episode_id: str


@cache
def get_disc_story_entries() -> list[DiscStoryEntry]:
    entries: list[DiscStoryEntry] = []
    discs = get_discs()
    for disc_id, disc_ip in sorted(autoload("DiscIP").items()):
        story_id = disc_ip.get("AvgId")
        if not story_id:
            continue
        disc: Disc | None = discs.get(int(disc_id))
        if disc is None:
            print(f"WARNING: Disc story has no disc metadata for {disc_id}")
            continue
        if load_story_config(story_id) is None:
            print(f"WARNING: Disc story {story_id} has no Lua file")
            continue
        entries.append(
            DiscStoryEntry(
                disc_id=disc.id,
                page_title=disc.name,
                episode_id=normalize_story_id(story_id),
            )
        )
    return entries


@cache
def get_disc_story_episodes() -> dict[str, StoryEpisode]:
    episodes: dict[str, StoryEpisode] = {}
    for entry in get_disc_story_entries():
        if entry.episode_id in episodes:
            continue
        episode = parse_story_config(entry.episode_id)
        if episode is None:
            continue
        episodes[entry.episode_id] = episode
    return episodes


def save_disc_stories() -> None:
    episodes = get_disc_story_episodes()
    export_story_assets(episodes)
    for entry in get_disc_story_entries():
        episode = episodes.get(entry.episode_id)
        if episode is None:
            continue
        content = with_tyrant_gender_selector(episode_to_messenger_template(episode))
        page = Page(s, entry.page_title)
        parsed = parse(page.text)
        disc_story_next_section = "See also"
        if not force_section_text(
            parsed,
            "Memory Recollection",
            "{{MemoryRecollectionSection}}\n" + content,
            prepend=disc_story_next_section,
        ):
            print(f"WARNING: Could not find {disc_story_next_section} section on {entry.page_title}")
            continue
        save_page(page, str(parsed), "update disc story")


def main():
    save_disc_stories()


if __name__ == "__main__":
    main()
