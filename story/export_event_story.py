import json
import re
from functools import cache
from typing import Any

from page_generators.events import get_all_events
from story.export_story import (
    build_story_pages,
    export_bgm_files,
    export_sound_effects,
    save_story_pages,
    StoryPageExport,
)
from story.parse_story import (
    load_story_config,
    normalize_story_id,
    parse_story_config,
    StoryEpisode,
)
from utils.data_utils import autoload


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


def _event_story_rows(avg_activity_id: int) -> tuple[str, list[dict[str, Any]]]:
    story_chapters = autoload("ActivityStoryChapter")
    story_data = autoload("ActivityStory")

    for chapter in story_chapters.values():
        if chapter["Id"] != avg_activity_id:
            continue
        chapter_id = chapter["ChapterId"]
        rows = [v for v in story_data.values() if v.get("ChapterId") == chapter_id]
        return "ActivityStory", sorted(rows, key=lambda v: v["Id"])

    avg_data = autoload("ActivityAvgLevel")
    rows = [v for v in avg_data.values() if v.get("ActivityId") == avg_activity_id]
    return "ActivityAvgLevel", sorted(rows, key=lambda v: v["Id"])


def _episode_suffix(index: str, sequence: int) -> str:
    match = re.match(r"^\s*0*(\d+)([A-Za-z]*)\b", index)
    if match:
        return f"{int(match.group(1))}{match.group(2).upper()}"
    return str(sequence)


@cache
def get_event_story_entries() -> list[StoryPageExport]:
    entries: list[StoryPageExport] = []
    events = get_all_events()
    avg_activity_ids = _event_avg_activity_ids()
    seen_pages: set[str] = set()

    for event_id, avg_activity_id in sorted(avg_activity_ids.items()):
        event = events.get(event_id)
        if event is None:
            print(f"WARNING: Event story has no event metadata for {event_id}")
            continue
        _, rows = _event_story_rows(avg_activity_id)
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
            page_title = f"{event.name}/Episode {suffix}"
            if page_title in seen_pages:
                continue
            seen_pages.add(page_title)
            entries.append(StoryPageExport(page_title, normalize_story_id(story_id)))

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
    return build_story_pages(get_event_story_entries(), get_event_story_episodes())


def save_event_stories() -> None:
    save_story_pages(build_event_story_pages(), "update event story")


def main():
    event_episodes = get_event_story_episodes()
    export_bgm_files(event_episodes)
    export_sound_effects(event_episodes)
    save_event_stories()


if __name__ == "__main__":
    main()
