import re
from collections import Counter
from dataclasses import dataclass
from functools import cache
from typing import Any

from pywikibot import Page
from wikitextparser import parse

from story.export_story import (
    episode_to_messenger_template,
    major_choice_target_links,
    StoryEntry,
    story_nav_template,
    with_tyrant_gender_selector,
)
from story.parse_story import (
    load_story_config,
    normalize_story_id,
    parse_story_config,
    process_text,
    StoryEpisode,
)
from story.story_assets import export_story_assets
from utils.data_utils import autoload
from utils.wiki_utils import (
    find_section,
    find_template_by_name,
    force_section_text,
    s,
    save_page,
    set_arg,
)

MAIN_STORY_PAGE = "Main Story"
NUMBERED_LABELS = ("Interlude", "Reminiscence", "The End")


@dataclass
class MainStoryStage(StoryEntry):
    story_id: int
    key: str
    label: str
    title: str
    description: str
    is_battle: bool
    requirements: tuple[str, ...]

    @property
    def is_end(self) -> bool:
        return self.label.startswith("The End")


@dataclass
class MainStoryChapter:
    chapter_id: int
    number: str | None
    name: str
    image: str
    page_title: str
    stages: list[MainStoryStage]


def _base_label(index: str) -> str:
    for base in NUMBERED_LABELS:
        if index.startswith(base):
            return base
    return index


def _stage_labels(rows: list[dict[str, Any]]) -> dict[int, str]:
    counts = Counter(_base_label(row["Index"].strip()) for row in rows if not row.get("IsBattle"))
    seen: Counter[str] = Counter()
    labels: dict[int, str] = {}
    for row in rows:
        index = row["Index"].strip()
        if row.get("IsBattle"):
            labels[row["Id"]] = f"Battle {int(index.removeprefix('BT'))}"
            continue
        base = _base_label(index)
        if base in NUMBERED_LABELS:
            seen[base] += 1
            labels[row["Id"]] = f"{base} {seen[base]}" if counts[base] > 1 else base
            continue
        match = re.fullmatch(r"0*(\d+)([A-Z]?)", index)
        labels[row["Id"]] = f"{int(match.group(1))}{match.group(2)}" if match else index
    return labels


@cache
def _story_requirements() -> dict[str, tuple[str, ...]]:
    return {
        condition["ConditionId"]: tuple(
            normalize_story_id(story_id)
            for name, story_ids in condition.items()
            if name.startswith("StoryId_")
            for story_id in story_ids
        )
        for condition in autoload("StoryCondition").values()
    }


@cache
def _story_evidence() -> dict[str, tuple[str, ...]]:
    return {
        condition["ConditionId"]: tuple(condition.get("EvIds_a", ()))
        for condition in autoload("StoryCondition").values()
    }


def _battle_lua_name(row: dict[str, Any]) -> str:
    chapter, suffix = row["StoryId"].removeprefix("BAm").split("_", 1)
    return f"bbm{chapter}_{suffix if suffix.startswith('BT') else row['Index']}".lower()


def _chapter_stages(chapter_id: int, page_title: str) -> list[MainStoryStage]:
    rows = sorted(
        (v for v in autoload("Story").values() if v["Chapter"] == chapter_id),
        key=lambda v: v["Id"],
    )
    labels = _stage_labels(rows)
    battle_ids = {normalize_story_id(row["StoryId"]) for row in rows if row.get("IsBattle")}

    dropped: set[str] = set()
    for row in rows:
        if not row.get("IsBattle") and load_story_config(row["StoryId"]) is None:
            print(f"WARNING: Main story {row['StoryId']} has no Lua file")
            dropped.add(normalize_story_id(row["StoryId"]))

    stages: list[MainStoryStage] = []
    seen_labels: set[str] = set()
    for row in rows:
        key = normalize_story_id(row["StoryId"])
        is_battle = bool(row.get("IsBattle"))
        requirements = _story_requirements().get(row.get("ConditionId"), ())
        if key in dropped or is_battle and any(r in dropped for r in requirements):
            continue
        label = labels[row["Id"]]
        if label in seen_labels:
            print(f"WARNING: Duplicate main story label {label} in {page_title}")
            continue
        seen_labels.add(label)
        parents = () if is_battle else row.get("ParentStoryId") or ()
        stages.append(
            MainStoryStage(
                page_title=f"{page_title}/{label}",
                episode_id=_battle_lua_name(row) if is_battle else key,
                parent_episode_ids=tuple(
                    normalize_story_id(p) for p in parents if normalize_story_id(p) not in battle_ids
                ),
                story_id=row["Id"],
                key=key,
                label=label,
                title=row["Title"].strip(),
                description=process_text(row["Desc"]),
                is_battle=is_battle,
                requirements=requirements,
                evidence_ids=_story_evidence().get(row.get("ConditionId"), ()),
            )
        )
    return _order_stages(stages)


def _branch_position(stage: MainStoryStage, positions: dict[str, int]) -> int:
    if stage.label.isdigit():
        return -1
    return max((positions[r] for r in stage.requirements if r in positions), default=-1)


def _dead_end_keys(stages: list[MainStoryStage]) -> set[str]:
    children: dict[str, list[MainStoryStage]] = {}
    for stage in stages:
        for r in stage.requirements:
            children.setdefault(r, []).append(stage)
    dead_ends: set[str] = set()
    changed = True
    while changed:
        changed = False
        for stage in stages:
            kids = children.get(stage.key, [])
            if stage.key not in dead_ends and (
                stage.is_end
                or kids
                and all(kid.key in dead_ends for kid in kids)
                and sum(not kid.is_end for kid in kids) < 2
            ):
                dead_ends.add(stage.key)
                changed = True
    return dead_ends


def _order_stages(stages: list[MainStoryStage]) -> list[MainStoryStage]:
    main = [stage for stage in stages if not stage.is_end]
    keys = {stage.key for stage in main}
    dead_ends = _dead_end_keys(stages)
    bad_end_forks = {
        r
        for stage in main
        if stage.key in dead_ends
        for r in stage.requirements
        if r not in dead_ends
    }

    def priority(stage: MainStoryStage) -> tuple[int, int, bool, int]:
        if any(r in dead_ends for r in stage.requirements):
            group = 0
        elif any(r in bad_end_forks for r in stage.requirements):
            group = 1
        else:
            group = 2
        return group, -_branch_position(stage, positions), not stage.is_battle, stage.story_id

    order: list[MainStoryStage] = []
    positions: dict[str, int] = {}
    while len(order) < len(main):
        ready = [
            stage
            for stage in main
            if stage.key not in positions
            and all(r in positions or r not in keys for r in stage.requirements)
        ]
        if not ready:
            print("WARNING: Cycle in main story stage requirements")
            break
        stage = min(ready, key=priority)
        positions[stage.key] = len(order)
        order.append(stage)

    ends = [stage for stage in stages if stage.is_end]
    result: list[MainStoryStage] = []
    for stage in order:
        result.append(stage)
        result.extend(end for end in ends if stage.key in end.requirements)
    result.extend(end for end in ends if end not in result)
    return result


@cache
def get_main_story_chapters() -> list[MainStoryChapter]:
    chapters: list[MainStoryChapter] = []
    for chapter in sorted(autoload("StoryChapter").values(), key=lambda v: v["Id"]):
        if chapter["Type"] == 1:
            number = str(int(chapter["Index"]))
            page_title = f"{MAIN_STORY_PAGE}/Chapter {number}"
        else:
            number = None
            page_title = f"{MAIN_STORY_PAGE}/{chapter['Name']}"
        icon = chapter["ChapterIcon"].rsplit("/", 1)[-1].replace("_", " ")
        chapters.append(
            MainStoryChapter(
                chapter_id=chapter["Id"],
                number=number,
                name=chapter["Desc"].strip(),
                image=f"{icon[0].upper()}{icon[1:]}.png",
                page_title=page_title,
                stages=_chapter_stages(chapter["Id"], page_title),
            )
        )
    return chapters


@cache
def get_main_story_episodes() -> dict[str, StoryEpisode]:
    episodes = {
        stage.episode_id: parse_story_config(stage.episode_id)
        for chapter in get_main_story_chapters()
        for stage in chapter.stages
    }
    return {episode_id: episode for episode_id, episode in episodes.items() if episode is not None}


def _story_stages(chapter: MainStoryChapter) -> list[MainStoryStage]:
    episodes = get_main_story_episodes()
    return [stage for stage in chapter.stages if stage.episode_id in episodes]


def _chapter_link(chapter: MainStoryChapter) -> str:
    return f"[[{chapter.page_title}|{chapter.name}]]"


def _chapter_phrase(chapter: MainStoryChapter) -> str:
    return f"Chapter {chapter.number}" if chapter.number else f"the {chapter.page_title.rsplit('/', 1)[-1]}"


def _stage_phrase(stage: MainStoryStage) -> str:
    if stage.label[0].isdigit():
        return f"Stage {stage.label}"
    if stage.label == "Epilogue":
        return "the Epilogue"
    return stage.label


def _set_section(text: str, title: str, body: str) -> str:
    parsed = parse(text)
    if force_section_text(parsed, f" {title} ", body):
        return str(parsed)
    return f"{text.rstrip()}\n\n== {title} ==\n{body}"


def _jump_target(stage: MainStoryStage) -> str | None:
    data = None if stage.is_battle else load_story_config(stage.key)
    jumps = [row["param"][0] for row in data or () if row.get("cmd") == "JUMP_AVG_ID"]
    return normalize_story_id(jumps[-1]) if jumps else None


def _nav_pages(stages: list[MainStoryStage], i: int) -> tuple[str | None, str | None]:
    stage = stages[i]
    index = {other.key: j for j, other in enumerate(stages)}
    parents = [r for r in stage.requirements if r in index]
    if len(parents) == 1:
        prev_stage = stages[index[parents[0]]]
    else:
        prev_stage = stages[i - 1] if i > 0 else None
    children = [other for other in stages if stage.key in other.requirements]
    jump_target = _jump_target(stage)
    if jump_target in index:
        next_stage = stages[index[jump_target]]
    elif children:
        next_stage = min(children, key=lambda v: (v.is_end, index[v.key]))
    else:
        next_stage = stages[i + 1] if i < len(stages) - 1 else None
    return (
        prev_stage.page_title if prev_stage else None,
        next_stage.page_title if next_stage else None,
    )


def build_main_story_transcripts() -> dict[str, str]:
    episodes = get_main_story_episodes()
    transcripts: dict[str, str] = {}
    for chapter in get_main_story_chapters():
        stages = _story_stages(chapter)
        choice_target_links = major_choice_target_links(stages, episodes)
        for i, stage in enumerate(stages):
            nav = story_nav_template("StoryNav", *_nav_pages(stages, i))
            content = episode_to_messenger_template(
                episodes[stage.episode_id],
                choice_target_links.get(stage.episode_id),
            )
            if not stage.is_battle:
                content = with_tyrant_gender_selector(content)
            transcripts[stage.page_title] = f"{nav}\n{content}\n{nav}"
    return transcripts


def build_stage_page(
    chapter: MainStoryChapter,
    stage: MainStoryStage,
    transcript: str,
    existing_text: str,
) -> str:
    text = existing_text.strip() or (
        f"'''{stage.title}''' is {_stage_phrase(stage)} of {_chapter_phrase(chapter)}, "
        f"'''{_chapter_link(chapter)}'''.\n\n"
        f"{'' if stage.is_battle else '== Date ==\n\n'}"
        f"== Plot ==\n{stage.description}"
    )
    return _set_section(text, "Transcript", transcript)


def build_stages_section(chapter: MainStoryChapter) -> str:
    episodes = get_main_story_episodes()
    dead_ends = _dead_end_keys(chapter.stages)
    lines = []
    for stage in chapter.stages:
        name = f"[[{stage.page_title}|{stage.title}]]" if stage.episode_id in episodes else stage.title
        bullet = "**" if stage.is_end or any(r in dead_ends for r in stage.requirements) else "*"
        line = f"{bullet} '''{stage.label}: {name}'''"
        if stage.description:
            line += f"<br>{stage.description}"
        lines.append(line)
    return "\n".join(lines)


def build_chapter_page(
    chapter: MainStoryChapter,
    prev_chapter: MainStoryChapter | None,
    next_chapter: MainStoryChapter | None,
    existing_text: str,
) -> str:
    intro = f"Chapter {chapter.number}" if chapter.number else "a special chapter"
    text = existing_text.strip() or (
        "{{ChapterData\n}}\n"
        f"'''{chapter.name}''' is {intro} of the [[{MAIN_STORY_PAGE}]].\n\n"
        "== Stages =="
    )
    parsed = parse(text)
    chapter_data = find_template_by_name(parsed, "ChapterData")
    assert chapter_data is not None, chapter.page_title
    set_arg(chapter_data, "name", chapter.name)
    if not chapter_data.has_arg("image"):
        set_arg(chapter_data, "image", chapter.image)
    if chapter.number:
        set_arg(chapter_data, "number", chapter.number)
    for arg_name, other in (("prev", prev_chapter), ("next", next_chapter)):
        if other is not None:
            set_arg(chapter_data, arg_name, _chapter_link(other))
        elif chapter_data.has_arg(arg_name):
            chapter_data.del_arg(arg_name)
    return _set_section(str(parsed), "Stages", build_stages_section(chapter))


def build_main_story_section() -> str:
    lines = ["The main story currently consists of the following chapters:"]
    for chapter in get_main_story_chapters():
        prefix = f"{chapter.number}." if chapter.number else "Sp."
        lines.append(f"* {prefix} {_chapter_link(chapter)}")
    return "\n".join(lines)


def save_main_story_stage_pages() -> None:
    transcripts = build_main_story_transcripts()
    for chapter in get_main_story_chapters():
        for stage in _story_stages(chapter):
            page = Page(s, stage.page_title)
            text = build_stage_page(
                chapter,
                stage,
                transcripts[stage.page_title],
                page.text if page.exists() else "",
            )
            save_page(page, text, "update main story transcript")
        pass


def save_main_story_chapter_pages() -> None:
    chapters = get_main_story_chapters()
    for i, chapter in enumerate(chapters):
        page = Page(s, chapter.page_title)
        text = build_chapter_page(
            chapter,
            chapters[i - 1] if i > 0 else None,
            chapters[i + 1] if i < len(chapters) - 1 else None,
            page.text if page.exists() else "",
        )
        save_page(page, text, "update main story chapter page")


def save_main_story_index() -> None:
    page = Page(s, MAIN_STORY_PAGE)
    parsed = parse(page.text)
    section = find_section(parsed, MAIN_STORY_PAGE)
    assert section is not None
    categories = "".join(
        f"\n{link}" for link in section.wikilinks if link.title.strip().startswith("Category:")
    )
    section.contents = f"{build_main_story_section()}\n{categories}\n"
    save_page(page, str(parsed), "update main story chapter list")


def main():
    export_story_assets(get_main_story_episodes())
    save_main_story_stage_pages()
    # save_main_story_chapter_pages()
    # save_main_story_index()


if __name__ == "__main__":
    main()
