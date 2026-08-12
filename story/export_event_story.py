import json
import re
from dataclasses import dataclass
from functools import cache
from typing import Any

from pywikibot import Page
from wikitextparser import parse

from page_generators.events import get_all_events, get_event_pages
from story.export_story import (
    episode_to_messenger_template,
    major_choice_target_links,
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
from utils.data_utils import autoload
from utils.wiki_utils import force_section_text, save_page, s


@dataclass
class EventStoryEntry(StoryEntry):
    event_id: int
    event_name: str
    act_title: str


@cache
def _event_avg_activity_ids() -> dict[int, int]:
    result: dict[int, int] = {}
    group_data = autoload("ActivityGroup")
    for v in group_data.values():
        enter_text = v.get("Enter", "{}") or "{}"
        enter = json.loads(enter_text)
        if "AVG" in enter:
            result[v["Id"]] = enter["AVG"][0]
    return result


def _event_story_rows(avg_activity_id: int) -> list[dict[str, Any]]:
    story_chapters = autoload("ActivityStoryChapter")
    story_data = autoload("ActivityStory")

    for chapter in story_chapters.values():
        if chapter["Id"] != avg_activity_id:
            continue
        chapter_id = chapter["ChapterId"]
        rows = [v for v in story_data.values() if v.get("ChapterId") == chapter_id]
        return sorted(rows, key=lambda v: v["Id"])

    avg_data = autoload("ActivityAvgLevel")
    rows = [v for v in avg_data.values() if v.get("ActivityId") == avg_activity_id]
    return sorted(rows, key=lambda v: v["Id"])


def _episode_suffix(index: str, sequence: int) -> str:
    match = re.match(r"^\s*0*(\d+)([A-Za-z]*)\b", index)
    if match:
        return f"{int(match.group(1))}{match.group(2).upper()}"
    return str(sequence)


@cache
def get_event_story_entries() -> list[EventStoryEntry]:
    entries: list[EventStoryEntry] = []
    events = get_all_events()
    avg_activity_ids = _event_avg_activity_ids()
    seen_pages: set[str] = set()

    for event_id, avg_activity_id in sorted(avg_activity_ids.items()):
        event = events.get(event_id)
        if event is None:
            print(f"WARNING: Event story has no event metadata for {event_id}")
            continue
        rows = _event_story_rows(avg_activity_id)
        sequence = 0
        for row in rows:
            story_id = row.get("AvgLuaName") or row.get("StoryId")
            if not story_id:
                print(f"WARNING: Event story row {row['Id']} has no Lua story name")
                continue
            if load_story_config(story_id) is None:
                print(f"WARNING: Event story {story_id} has no Lua file")
                continue

            sequence += 1
            index = str(row.get("Index", ""))
            suffix = _episode_suffix(index, sequence)
            act_title = f"Act {suffix}"
            page_title = f"{event.name}/{act_title}"
            if page_title in seen_pages:
                continue
            seen_pages.add(page_title)
            entries.append(
                EventStoryEntry(
                    event_id=event_id,
                    event_name=event.name,
                    page_title=page_title,
                    act_title=act_title,
                    episode_id=normalize_story_id(story_id),
                    parent_episode_ids=tuple(
                        normalize_story_id(parent_id)
                        for parent_id in row.get("ParentStoryId", []) or []
                    ),
                )
            )

    return entries


@cache
def get_event_story_episodes() -> dict[str, StoryEpisode]:
    episodes: dict[str, StoryEpisode] = {}
    for entry in get_event_story_entries():
        if entry.episode_id in episodes:
            continue
        episode = parse_story_config(entry.episode_id)
        if episode is None:
            continue
        episodes[entry.episode_id] = episode
    return episodes


def build_event_story_pages() -> dict[str, str]:
    episodes = get_event_story_episodes()
    pages: dict[str, str] = {}
    event_entries: dict[str, list[EventStoryEntry]] = {}
    for entry in get_event_story_entries():
        if entry.episode_id in episodes:
            event_entries.setdefault(entry.event_name, []).append(entry)

    for entries in event_entries.values():
        choice_target_links = major_choice_target_links(entries, episodes)
        for i, entry in enumerate(entries):
            prev_page = entries[i - 1].page_title if i > 0 else None
            next_page = entries[i + 1].page_title if i < len(entries) - 1 else None
            top = story_nav_template("EventStoryTop", prev_page, next_page)
            bottom = story_nav_template("EventStoryBottom", prev_page, next_page)
            content = episode_to_messenger_template(
                episodes[entry.episode_id],
                choice_target_links.get(entry.episode_id),
            )
            pages[entry.page_title] = (
                f"{top}\n{with_tyrant_gender_selector(content)}\n{bottom}"
            )
    return pages


def build_event_story_section(
    entries: list[EventStoryEntry],
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


def build_event_story_sections() -> dict[str, str]:
    episodes = get_event_story_episodes()
    event_pages = get_event_pages()
    event_entries: dict[str, list[EventStoryEntry]] = {}
    for entry in get_event_story_entries():
        wiki_name = event_pages[entry.event_id].page_title if entry.event_id in event_pages else entry.event_name
        event_entries.setdefault(wiki_name, []).append(entry)
    return {
        event_name: build_event_story_section(entries, episodes)
        for event_name, entries in event_entries.items()
    }


def save_event_stories() -> None:
    save_story_pages(build_event_story_pages(), "update event story")


def save_event_story_sections() -> None:
    for event_name, section_text in build_event_story_sections().items():
        page = Page(s, event_name)
        parsed = parse(page.text)
        if not force_section_text(parsed, "Story", section_text, prepend="Period"):
            print(f"WARNING: Could not find Period section on {event_name}")
            continue
        save_page(page, str(parsed), "update event story links")


def main():
    event_episodes = get_event_story_episodes()
    export_story_assets(event_episodes)
    save_event_stories()
    save_event_story_sections()


if __name__ == "__main__":
    main()
