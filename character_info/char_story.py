import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from pywikibot import Page
from wikitextparser import parse, Template

from character_info.characters import get_characters, get_character_pages, get_id_to_char, Character
from utils.data_utils import autoload, assets_root
from utils.upload_utils import UploadRequest, process_uploads
from utils.wiki_utils import force_section_text, save_page, set_arg


@dataclass
class AffinityArchive:
    id: int
    title: str
    content: str


@cache
def get_affinity_archives() -> dict[str, list[AffinityArchive]]:
    chars = get_characters()
    result = {}
    data = autoload("CharacterArchiveContent")
    for name, char in chars.items():
        lst = []
        for i in range(2, 14):
            key = f"{char.id}{i:02}"
            if key not in data:
                break
            row = data[key]
            content = row['Content']
            content = content.replace("\n", "<br/>").replace("==PLAYER_NAME==", "<player name>")
            filename = ""
            if "acrchives_certified" in content:
                filename = "certified"
            if "acrchives_falsified" in content:
                filename = "falsified"
            if filename != "":
                repl = f"[[File:Archive {filename}.png|30px|link=]]"
                content = re.sub("<sprite[^>]+>", repl, content)
            lst.append(AffinityArchive(
                id=row['Id'],
                title=row['Title'],
                content=content
            ))
        else:
            result[name] = lst
    return result


@dataclass
class InvitationStory:
    id: int
    name: str
    clue: str
    landmark: str
    option: str
    memory: str
    desc: str

    @property
    def file_page(self) -> str:
        return f"Date CG {self.id}.png"

    @property
    def file_path(self) -> Path:
        return assets_root / "icon" / "datingeventcg" / f"datingspcg_{self.id}.png"


@dataclass
class Landmark:
    id: int
    name: str


@cache
def get_landmarks() -> dict[str, Landmark]:
    data = autoload("DatingLandmark")
    result: dict[str, Landmark] = {}
    for k, v in data.items():
        name = v['Name'].replace("The ", "")
        result[name] = Landmark(int(k), v)
    return result


def get_landmark_option(landmark: str, branch: int):
    data = autoload("DatingBranch")
    landmarks = get_landmarks()
    assert landmark in landmarks
    key = str(landmarks[landmark].id * 1000 + 1)
    assert key in data
    return data[key].get(f"Option{branch}")


def get_invitation_stories() -> dict[str, list[InvitationStory]]:
    chars = get_id_to_char()
    data = autoload("DatingCharacterEvent")
    result: dict[str, list[InvitationStory]] = {}
    for k, v in data.items():
        event_id = v['Id']
        char_id = event_id // 1000
        if char_id not in chars:
            continue
        char = chars[char_id]
        desc = "\n\n".join(v[f"Desc{i}"] for i in range(1, 10) if f"Desc{i}" in v)
        clue = v['Clue']
        landmark = re.search(r"the (.*) to unlock", clue)
        assert landmark is not None
        landmark = landmark.group(1)
        branch = v['BranchTag']
        option = get_landmark_option(landmark, branch)
        result[char.name] = result.get(char.name, [])
        result[char.name].append(InvitationStory(
            id=event_id,
            name=v['Name'],
            clue=clue,
            landmark=landmark,
            option=option,
            memory=v['Memory'],
            desc=desc,
        ))
    return result


def affinity_archive_sections(stories: list[AffinityArchive]) -> str:
    result = []
    for story in stories:
        result.append("{{Collapse|1=" + story.title + "|2=" + story.content + "}}\n")
    return "\n".join(result)


def upload_invitation_story_images() -> None:
    stories = get_invitation_stories()
    upload_requests = []
    for story_list in stories.values():
        for story in story_list:
            upload_requests.append(UploadRequest(
                story.file_path,
                story.file_page,
                '[[Category:Invitation story images]]',
                'batch upload invitation story images',
            ))
    process_uploads(upload_requests)


def invitation_story_sections(stories: list[InvitationStory]) -> str:
    result = ["{{InvitationStorySection}}"]
    for story in stories:
        result.append(f"==={story.name}===")
        template = Template("{{InvitationStory\n}}")
        set_arg(template, "file", story.file_page)
        set_arg(template, "clue", story.clue)
        set_arg(template, "landmark", story.landmark)
        set_arg(template, "option", story.option)
        set_arg(template, "memory", story.memory)
        set_arg(template, "desc", story.desc)
        result.append(str(template))
    return "\n".join(result)


def save_story_page_content():
    affinity_archives = get_affinity_archives()
    invitation_stories = get_invitation_stories()
    for char, page in get_story_pages().items():
        if page.exists():
            parsed = parse(page.text)
        else:
            parsed = parse("""{{StoryTop}}
==Affinity archives==
==Invitation stories==
""")
        text = affinity_archive_sections(affinity_archives[char.name])
        force_section_text(parsed, "Affinity archives", text)
        text = invitation_story_sections(invitation_stories[char.name])
        force_section_text(parsed, "Invitation stories", text)
        save_page(page, str(parsed), "update character story")


def get_story_pages() -> dict[Character, Page]:
    return get_character_pages(suffix="/story", must_exist=False)


def update_character_stories():
    upload_invitation_story_images()
    save_story_page_content()


def main():
    update_character_stories()


if __name__ == '__main__':
    main()
