import json
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from pywikibot import Page
from pywikibot.pagegenerators import PreloadingGenerator
from wikitextparser import parse, Template

from character_info.characters import ElementType
from utils.data_utils import autoload, load_json, assets_root
from utils.skill_utils import skill_escape
from utils.upload_utils import UploadRequest, process_uploads
from utils.wiki_utils import s, find_template_by_name, set_arg, save_page, find_section, set_section_content

disc_icon_root = assets_root / "icon" / "discskill"


@dataclass
class DiscSkill:
    id: int
    name: str
    descriptions: list[str] = field(default_factory=list)
    icon: int = None
    icon_bg: int = None
    unlock: list[list[tuple[str, int]]] = field(default_factory=list)

    @property
    def icon_path(self) -> Path:
        return disc_icon_root / f"discskill_{self.icon}.png"

    @property
    def icon_name(self) -> str:
        return f"{self.icon}"

    @property
    def icon_page(self) -> str:
        return f"Discskill-icon-{self.icon}.png"

    @property
    def icon_bg_name(self) -> str:
        color = {
            1: "red",
            2: "blue2",
            3: "green",
            4: "cyan",
            5: "blue",
            6: "purple"
        }[self.icon_bg]
        return f"{color}-sq"


@dataclass
class Melody:
    id: int
    name: str


@cache
def get_melodies() -> dict[int, Melody]:
    data = autoload("SubNoteSkill")
    result: dict[int, Melody] = {}
    for k, v in data.items():
        k = int(k)
        result[k] = Melody(k, v['Name'].split(" of ")[1])
    return result


def parse_disc_skill_icons(v: dict) -> tuple[int, int]:
    icon = int(v['Icon'].split("_")[-1])
    icon_bg = int(v['IconBg'].split("_")[-1])
    return icon, icon_bg


def parse_disc_skill_lock(skill_string: str | None) -> list[tuple[str, int]]:
    if skill_string is None:
        return []
    notes = get_melodies()
    result: list[tuple[str, int]] = []
    for k, quantity in json.loads(skill_string).items():
        result.append((notes[int(k)].name, quantity))
    return result


@cache
def parse_disc_skills(filename: str) -> dict[int, DiscSkill]:
    disc_skills = autoload(filename)
    result: dict[int, DiscSkill] = {}
    for v in disc_skills.values():
        group = v.get('GroupId', None)
        if group is None:
            continue
        name = v['Name']
        desc = v['Desc']
        desc = skill_escape(desc)
        for i in range(1, 100):
            key = f"Param{i}"
            if key not in v:
                break
            desc = desc.replace("{" + str(i) + "}", str(v[key]))
        if group not in result:
            result[group] = DiscSkill(group, name)
        skill = result[group]
        # Name must be consistent across ids unless this is a unlocalized field
        assert name == skill.name or name.startswith("MainSkill.") or name.startswith("SecondarySkill.")
        skill.descriptions.append(desc)
        skill.icon, skill.icon_bg = parse_disc_skill_icons(v)
        skill.unlock.append(parse_disc_skill_lock(v.get('NeedSubNoteSkills', None)))
    return result


@cache
def get_main_disc_skills() -> dict[int, DiscSkill]:
    return parse_disc_skills("MainSkill")


@cache
def get_secondary_disc_skills() -> dict[int, DiscSkill]:
    return parse_disc_skills("SecondarySkill")


def get_disc_main_skill(skill_group_id: int) -> DiscSkill:
    return get_main_disc_skills()[skill_group_id]


def get_disc_secondary_skill(skill_group_id: int) -> DiscSkill | None:
    return get_secondary_disc_skills().get(skill_group_id, None)


@dataclass
class Disc:
    id: int
    name: str = None
    rarity: int = 0
    lines_short: str = None
    story: str = None
    disc_bg: str = None
    main_skill: DiscSkill = None
    secondary_skills: list[DiscSkill] = field(default_factory=list)
    element: ElementType = None

    @property
    def image_path(self) -> Path:
        return assets_root / "disc" / self.disc_bg / f"{self.disc_bg}_b.png"

    @property
    def icon_path(self) -> Path:
        return assets_root / "icon" / "outfit" / f"outfit_{self.disc_bg}_b.png"

    @property
    def image_file(self) -> str:
        return f"Disc {self.name}.png"

    @property
    def icon_file(self) -> str:
        return f"Disc icon {self.name}.png"


@cache
def get_disks() -> dict[int, Disc]:
    data = load_json("Disc")
    items = autoload("Item")
    disc_ips = autoload("DiscIP")
    result: dict[int, Disc] = {}
    for k, v in data.items():
        disc = Disc(id=int(k))
        item = items[k]
        disc_ip = disc_ips[k]
        disc.name = item["Title"]
        if disc.name == "???":
            continue
        disc.lines_short = item['Literary']
        disc.rarity = 6 - item['Rarity']
        disc.story = disc_ip['StoryDesc']
        disc.disc_bg = v['DiscBg'].split("/")[-1]
        disc.main_skill = get_disc_main_skill(v['MainSkillGroupId'])
        s1 = get_disc_secondary_skill(v.get('SecondarySkillGroupId1', 0))
        if s1 is not None:
            disc.secondary_skills.append(s1)
            s2 = get_disc_secondary_skill(v.get('SecondarySkillGroupId2', 0))
            if s2 is not None:
                disc.secondary_skills.append(s2)
        disc.element = ElementType(v['EET'])
        result[int(k)] = disc
    return result


def upload_disc_images():
    disks = get_disks()
    upload_requests = []
    for disc in disks.values():
        upload_requests.append(UploadRequest(disc.image_path, disc.image_file, "[[Category:Disc images]]"))
        upload_requests.append(UploadRequest(disc.icon_path, disc.icon_file, "[[Category:Disc icons]]"))
    process_uploads(upload_requests)


def get_disc_pages() -> list[tuple[Disc, Page]]:
    discs = get_disks()
    name_to_disc = dict((d.name, d) for d in discs.values())
    pages = PreloadingGenerator([Page(s, d.name) for d in discs.values()])
    result = []
    for p in pages:
        result.append((name_to_disc[p.title()], p))
    return result


def save_disc_infobox():
    for disc, p in get_disc_pages():
        parsed = parse(p.text)
        t = find_template_by_name(parsed, "DiscData")
        assert t is not None
        set_arg(t, "rarity", disc.rarity)
        set_arg(t, "image_artwork", disc.image_file)
        set_arg(t, "image_icon", disc.icon_file)
        set_arg(t, "element", disc.element.name.capitalize())
        text = str(parsed)
        text = re.sub(r"\d-star", f"{disc.rarity}-star", text)
        save_page(p, text, "update infobox")


def save_disc_story():
    for disc, p in get_disc_pages():
        parsed = parse(p.text)
        section = find_section(parsed, "Story")
        assert section is not None
        section.contents = f"""
===Lines===
{disc.lines_short}
===Full story===
{disc.story}

"""
        save_page(p, str(parsed), "update disc story")


def save_disk_skills():
    for disc, p in get_disc_pages():
        parsed = parse(p.text)

        def set_template_skill(t: Template, skill: DiscSkill):
            set_arg(t, "skill_name", skill.name)
            set_arg(t, "rarity", disc.rarity)
            for i in range(1, len(skill.descriptions) + 1):
                set_arg(t, f"skill_desc_{i}", skill.descriptions[i - 1])
            set_arg(t, "skillicon", f"{{{{DiscSkillIcon|bgicon={skill.icon_bg_name}|fgicon={skill.icon_name}}}}}")
            for i in range(1, len(skill.unlock) + 1):
                unlock = " ".join("{{MelodyRequirement|" + name + "|" + str(quantity) + "}}" for name, quantity in skill.unlock[i - 1])
                if unlock != "":
                    set_arg(t, f"melody_{i}", unlock)

        t = Template("{{DiscMelodySkill\n}}")
        set_template_skill(t, disc.main_skill)
        set_section_content(parsed, "Melody Skill", str(t))

        harmoney_skills = []
        for secondary_skill in disc.secondary_skills:
            t = Template("{{DiscHarmonySkill\n}}")
            set_template_skill(t, secondary_skill)
            harmoney_skills.append(str(t))
        text = "This disc does not have any harmoney skills."
        if len(harmoney_skills) > 0:
            text = "\n".join(harmoney_skills)
        set_section_content(parsed, "Harmony Skill", text)

        save_page(p, str(parsed), "update disk skills")


def upload_disc_skill_icons():
    upload_requests = []
    for disc in get_disks().values():
        upload_requests.append(UploadRequest(
            disc.main_skill.icon_path,
            disc.main_skill.icon_page,
            "[[Category:Disc skill icons]]")
        )
        for skill in disc.secondary_skills:
            upload_requests.append(UploadRequest(
                skill.icon_path,
                skill.icon_page,
                "[[Category:Disc skill icons]]",
                "batch upload disc skill icons"
            ))
    process_uploads(upload_requests)


def create_disc_pages():
    for disc, p in get_disc_pages():
        if p.exists():
            continue
        p.text = f"""{{{{DiscData
}}}}
'''{disc.name}''' is a {disc.rarity}-star Disc in Stella Sora.

==Melody Skill==

==Harmony Skill==

==Acquisition==

==Story==

==See also==
{{{{DiscsList}}}}"""
        p.save(summary="batch create disc pages")


def main():
    upload_disc_skill_icons()
    upload_disc_images()
    create_disc_pages()
    save_disc_infobox()
    save_disk_skills()
    save_disc_story()


if __name__ == '__main__':
    main()
