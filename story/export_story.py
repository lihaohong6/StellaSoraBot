import re
from dataclasses import dataclass
from functools import cache
from typing import Optional

from character_info.char_sprite_face import sanitize_css_class
from story.parse_story import get_story_episodes, StoryEpisode, StoryRow
from story.story_audio import get_bgm_path, get_sound_effect_path
from utils.data_utils import assets_root
from utils.upload_utils import UploadRequest, process_uploads
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
class StoryPageExport:
    page_title: str
    episode_id: str


@dataclass
class ChoiceContext:
    group: Optional[int] = None
    option: Optional[str] = None


PROTAGONIST_CHARACTER_IDS = frozenset({"avg3_100"})


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


def character_id_to_speaker_name(char_id: str) -> str:
    return char_id


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

        speaker_name = character_id_to_speaker_name(speaker)

        # Skip image if expression is "00"
        image_path = None
        if expression != "00":
            image_path = get_character_sprite_path(speaker_name, variant, expression)

        if is_reply:
            reply_parts = ["| reply"]
            if image_path:
                reply_parts.append(f"| image :: {image_path}")
                reply_parts.append(f"| class :: {sanitize_css_class(speaker_name, variant)}")
            reply_parts.extend([f"| text :: {text}", ""])
            result.extend(reply_parts)
            return _append_group_option(result, group, option)

        if speaker_name != current_speaker:
            message_parts = ["| message", f"| name :: {speaker_name}"]
            if image_path:
                message_parts.append(f"| image :: {image_path}")
                message_parts.append(f"| class :: {sanitize_css_class(speaker_name, variant)}")
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
            if bg_image.startswith("story"):
                pass
            elif bg_image in _get_avgbg_names():
                bg_image = f"BG_{bg_image}"
            else:
                return result
            result.extend(
                ["| raw", f"| content :: {{{{Story/background | {bg_image}}}}}", ""]
            )
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

    if row.name == "clear":
        result.extend(["| info", "| text :: [Characters cleared]", ""])
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


def episode_to_messenger_template(episode: StoryEpisode) -> str:
    result = ["{{Messenger", "", "| config", "| image-default-width :: 300px", ""]

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
                choice_stack.append(ChoiceContext(choice_group_counter))
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
                choice_stack[-1].option = None
            continue

        if row.name == "choice_end":
            if choice_stack:
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
            speaker = row.attributes.get("speaker", "")
            speaker_name = character_id_to_speaker_name(speaker)
            current_speaker = speaker_name

    result.append("}}")
    return "\n".join(result)


def create_branch_tabs(branch_groups: dict[str, str], base_episode_id: str) -> str:
    if not branch_groups:
        return ""

    tab_result = ["{{Tab"]

    for branch_id, branch_content in sorted(branch_groups.items()):
        tab_name = branch_id.split("_")[-1].upper()
        tab_result.extend([f"| {tab_name}", f"| {branch_content}", ""])

    tab_result.append("}}")
    return "\n".join(tab_result)


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
            content = episode_to_messenger_template(episode)
            exports[episode_id] = StoryExport(
                episode_id=episode_id,
                title=episode.title,
                subtitle=episode.subtitle,
                description=episode.description,
                branches={},
                main_content=content,
            )

    return exports


def build_story_pages(
    page_exports: list[StoryPageExport],
    episodes: dict[str, StoryEpisode],
) -> dict[str, str]:
    pages: dict[str, str] = {}
    for page_export in page_exports:
        if page_export.episode_id not in episodes:
            continue
        pages[page_export.page_title] = episode_to_messenger_template(
            episodes[page_export.episode_id]
        )
    return pages


def save_story_pages(
    pages: dict[str, str],
    summary: str = "update story",
) -> None:
    for page_title, text in pages.items():
        save_page(page_title, text, summary)


def main():
    episodes = get_story_episodes()
    export_bgm_files(episodes)
    export_sound_effects(episodes)
    exports = process_story_branches(episodes)

    # Get the first story export
    first_export_id = min(exports.keys()) if exports else None
    if first_export_id:
        export_data = exports[first_export_id]

        if export_data.branches:
            # If it has branches, output the tabbed content
            print(create_branch_tabs(export_data.branches, first_export_id))
        else:
            # If it's a single story, output the messenger template
            print(export_data.main_content)


def export_bgm_files(episodes: dict[str, StoryEpisode]):
    bgm_files: set[str] = set()
    for episode in episodes.values():
        for row in episode.rows:
            if row.name == "bgm":
                bgm_file = row.attributes.get("file", "")
                if bgm_file:
                    bgm_files.add(bgm_file)
    upload_requests = []
    for bgm in sorted(bgm_files):
        assert bgm.startswith("m")
        try:
            path = get_bgm_path(bgm)
        except KeyError:
            print(f"WARNING: Could not find BGM asset for {bgm}")
            continue
        upload_requests.append(UploadRequest(
            path,
            f"File:Bg{bgm}.ogg",
            "[[Category:Story BGMs]]",
            'batch upload story bgms')
        )
    process_uploads(upload_requests)


def export_sound_effects(episodes: dict[str, StoryEpisode]):
    sound_effects: set[str] = set()
    for episode in episodes.values():
        for row in episode.rows:
            if row.name == "sound_effect":
                for se_file in row.attributes.get("files", "").split(","):
                    if se_file:
                        sound_effects.add(se_file)
    upload_requests = []
    for se in sorted(sound_effects):
        if not se.startswith("se"):
            continue
        if "stop" in se:
            continue
        path = get_sound_effect_path(se)
        if path is None:
            continue
        upload_requests.append(UploadRequest(
            path,
            f"File:{se}.ogg",
            "[[Category:Sound effects]]",
            'batch upload story sound effects')
        )
    process_uploads(upload_requests)


if __name__ == "__main__":
    main()
