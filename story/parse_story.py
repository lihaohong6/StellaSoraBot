import re
from dataclasses import dataclass
from functools import cache
from typing import Any, Optional

from character_info.char_sprites import get_avg_characters
from utils.data_utils import load_lua_table
from utils.text_utils import escape_text


class StoryRow:
    name: str
    attributes: dict[str, str]

    def __init__(self, name: str, attributes: dict[str, str]):
        self.name = name
        self.attributes = dict((str(k), str(v)) for k, v in attributes.items())


@dataclass
class StoryEpisode:
    episode_id: str
    title: str
    subtitle: str
    description: str
    rows: list[StoryRow]


@dataclass
class CharacterState:
    variant: str = "a"
    expression: str = "00"

    def update(self, variant: Optional[str] = None, expression: Optional[str] = None):
        if variant:
            self.variant = variant
        if expression:
            self.expression = expression


@dataclass
class StoryState:
    current_speaker: Optional[str] = None
    character_states: Optional[dict[str, CharacterState]] = None
    pending_reply_char: Optional[str] = None

    def __post_init__(self):
        if self.character_states is None:
            self.character_states = {}

    def reset_speaker(self):
        self.current_speaker = None

    def get_character_state(self, char_id: str) -> CharacterState:
        assert self.character_states is not None
        if char_id not in self.character_states:
            self.character_states[char_id] = CharacterState()
        return self.character_states[char_id]


@cache
def get_character_sex_strings() -> dict[str, list[str]]:
    data = load_lua_table("game/ui/avg/_en/preset/avguitext.lua")
    if data and isinstance(data, dict) and "SEX" in data:
        return data["SEX"]
    return {}


@cache
def get_character_name_from_id(char_id: str | int) -> str:
    """Get character name from character ID, handling both playable characters and NPCs."""
    # Ensure char_id is a string
    if isinstance(char_id, int):
        char_id = str(char_id)

    avg_chars, _ = get_avg_characters()

    if char_id in avg_chars:
        return avg_chars[char_id].name

    # Fallback to the raw ID if no mapping found
    return char_id


def process_text(text: str) -> str:
    sex_dict = get_character_sex_strings()
    text, _ = re.subn(r"==SEX\d*==", lambda m: "/".join(sex_dict[m.group(0)]), text)
    text = escape_text(text)
    return text


def normalize_story_id(story_id: str) -> str:
    return story_id.removesuffix(".lua").lower()


def load_story_config(story_id: str) -> list[dict[str, Any]] | None:
    return load_lua_table(f"game/ui/avg/_en/config/{normalize_story_id(story_id)}.lua")


def parse_story_config(story_id: str) -> StoryEpisode | None:
    data = load_story_config(story_id)
    if data is None:
        return None
    return parse_story_episode(normalize_story_id(story_id), data)


def parse_story_episode(episode_id: str, data: Any) -> StoryEpisode:
    rows = []
    state = StoryState()

    # Extract episode info from SetIntro
    title = ""
    subtitle = ""
    description = ""

    for row in data:
        cmd = row["cmd"]
        params = row.get("param", [])

        if cmd == "SetIntro" and len(params) >= 5:
            title = process_text(params[1])
            subtitle = process_text(params[2])
            description = process_text(params[3])
            break

    for row in data:
        cmd = row["cmd"]
        params = row.get("param", [])

        def set_talk():
            position, char_id, _, text_pos, voice_line, _, _, text, _ = params
            text = process_text(text)
            speaker_name = get_character_name_from_id(char_id)

            if speaker_name != state.current_speaker:
                state.current_speaker = speaker_name

            # Get character state for sprite information
            char_state = state.get_character_state(char_id)

            is_reply = char_id == state.pending_reply_char
            if is_reply:
                state.pending_reply_char = None

            rows.append(
                StoryRow(
                    "dialogue",
                    {
                        "speaker": speaker_name,
                        "text": text,
                        "voice": voice_line if voice_line else "",
                        "position": str(position),
                        "character_id": char_id,
                        "variant": char_state.variant,
                        "expression": char_state.expression,
                        "is_reply": "true" if is_reply else "",
                    },
                )
            )

        def set_bgm():
            track_type = params[0]
            bgm_file = params[3]

            rows.append(
                StoryRow(
                    "bgm",
                    {
                        "action": "play"
                        if track_type == 0
                        else "stop",  # 0 = play, 1 = stop
                        "file": bgm_file
                    },
                )
            )

        def set_bg():
            bg_image: str = params[1]

            rows.append(
                StoryRow(
                    "background",
                    {
                        "image": bg_image.lower(),
                    },
                )
            )

        def set_scene_heading():
            time = params[0]
            month = params[1]
            day = params[2]
            location = params[3]
            area = params[4]

            rows.append(
                StoryRow(
                    "scene_heading",
                    {
                        "time": time,
                        "month": month,
                        "day": day,
                        "location": location,
                        "area": area,
                    },
                )
            )

        def set_audio():
            audio_file = params[1]
            if rows and rows[-1].name == "sound_effect":
                rows[-1].attributes["files"] += f",{audio_file}"
            else:
                rows.append(StoryRow("sound_effect", {"files": audio_file}))

        def set_char():
            # Character positioning and sprite changes
            char_id = params[3]
            char_part = params[4]
            char_expression = params[5]

            character_name = get_character_name_from_id(char_id)

            # Update character state with variant and expression
            char_state = state.get_character_state(char_id)
            char_state.update(variant=char_part, expression=char_expression)

            rows.append(
                StoryRow(
                    "character",
                    {
                        "character": character_name,
                        "character_id": char_id,
                        "part": char_part,
                        "expression": char_expression,
                    },
                )
            )

        def set_main_role_talk():
            # Player character dialogue
            # Based on actual parameter structure from story files:
            # [position, _, expression, emoji, _, direction, _, _, char_id]
            position = params[0]
            expression = params[2]
            emoji = params[3]
            direction = params[5]
            char_id = params[8]  # Character ID is at index 9 (0-based)

            character_name = get_character_name_from_id(char_id)
            state.pending_reply_char = char_id
            rows.append(
                StoryRow(
                    "main_role_talk",
                    {
                        "position": str(position),
                        "character": character_name,
                        "character_id": char_id,
                        "expression": expression,
                        "emoji": emoji,
                        "direction": str(direction),
                    },
                )
            )

        def append_choice_begin(choice_id: str, choice_texts: list[Any]):
            attrs: dict[str, str] = {"choice_id": choice_id}
            option_num = 0
            for text in choice_texts:
                if text:
                    option_num += 1
                    attrs[f"option{option_num}"] = process_text(str(text))
            rows.append(StoryRow("choice_begin", attrs))

        def set_choice_begin():
            append_choice_begin(str(params[0]), params[12])

        def set_personality_choice():
            append_choice_begin(str(params[0]), params[2:5])

        def set_choice_jump():
            rows.append(StoryRow("choice_jump", {
                "choice_id": str(params[0]),
                "option": str(params[1]),
            }))

        def set_choice_rollover():
            rows.append(StoryRow("choice_rollover", {
                "choice_id": str(params[0]),
            }))

        def set_choice_end():
            rows.append(StoryRow("choice_end", {
                "choice_id": str(params[0]),
            }))

        # Dispatcher for different command types
        dispatcher = {
            "SetTalk": set_talk,
            "SetBGM": set_bgm,
            "SetBg": set_bg,
            "SetSceneHeading": set_scene_heading,
            "SetAudio": set_audio,
            "SetChar": set_char,
            "SetMainRoleTalk": set_main_role_talk,
            "SetChoiceBegin": set_choice_begin,
            "SetChoiceJumpTo": set_choice_jump,
            "SetChoiceRollover": set_choice_rollover,
            "SetChoiceEnd": set_choice_end,
            "SetPersonalityChoice": set_personality_choice,
            "SetPersonalityChoiceJumpTo": set_choice_jump,
            "SetPersonalityChoiceRollover": set_choice_rollover,
            "SetPersonalityChoiceEnd": set_choice_end,
            "End": lambda: None,
        }

        if cmd in dispatcher:
            dispatcher[cmd]()

    return StoryEpisode(episode_id, title, subtitle, description, rows)


@cache
def load_story_files() -> dict[str, dict | list]:
    result = {}
    for chapter in range(0, 10):
        for episode in range(0, 20):
            for suffix in ["", "_a", "_b", "_c"]:
                filename = f"stm{chapter:02d}_{episode:02d}{suffix}.lua"
                full_path = "game/ui/avg/_en/config/" + filename
                table = load_lua_table(full_path)
                if table is not None:
                    result[filename.split(".")[0]] = table
    return result


@cache
def get_story_episodes() -> dict[str, StoryEpisode]:
    result: dict[str, StoryEpisode] = {}

    episode_files = load_story_files()

    for filename, data in episode_files.items():
        episode = parse_story_episode(filename, data)
        result[filename] = episode

    return result


def handle_story_branches(episodes: dict[str, StoryEpisode]):
    """Handle story branching logic (files ending with _a, _b, _c, etc.)."""
    print("Placeholder: Handle story branches")
    # This would identify story branches (e.g., stm01_08_a.lua, stm01_08_b.lua)
    # and create appropriate data structures to represent the branching narrative

    branch_groups = {}
    for episode_id in episodes.keys():
        # Check if episode ID has a branch suffix (_a, _b, _c, etc.)
        match = re.match(r"(.+)_[a-z]$", episode_id)
        if match:
            base_id = match.group(1)
            if base_id not in branch_groups:
                branch_groups[base_id] = []
            branch_groups[base_id].append(episode_id)

    print(f"Found {len(branch_groups)} story branch groups:")
    for base_id, branches in branch_groups.items():
        print(f"  - {base_id}: {', '.join(branches)}")


def main():
    """Main function to parse and process story episodes."""
    episodes = get_story_episodes()

    print(f"Parsed {len(episodes)} story episodes")

    # Show episode information
    for episode_id, episode in list(episodes.items())[:3]:  # Show first 3 as example
        print(f"\nEpisode: {episode_id}")
        print(f"Title: {episode.title}")
        print(f"Subtitle: {episode.subtitle}")
        print(f"Description: {episode.description}")
        print(f"Rows: {len(episode.rows)}")

    # Placeholder functions for exporting assets
    handle_story_branches(episodes)


if __name__ == "__main__":
    main()
