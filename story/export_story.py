import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from typing import Optional

from character_info.char_sprite_face import sanitize_css_class
from character_info.characters import id_to_char
from story.parse_story import get_story_episodes, StoryEpisode, StoryRow
from story.story_assets import export_story_assets, get_front_object_file_name
from utils.data_utils import assets_root
from utils.wiki_utils import save_page


@cache
def _get_avgbg_names() -> frozenset[str]:
    return frozenset(f.stem for f in (assets_root / "imageavg" / "avgbg").glob("*.png"))


@dataclass
class StoryExport:
    episode_id: str
    title: str
    subtitle: str
    description: str
    branches: dict[str, str]
    main_content: str


@dataclass
class StoryEntry:
    page_title: str
    episode_id: str
    parent_episode_ids: tuple[str, ...]


@dataclass
class ChoiceContext:
    choice_id: Optional[str] = None
    group: Optional[int] = None
    option: Optional[str] = None


PROTAGONIST_CHARACTER_IDS = frozenset({"avg3_100"})
TYRANT_GENDER_GROUP = "tgender"
FEMALE_TYRANT_NAME = "Female tyrant"
MALE_TYRANT_NAME = "Male tyrant"


def get_character_sprite_path(
    char_name: str, variant: str = "a", expression: str = "00"
) -> str:
    # Convert expression to integer and format as 2 digits
    # This handles cases like "002" -> "02", "01" -> "01", "1" -> "01"
    try:
        expr_num = int(expression)
    except ValueError:
        # If expression is not a valid number, default to "00"
        expr_num = 0
    return f"{char_name}_{variant}_{expr_num:02d}.png"


def with_tyrant_gender_selector(content: str) -> str:
    return "{{GenderToggle}}\n" + content


def _tyrant_sprite_name(char_name: str) -> str:
    if char_name in {FEMALE_TYRANT_NAME, MALE_TYRANT_NAME}:
        return FEMALE_TYRANT_NAME
    return char_name


def _sprite_name_for_character_id(character_id: str, fallback_name: str) -> str:
    match = re.fullmatch(r"avg1_(\d+)", character_id)
    if match:
        character = id_to_char(match.group(1))
        if character is not None:
            return character.name
    return fallback_name


def _gendered_background_pair(bg_image: str) -> tuple[str, str] | None:
    replacements = [
        ("female_tyrant", "male_tyrant"),
        ("female", "male"),
    ]
    avgbg_names = _get_avgbg_names()
    for female_text, male_text in replacements:
        if female_text not in bg_image:
            continue
        male_image = bg_image.replace(female_text, male_text)
        if bg_image.startswith("story") and male_image.startswith("story"):
            return bg_image, male_image
        if bg_image in avgbg_names and male_image in avgbg_names:
            return bg_image, male_image
    return None


def _story_background_template(bg_image: str) -> str | None:
    if bg_image.startswith("story"):
        return f"{{{{Story/background | {bg_image}}}}}"
    if bg_image in _get_avgbg_names():
        return f"{{{{Story/background | BG_{bg_image}}}}}"
    return None


def _story_background_content(bg_image: str) -> str | None:
    pair = _gendered_background_pair(bg_image)
    if pair is not None:
        female_template = _story_background_template(pair[0])
        male_template = _story_background_template(pair[1])
        if female_template is not None and male_template is not None:
            return (
                "{{GenderContent"
                f"|{female_template}"
                f"|{male_template}"
                "}}"
            )
    return _story_background_template(bg_image)


def _append_group_option(
    lines: list[str],
    group: Optional[int],
    option: Optional[str],
) -> list[str]:
    if group is None or option is None or not lines:
        return lines
    result = []
    for line in lines:
        if line == "" and result:
            result.append(f"| group :: {group}")
            result.append(f"| option :: {option}")
        result.append(line)
    return result


def story_row_to_messenger(
    row: StoryRow,
    current_speaker: Optional[str] = None,
    group: Optional[int] = None,
    option: Optional[str] = None,
) -> list[str]:
    result = []

    if row.name == "dialogue":
        speaker = row.attributes.get("speaker", "")
        text = row.attributes.get("text", "")
        variant = row.attributes.get("variant", "a")
        expression = row.attributes.get("expression", "00")
        character_id = row.attributes.get("character_id", "")
        is_reply = (
            row.attributes.get("is_reply") == "true"
            or character_id in PROTAGONIST_CHARACTER_IDS
        )

        speaker_name = speaker
        sprite_name = _sprite_name_for_character_id(character_id, speaker_name)
        sprite_name = _tyrant_sprite_name(sprite_name)

        # Skip image if expression is "00"
        image_path = None
        if expression != "00":
            image_path = get_character_sprite_path(sprite_name, variant, expression)

        if is_reply:
            reply_parts = ["| reply"]
            if image_path:
                reply_parts.append(f"| image :: {image_path}")
                reply_parts.append(f"| class :: {sanitize_css_class(sprite_name, variant)}")
            reply_parts.extend([f"| text :: {text}", ""])
            result.extend(reply_parts)
            return _append_group_option(result, group, option)

        if speaker_name != current_speaker:
            message_parts = ["| message", f"| name :: {speaker_name}"]
            if image_path:
                message_parts.append(f"| image :: {image_path}")
                message_parts.append(f"| class :: {sanitize_css_class(sprite_name, variant)}")
            message_parts.extend([f"| text :: {text}", ""])
            result.extend(message_parts)
        else:
            result.extend(["| message", f"| text :: {text}", ""])
        return _append_group_option(result, group, option)

    if row.name == "scene_heading":
        time = row.attributes.get("time", "")
        location = row.attributes.get("location", "")
        if location:
            scene_text = f"{location}"
            if time:
                scene_text = f"{time} - {location}"
            result.extend(["| info", f"| text :: {scene_text}", ""])
        return _append_group_option(result, group, option)

    if row.name == "background":
        bg_image = row.attributes.get("image", "")
        if bg_image and bg_image != "bg_black":
            content = _story_background_content(bg_image)
            if content is None:
                return result
            result.extend(["| raw", f"| content :: {content}", ""])
        return _append_group_option(result, group, option)

    if row.name == "bgm":
        action = row.attributes.get("action", "play")

        if action == "play":
            bgm_file = row.attributes.get("file", "")
            if bgm_file and bgm_file.startswith("m"):
                result.extend(["| raw", f"| content :: {{{{Story/bgm|Bg{bgm_file}.ogg}}}}", ""])
        elif action == "stop":
            result.extend(["| raw", "| content :: {{Story/bgm stop}}", ""])
        return _append_group_option(result, group, option)

    if row.name == "sound_effect":
        all_files = row.attributes.get("files", "")
        templates = []
        for se_file in all_files.split(","):
            if se_file and "stop" not in se_file:
                templates.append(f"{{{{Audio/se|{se_file}.ogg}}}}")
        if templates:
            result.extend(["| raw", f"| content :: {' '.join(templates)}", ""])
        return _append_group_option(result, group, option)

    if row.name == "front_object":
        image_name = row.attributes.get("image", "")
        if image_name:
            file_name = get_front_object_file_name(image_name)
            content = f"[[File:{file_name}|200px|link=]]"
            result.extend(["| raw", f"| content :: {content}", ""])
        return _append_group_option(result, group, option)

    return result


def _get_choice_options(row: StoryRow) -> list[str]:
    options = []
    i = 1
    while f"option{i}" in row.attributes:
        options.append(row.attributes[f"option{i}"])
        i += 1
    return options


def _current_group_option(
    choice_stack: list[ChoiceContext],
) -> tuple[Optional[int], Optional[str]]:
    for context in reversed(choice_stack):
        if context.group is not None and context.option is not None:
            return context.group, context.option
    return None, None


def _append_choice_target_link(
    result: list[str],
    context: ChoiceContext,
    choice_target_links: dict[tuple[str, str], str],
) -> None:
    if context.choice_id is None or context.group is None or context.option is None:
        return
    target_page = choice_target_links.get((context.choice_id, context.option))
    if target_page is None:
        return
    target_label = target_page.rsplit("/", 1)[-1]
    result.extend(
        [
            "| info",
            f"| text :: Continue to [[{target_page}|{target_label}]]",
            f"| group :: {context.group}",
            f"| option :: {context.option}",
            "",
        ]
    )


def episode_to_messenger_template(
    episode: StoryEpisode,
    choice_target_links: dict[tuple[str, str], str] | None = None,
) -> str:
    if choice_target_links is None:
        choice_target_links = {}

    result = [
        "{{Messenger",
        "",
        "| config",
        "| image-default-width :: 300px",
        "| columns :: 3",
        "",
    ]

    if episode.title or episode.subtitle:
        episode_info = f"{episode.title}"
        if episode.subtitle:
            episode_info += f" - {episode.subtitle}"
        result.extend(["| info", f"| text :: {episode_info}", ""])

    if episode.description:
        result.extend(["| info", f"| text :: {episode.description}", ""])

    current_speaker = None
    choice_group_counter = 0
    choice_stack: list[ChoiceContext] = []

    for row in episode.rows:
        if row.name == "choice_begin":
            options = _get_choice_options(row)
            if len(options) == 1:
                group, option = _current_group_option(choice_stack)
                result.extend(
                    _append_group_option(
                        ["| reply", f"| text :: {options[0]}", ""],
                        group,
                        option,
                    )
                )
                choice_stack.append(ChoiceContext())
            else:
                choice_group_counter += 1
                choice_stack.append(
                    ChoiceContext(
                        row.attributes.get("choice_id"),
                        choice_group_counter,
                    )
                )
                options_block = ["| options", f"| group :: {choice_group_counter}"]
                for i, opt_text in enumerate(options, 1):
                    options_block.append(f"| option{i} :: {opt_text}")
                options_block.append("")
                result.extend(options_block)
            continue

        if row.name == "choice_jump":
            if choice_stack and choice_stack[-1].group is not None:
                choice_stack[-1].option = row.attributes.get("option")
            continue

        if row.name == "choice_rollover":
            if choice_stack and choice_stack[-1].group is not None:
                _append_choice_target_link(
                    result,
                    choice_stack[-1],
                    choice_target_links,
                )
                choice_stack[-1].option = None
            continue

        if row.name == "choice_end":
            if choice_stack:
                _append_choice_target_link(
                    result,
                    choice_stack[-1],
                    choice_target_links,
                )
                choice_stack.pop()
            continue

        group, option = _current_group_option(choice_stack)
        messenger_rows = story_row_to_messenger(
            row,
            current_speaker,
            group,
            option,
        )
        result.extend(messenger_rows)

        if row.name == "dialogue":
            current_speaker = row.attributes.get("speaker", "")

    result.append("}}")
    return "\n".join(result)


def major_choice_target_links(
    entries: Sequence[StoryEntry],
    episodes: dict[str, StoryEpisode],
) -> dict[str, dict[tuple[str, str], str]]:
    result: dict[str, dict[tuple[str, str], str]] = {}

    for entry in entries:
        episode = episodes.get(entry.episode_id)
        if episode is None:
            continue

        child_entries = [
            child_entry
            for child_entry in entries
            if entry.episode_id in child_entry.parent_episode_ids
        ]
        if not child_entries:
            continue

        for row in episode.rows:
            if row.name != "choice_begin":
                continue
            if row.attributes.get("choice_type") != "major":
                continue

            options = [
                key.removeprefix("option")
                for key in row.attributes
                if re.fullmatch(r"option\d+", key)
            ]
            options = sorted(options, key=int)
            if len(options) != len(child_entries):
                print(
                    "WARNING: Major choice target count mismatch for "
                    f"{entry.page_title}: {len(options)} options, "
                    f"{len(child_entries)} child pages"
                )
                continue

            choice_id = row.attributes["choice_id"]
            for option, child_entry in zip(options, child_entries):
                result.setdefault(entry.episode_id, {})[
                    (choice_id, option)
                ] = child_entry.page_title

    return result


def story_nav_template(
    template_name: str,
    prev_page: str | None,
    next_page: str | None,
) -> str:
    args = []
    if next_page is not None:
        args.append(f"next_page={next_page}")
    if prev_page is not None:
        args.append(f"prev_page={prev_page}")
    if args:
        return "{{" + template_name + "|" + "|".join(args) + "}}"
    return "{{" + template_name + "}}"


def create_branch_tabs(branch_groups: dict[str, str]) -> str:
    if not branch_groups:
        return ""

    tab_result = ["{{Tab"]

    for branch_id, branch_content in sorted(branch_groups.items()):
        tab_name = branch_id.split("_")[-1].upper()
        tab_result.extend([f"| {tab_name}", f"| {branch_content}", ""])

    tab_result.append("}}")
    return with_tyrant_gender_selector("\n".join(tab_result))


def process_story_branches(episodes: dict[str, StoryEpisode]) -> dict[str, StoryExport]:
    exports = {}
    processed_episodes = set()

    for episode_id, episode in episodes.items():
        branch_match = re.match(r"(.+)_[a-z]$", episode_id)
        if branch_match:
            base_id = branch_match.group(1)
            if base_id not in exports:
                exports[base_id] = StoryExport(
                    episode_id=base_id,
                    title=episode.title,
                    subtitle=episode.subtitle,
                    description=episode.description,
                    branches={},
                    main_content="",
                )

            branch_content = episode_to_messenger_template(episode)
            exports[base_id].branches[episode_id] = branch_content
            processed_episodes.add(episode_id)

    for episode_id, episode in episodes.items():
        if episode_id not in processed_episodes:
            content = with_tyrant_gender_selector(episode_to_messenger_template(episode))
            exports[episode_id] = StoryExport(
                episode_id=episode_id,
                title=episode.title,
                subtitle=episode.subtitle,
                description=episode.description,
                branches={},
                main_content=content,
            )

    return exports


def save_story_pages(
    pages: dict[str, str],
    summary: str = "update story",
) -> None:
    for page_title, text in pages.items():
        save_page(page_title, text, summary)


def main():
    episodes = get_story_episodes()
    export_story_assets(episodes)
    exports = process_story_branches(episodes)

    # Get the first story export
    first_export_id = min(exports.keys()) if exports else None
    if first_export_id:
        export_data = exports[first_export_id]

        if export_data.branches:
            # If it has branches, output the tabbed content
            print(create_branch_tabs(export_data.branches))
        else:
            # If it's a single story, output the messenger template
            print(export_data.main_content)


if __name__ == "__main__":
    main()
