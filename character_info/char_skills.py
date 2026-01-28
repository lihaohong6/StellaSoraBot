import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from wikitextparser import parse, Template

from character_info.char_advance import get_char_skill_material, upgrade_material_to_string
from character_info.characters import get_id_to_char, get_character_pages, ElementType, common_name_to_element_type
from page_generators.items import make_item_template, get_all_items
from utils.data_utils import autoload, assets_root
from utils.skill_utils import skill_escape, get_words, SkillParam, parse_params, format_desc
from utils.upload_utils import UploadRequest, process_uploads
from utils.wiki_utils import force_section_text, set_arg, save_page, save_json_page


@dataclass
class Skill:
    id: int
    name: str
    brief_desc: str
    desc: str
    cd: float
    energy: float
    icon: str
    params: list[SkillParam]

    def icon_path(self) -> Path:
        p = assets_root / "icon/skill"
        return p / f"{self.icon.lower()}.png"

    def icon_page(self) -> str:
        return f"{self.icon}.png"

    def __init__(self, d):
        self.id = d["Id"]
        self.name = d['Title']
        self.brief_desc = skill_escape(d['BriefDesc'])
        self.desc = skill_escape(d['Desc'])
        self.cd = d.get('SkillCD', 0) / 10000.0
        self.energy = d.get('UltraEnergy', 0) / 10000.0
        self.icon = d['Icon'].split("/")[-1]
        max_params = 0
        for i in range(1, 100):
            if "{" + str(i) + "}" in self.desc:
                max_params = i
        self.params = parse_params(d, max_params)

    def format_params(self) -> list[str] | None:
        result = []
        for level in range(10):
            desc = format_desc(self.desc, self.params, level)
            if desc is None:
                continue
            result.append(desc)
        return result

    def to_template(self, upgrade_materials_brief: str, upgrade_materials: list[str]) -> Template:
        t = Template("{{TrekkerSkill\n}}")

        set_arg(t, "name", self.name)
        set_arg(t, "brief", format_desc(self.brief_desc, self.params, 1) + "<br>Upgrade materials: " + upgrade_materials_brief)
        if self.cd != 0:
            set_arg(t, "cooldown", self.cd)
        if self.energy != 0:
            set_arg(t, "energy", self.energy)
        long_desc = self.format_params()
        if long_desc:
            for index, desc in enumerate(long_desc, 1):
                append = ""
                if index - 1 < len(upgrade_materials):
                    append = "<br>Upgrade materials: " + upgrade_materials[index - 1]
                set_arg(t, f"desc_{index}", desc + append)
        return t


@dataclass
class CharSkills:
    attack: Skill
    main: Skill
    support: Skill
    ultimate: Skill

    @property
    def skill_list(self) -> list[Skill]:
        return [self.attack, self.main, self.support, self.ultimate]

    @property
    def element(self) -> ElementType:
        groups = []
        for skill in self.skill_list:
            groups.extend(re.findall(r"\{\{word\|[^|]+\|([^}]*)}", skill.desc))
        groups = set(groups)
        if "" in groups:
            groups.remove("")
        assert len(groups) == 1
        return common_name_to_element_type(groups.pop())


@cache
def get_skills() -> dict[str, CharSkills]:
    id_to_char = get_id_to_char()
    result = {}
    data = autoload("Skill")

    for char_id, char in id_to_char.items():
        def get(key: int) -> dict:
            k1 = str(char_id) + str(key)
            if k1 in data:
                return data[k1]
            k2 = str(char_id) + str(key + 1)
            if k2 in data:
                return data[k2]
            raise RuntimeError()

        result[char.name] = CharSkills(
            attack=Skill(get(10000)),
            main=Skill(get(31000)),
            support=Skill(get(32000)),
            ultimate=Skill(get(40000)),
        )
    return result


def update_skills():
    all_skills = get_skills()
    for char, page in get_character_pages().items():
        skills = all_skills.get(char.name)
        if skills is None:
            continue
        result = []
        skill_materials = get_char_skill_material()[char.id]
        material_ids = list(sorted(set(item[0] for m in skill_materials for item in m.items)))
        upgrade_items = [upgrade_material_to_string(m) for m in skill_materials]
        for skill, skill_type in [(skills.attack, "auto"),
                     (skills.main, "main"),
                     (skills.support, "support"),
                     (skills.ultimate, "ultimate")]:
            brief_upgrade = " ".join(str(make_item_template(get_all_items()[material_id])) for material_id in material_ids)
            t = skill.to_template(brief_upgrade, upgrade_items)
            set_arg(t, "type", skill_type)
            icon_template = Template("{{TrekkerSkillIcon}}")
            icon_template.set_arg("element", skills.element.name)
            icon_template.set_arg("icon", skill.icon_page().replace(".png", ""))
            icon_template.set_arg("type", skill_type)
            set_arg(t, "icon", str(icon_template))
            result.append(str(t))

        parsed = parse(page.text)
        text = '\n'.join(result)
        res = force_section_text(parsed, "Skills", text, "Gallery")
        if not res:
            print(f"Warning: skill section not found for {char.name}")
            continue
        save_page(page, str(parsed), summary="Generate character skills")


def upload_skill_icons():
    upload_requests = []
    for k, v in get_skills().items():
        for skill in v.skill_list:
            p = skill.icon_path()
            if not p.exists():
                continue
            upload_requests.append(UploadRequest(
                skill.icon_path(),
                skill.icon_page(),
                "[[Category:Skill icons]]",
            ))
    process_uploads(upload_requests)


def update_words():
    words = get_words()
    obj = {}
    for word in words.values():
        obj[word.name] = word.desc
    save_json_page("Module:Words/data.json", obj)


def skill_main():
    upload_skill_icons()
    update_skills()
    update_words()


if __name__ == "__main__":
    skill_main()
