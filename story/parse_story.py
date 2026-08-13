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
    character_states: Optional[dict[str, CharacterState]] = None
    pending_reply_char: Optional[str] = None
    current_background: Optional[str] = None
    current_front_objects: Optional[dict[str, str]] = None

    def __post_init__(self):
        if self.character_states is None:
            self.character_states = {}
        if self.current_front_objects is None:
            self.current_front_objects = {}

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


def phone_sticker_link(image_name: str) -> str:
    size = "90" if image_name.startswith("emoji") else "200"
    return f"[[File:Phone_{image_name}.png|{size}px]]"


def process_text(text: str) -> str:
    sex_dict = get_character_sex_strings()
    gender_tabs: dict[str, str] = {}

    def replace_sex_marker(match: re.Match[str]) -> str:
        values = sex_dict.get(match.group(0))
        if values is None:
            return match.group(0)
        female, male = (escape_text(value) for value in values)
        token = f"__STORY_GENDER_TAB_{len(gender_tabs)}__"
        gender_tabs[token] = f"{{{{GenderContent|1={female}|2={male}}}}}"
        return token

    text, _ = re.subn(r"==SEX\d*==", replace_sex_marker, text)
    text = escape_text(text)
    for token, tab in gender_tabs.items():
        text = text.replace(token, tab)
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

        def append_dialogue(char_id: str, text: str):
            speaker_name = get_character_name_from_id(char_id)

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
                        "character_id": char_id,
                        "variant": char_state.variant,
                        "expression": char_state.expression,
                        "is_reply": "true" if is_reply else "",
                    },
                )
            )

        def set_talk():
            _, char_id, _, _, _, _, _, text, _ = params
            # Animation frames the game itself keeps out of the story log.
            if text.startswith("_NOT_IN_LOG_"):
                return
            text = process_text(text)
            if text:
                append_dialogue(char_id, text)

        def set_phone_msg():
            msg_type, char_id, image_name, _, _, _, _, text, _ = params
            text = process_text(text)
            if msg_type == 5:
                if text:
                    rows.append(StoryRow("info", {"text": text}))
                return
            if msg_type in (3, 4) and image_name:
                text = phone_sticker_link(image_name)
            if text:
                append_dialogue(char_id, text)

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
            bg_image = str(params[1]).lower()
            if bg_image == state.current_background:
                return
            state.current_background = bg_image

            rows.append(
                StoryRow(
                    "background",
                    {
                        "image": bg_image,
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

        def set_front_obj() -> None:
            assert state.current_front_objects is not None
            action = params[0]
            position = str(params[1])
            image_name = params[2]

            if action == 1:
                state.current_front_objects.pop(position, None)
                return

            if action != 0:
                return

            if not image_name:
                return

            if image_name in state.current_front_objects.values():
                state.current_front_objects[position] = image_name
                return

            state.current_front_objects[position] = image_name
            rows.append(
                StoryRow(
                    "front_object",
                    {
                        "image": image_name.lower(),
                        "position": position,
                    },
                )
            )

        def update_character_state(
            char_id: str,
            char_part: Optional[str],
            char_expression: Optional[str],
        ):
            char_state = state.get_character_state(char_id)
            char_state.update(variant=char_part, expression=char_expression)

        def set_char():
            update_character_state(params[3], params[4], params[5])

        def set_char_head():
            update_character_state(params[5], params[6], params[7])

        def ctrl_char():
            update_character_state(params[0], params[1], params[2])

        def set_main_role_talk():
            # [position, _, expression, emoji, _, part, _, _, char_id]
            update_character_state(params[8], params[5], params[2])
            state.pending_reply_char = params[8]

        def append_choice_begin(
            choice_id: str,
            choice_texts: list[Any],
            choice_type: str = "",
        ):
            attrs: dict[str, str] = {"choice_id": choice_id}
            if choice_type:
                attrs["choice_type"] = choice_type
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

        def set_ifunlock_choice():
            # params[0] = a_1
            # params[1] = C07_06_bb (reference to episode that needs to be unlocked?)
            append_choice_begin(str(params[0]), [
                f"{str(params[1])} unlocked", # How to get pretty name?
                "Path not discovered yet"
            ])
            rows.append(StoryRow("choice_jump", {
                "choice_id": str(params[0]),
                "option": "1",
            }))

        def set_ifunlock_else():
            rows.append(StoryRow("choice_jump", {
                "choice_id": str(params[0]),
                "option": "2",
            }))

        def set_ifunlock_end():
            set_choice_end()

        def set_phone_msg_choice_begin():
            append_choice_begin(str(params[0]), params[1:7])

        def set_major_choice():
            choice_texts = []
            option_params = params[1:-5]
            for i in range(0, len(option_params), 7):
                option = option_params[i:i + 7]
                if len(option) < 4:
                    continue
                prompt = str(option[2]).strip()
                action = str(option[3]).strip()
                if prompt and action:
                    choice_texts.append(f"{prompt}<br>{action}")
                else:
                    choice_texts.append(prompt or action)
            append_choice_begin(str(params[0]), choice_texts, "major")

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
            "SetPhoneMsg": set_phone_msg,
            "SetBGM": set_bgm,
            "SetBg": set_bg,
            "SetSceneHeading": set_scene_heading,
            "SetAudio": set_audio,
            "SetFrontObj": set_front_obj,
            "SetChar": set_char,
            "SetCharHead": set_char_head,
            "CtrlChar": ctrl_char,
            "SetMainRoleTalk": set_main_role_talk,
            "SetChoiceBegin": set_choice_begin,
            "SetChoiceJumpTo": set_choice_jump,
            "SetChoiceRollover": set_choice_rollover,
            "SetChoiceEnd": set_choice_end,
            "IfUnlock": set_ifunlock_choice,
            "IfUnlockElse": set_ifunlock_else,
            "IfUnlockEnd": set_ifunlock_end,
            "SetPersonalityChoice": set_personality_choice,
            "SetPersonalityChoiceJumpTo": set_choice_jump,
            "SetPersonalityChoiceRollover": set_choice_rollover,
            "SetPersonalityChoiceEnd": set_choice_end,
            "SetMajorChoice": set_major_choice,
            "SetMajorChoiceJumpTo": set_choice_jump,
            "SetMajorChoiceRollover": set_choice_rollover,
            "SetMajorChoiceEnd": set_choice_end,
            "SetPhoneMsgChoiceBegin": set_phone_msg_choice_begin,
            "SetPhoneMsgChoiceJumpTo": set_choice_jump,
            "SetPhoneMsgChoiceRollover": set_choice_rollover,
            "SetPhoneMsgChoiceEnd": set_choice_end,
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


if __name__ == "__main__":
    main()
