import re
from dataclasses import dataclass
from functools import cache
from typing import Any

from pywikibot import FilePage
from wikitextparser import parse

from character_info.char_sprites import get_avg_characters
from character_info.char_story import get_story_pages
from character_info.characters import get_characters, Character, id_to_char
from utils.data_utils import lua_root, assets_root, load_lua_table
from utils.text_utils import escape_text
from utils.upload_utils import UploadRequest, process_uploads
from utils.wiki_utils import s, force_section_text, save_page


class MessengerRow:
    name: str
    attributes: dict[str, str]

    def __init__(self, name: str, attributes: dict[str, str]):
        self.name = name
        self.attributes = dict((str(k), str(v)) for k, v in attributes.items())


@dataclass
class MessengerConversation:
    rows: list[MessengerRow]


@dataclass
class CharacterMessages:
    char: Character
    messages: list[MessengerConversation]


@dataclass
class MessageState:
    char_string: str | None = None
    choice_group_counter: int = 0
    choice_group: int | None = None
    choice_option: int | None = None

    def reset_char_string(self):
        self.char_string = None

    def reset(self):
        self.reset_char_string()


@cache
def get_character_sex_strings() -> dict[str, list[str]]:
    data = load_lua_table("game/ui/avg/_en/preset/avguitext.lua")
    return data["SEX"]


def process_text(text: str) -> str:
    sex_dict = get_character_sex_strings()
    text, _ = re.subn(r"==SEX\d*==", lambda m: "/".join(sex_dict[m.group(0)]), text)
    text = escape_text(text)
    return text


def parse_private_messages(char: Character, data: list[dict[str, Any]]) -> CharacterMessages:
    conversation_list: list[MessengerConversation] = []
    current_conversation: list[MessengerRow]

    state = MessageState()
    for row in data:
        cmd = row['cmd']
        params = row.get('param', [])

        options_dict = {}
        if state.choice_group is not None and state.choice_option is not None:
            options_dict['group'] = state.choice_group
            options_dict['option'] = state.choice_option

        def set_group_id():
            nonlocal current_conversation
            current_conversation = []
            conversation_list.append(MessengerConversation(current_conversation))
            state.reset_char_string()

        def set_phone_msg():
            msg_type, char_string, image_name, _, _, _, _, text, _ = params
            # 0: Trekker message
            # 1: Tyrant message
            # 3: Trekker sticker
            # 4: Tyrant sticker
            # 5: Info?
            assert msg_type in {0, 1, 3, 4, 5}
            char_string: str

            # Sometimes we get the wrong msg_type. Fix this explicitly.
            if char_string == "avg3_101" and msg_type in {0, 3}:
                msg_type += 1

            text = process_text(text)
            show_pfp = False
            if char_string != state.char_string:
                show_pfp = True
                state.char_string = char_string
            if msg_type == 5:
                current_conversation.append(
                    MessengerRow("info", {"text": text} | options_dict)
                )
                return
            if msg_type in {3, 4}:
                assert text == "" and image_name != ""
                if image_name.startswith("emoji"):
                    size = "90"
                else:
                    size = "200"
                text = f"[[File:Phone_{image_name}.png|{size}px]]"
            if msg_type in {1, 4}:
                current_conversation.append(
                    MessengerRow("reply", {"text": text} | options_dict)
                )
                return
            pfp_dict = {}
            if show_pfp:
                char_id = int(char_string.split("_")[-1])
                speaker = id_to_char(char_id).name
                pfp = f"{speaker}-head-s.png"
                pfp_dict['name'] = speaker
                pfp_dict['image'] = pfp
                pfp_dict['image-width'] = '80px'
            current_conversation.append(MessengerRow(
                "message",
                {"text": text} | options_dict | pfp_dict
            ))

        def set_phone_msg_choice_begin():
            state.choice_group_counter += 1
            state.choice_group = state.choice_group_counter
            state.choice_option = None
            options = [process_text(option) for option in params[1:-1] if option.strip() != ""]
            options = dict((f"option{index}", option) for index, option in enumerate(options, 1))
            current_conversation.append(MessengerRow(
                "options",
                {"group": state.choice_group} | options
            ))

        def set_phone_msg_choice_jump_to():
            group, option = params
            option = int(option)
            state.choice_option = option

        def set_phone_msg_choice_end():
            state.choice_group = None
            state.choice_option = None

        dispatcher = {
            'SetGroupId': set_group_id,
            'SetPhoneMsg': set_phone_msg,
            'SetPhoneMsgChoiceBegin': set_phone_msg_choice_begin,
            'SetPhoneMsgChoiceJumpTo': set_phone_msg_choice_jump_to,
            'SetPhoneMsgChoiceEnd': set_phone_msg_choice_end,
            'End': lambda: None,
        }
        dispatcher[cmd]()

    return CharacterMessages(char, conversation_list)


def conversation_to_template(conversation: MessengerConversation) -> str:
    result = ["{{Messenger\n"]
    for row in conversation.rows:
        name = row.name
        result.append("| " + name)
        for k, v in row.attributes.items():
            result.append(f"| {k} :: {v}")
        result[-1] += "\n"
    result.append("}}")
    return "\n".join(result)


def get_private_messages() -> dict[str, CharacterMessages]:
    pm_root = "game/ui/avg/_en/config/"
    result: dict[str, CharacterMessages] = {}
    for char_name, char in get_characters().items():
        pm_path = pm_root + f"pm{char.id}01.lua"
        data = load_lua_table(pm_path)
        if data is None:
            print(f"ERROR: {char_name}'s PM file {pm_path} does not exist")
            continue
        messages = parse_private_messages(char, data)
        result[char_name] = messages
    return result


def save_private_message_pages() -> None:
    messages = get_private_messages()
    for char, page in get_story_pages().items():
        parsed = parse(page.text)
        result = []
        if char.name not in messages:
            continue
        for index, conversation in enumerate(messages[char.name].messages, 1):
            lines = [
                "{{ToggleChat",
                f"|Conversation {index}",
                "|" + conversation_to_template(conversation),
                "}}"
            ]
            result.append("\n".join(lines))
        force_section_text(parsed,
                           section_title="Heartlink Chat",
                           text="\n\n".join(result),
                           prepend="Invitation stories")
        save_page(page, str(parsed), summary="Update Heartlink chat")


def upload_emojis():
    path = assets_root / "icon/avgphoneemojimsg"
    upload_requests = []
    for file in path.glob("*.png"):
        assert file.name.startswith("emoji")
        target = FilePage(s, f"File:Phone_{file.name}")
        upload_requests.append(UploadRequest(
            file,
            target,
            text="[[Category:Phone emojis]]",
            summary="batch upload phone emojis")
        )
    process_uploads(upload_requests)


def upload_phone_pictures():
    path = assets_root / "icon/avgphoneimagemsg"
    upload_requests = []
    for file in path.glob("pic*.png"):
        target = FilePage(s, f"File:Phone_{file.name}")
        upload_requests.append(UploadRequest(
            file,
            target,
            text="[[Category:Chat images]]",
            summary="batch upload Heartlink chat images"
        ))
    process_uploads(upload_requests)


def update_private_messages() -> None:
    upload_emojis()
    upload_phone_pictures()
    save_private_message_pages()


def main():
    update_private_messages()


if __name__ == "__main__":
    main()
