from dataclasses import dataclass
from functools import cache

from pywikibot import Page
from wikitextparser import parse

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
from utils.data_utils import autoload
from utils.wiki_utils import (
    find_template_by_name,
    force_section_text,
    s,
    save_page,
    set_arg,
)

NOVA_TIMES_PAGE = "The Nova Times"


@dataclass
class NovaTimesAct(StoryEntry):
    act_title: str


@dataclass
class NovaTimesStory:
    chapter_id: int
    number: str
    name: str
    page_title: str
    acts: list[NovaTimesAct]


@cache
def get_nova_times_stories() -> list[NovaTimesStory]:
    sections = autoload("StorySetSection")
    stories: list[NovaTimesStory] = []
    for chapter in sorted(autoload("StorySetChapter").values(), key=lambda v: v["Id"]):
        if not chapter.get("IsShow"):
            continue
        page_title = f"{NOVA_TIMES_PAGE}/{chapter['Name']}"
        rows = sorted(
            (v for v in sections.values() if v["ChapterId"] == chapter["Id"]),
            key=lambda v: v["Id"],
        )
        acts: list[NovaTimesAct] = []
        for row in rows:
            story_id = row["AVGId"]
            if load_story_config(story_id) is None:
                print(f"WARNING: Nova Times story {story_id} has no Lua file")
                continue
            act_title = row["Title"]
            acts.append(
                NovaTimesAct(
                    page_title=f"{page_title}/{act_title}",
                    episode_id=normalize_story_id(story_id),
                    parent_episode_ids=(),
                    act_title=act_title,
                )
            )
        stories.append(
            NovaTimesStory(
                chapter_id=chapter["Id"],
                number=chapter["Title"],
                name=chapter["Name"],
                page_title=page_title,
                acts=acts,
            )
        )
    return stories


@cache
def get_nova_times_episodes() -> dict[str, StoryEpisode]:
    episodes: dict[str, StoryEpisode] = {}
    for story in get_nova_times_stories():
        for act in story.acts:
            episode = parse_story_config(act.episode_id)
            if episode is not None:
                episodes[act.episode_id] = episode
    return episodes


def _story_link(story: NovaTimesStory) -> str:
    return f"[[{story.page_title}|{story.name}]]"


def build_nova_times_transcript_pages() -> dict[str, str]:
    episodes = get_nova_times_episodes()
    pages: dict[str, str] = {}
    for story in get_nova_times_stories():
        acts = [a for a in story.acts if a.episode_id in episodes]
        for i, act in enumerate(acts):
            prev_page = acts[i - 1].page_title if i > 0 else None
            next_page = acts[i + 1].page_title if i < len(acts) - 1 else None
            nav = story_nav_template("StoryNav", prev_page, next_page)
            content = episode_to_messenger_template(episodes[act.episode_id])
            pages[act.page_title] = (
                f"{nav}\n{with_tyrant_gender_selector(content)}\n{nav}"
            )
    return pages


def build_story_section(story: NovaTimesStory, episodes: dict[str, StoryEpisode]) -> str:
    blocks = []
    for act in story.acts:
        episode = episodes.get(act.episode_id)
        if episode is None:
            continue
        lines = [
            f"=== {act.act_title} ===",
            f": [[{act.page_title}|Read the story]]"
        ]
        summary = episode.description.strip()
        if summary:
            lines.append(summary)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def build_story_page(
    story: NovaTimesStory,
    prev_story: NovaTimesStory | None,
    next_story: NovaTimesStory | None,
    existing_text: str,
) -> str:
    text = existing_text.strip() or (
        "{{NovaTimesData\n}}\n\n"
        f"'''{story.name}''' is a Nova Times story.\n\n"
        "== Story ==\n"
    )
    parsed = parse(text)
    chapter_data = find_template_by_name(parsed, "NovaTimesData")
    assert chapter_data is not None, story.page_title
    set_arg(chapter_data, "name", story.name)
    if not chapter_data.has_arg("image"):
        set_arg(chapter_data, "image", f"Story tales {story.chapter_id % 1000:02d} 001.png")
    set_arg(chapter_data, "number", f"Nova Times {story.number}")
    for arg_name, other in (("prev", prev_story), ("next", next_story)):
        if other is not None:
            set_arg(chapter_data, arg_name, _story_link(other))
        elif chapter_data.has_arg(arg_name):
            chapter_data.del_arg(arg_name)

    section_text = build_story_section(story, get_nova_times_episodes())
    if not force_section_text(parsed, " Story ", section_text):
        print(f"WARNING: Could not find Story section on {story.page_title}")
    return str(parsed)


def build_nova_times_stories_section() -> str:
    return "\n".join(
        f"* {story.number}: {_story_link(story)}" for story in get_nova_times_stories()
    )


def save_nova_times_transcripts() -> None:
    save_story_pages(build_nova_times_transcript_pages(), "update Nova Times story")


def save_nova_times_story_pages() -> None:
    stories = get_nova_times_stories()
    for i, story in enumerate(stories):
        page = Page(s, story.page_title)
        text = build_story_page(
            story,
            stories[i - 1] if i > 0 else None,
            stories[i + 1] if i < len(stories) - 1 else None,
            page.text if page.exists() else "",
        )
        save_page(page, text, "update Nova Times story page")


def save_nova_times_index() -> None:
    page = Page(s, NOVA_TIMES_PAGE)
    parsed = parse(page.text)
    if not force_section_text(
        parsed,
        "Stories",
        build_nova_times_stories_section(),
        prepend="Other languages",
    ):
        print(f"WARNING: Could not find Other languages section on {NOVA_TIMES_PAGE}")
        return
    save_page(page, str(parsed), "update Nova Times story links")


def main():
    # export_story_assets(get_nova_times_episodes())
    save_nova_times_transcripts()
    save_nova_times_story_pages()
    save_nova_times_index()


if __name__ == "__main__":
    main()
