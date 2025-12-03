import re
from dataclasses import dataclass
from enum import Enum
from functools import cache
from pathlib import Path

from wikitextparser import parse, Template

from character_info.characters import get_id_to_char, get_character_pages, ElementType, common_name_to_element_type
from utils.data_utils import autoload, load_json, data_root, assets_root
from utils.skill_utils import skill_escape, get_effects, Effect
from utils.upload_utils import UploadRequest, process_uploads
from utils.wiki_utils import force_section_text, set_arg, save_page

class SkillParamType(Enum):
    NONE = 0
    ASCENSION = 1
    SKILL_LEVEL = 3
    BREAKTHROUGH = 4

@dataclass
class SkillParam:
    param_type: SkillParamType
    params: list[int] | int | str


def get_effect_by_type(type1: int, type2: int) -> Effect:
    effects = [e for e in get_effects() if e.type1 == type1 and e.type2 == type2]
    assert len(effects) > 0
    effect = effects[0]
    return effect

def process_param(param: str) -> tuple[SkillParamType, list[int] | int | str]:
    hint: str = ""
    dict_key_hint: str = ""

    def normalize_percentage(original_value: float | list[float]) -> str | list[str]:
        if type(original_value) is list:
            return [normalize_percentage(v2) for v2 in original_value]
        try:
            value = float(original_value)
        except ValueError:
            return str(original_value)
        suffix = "%"
        if dict_key_hint == "Time":
            suffix = ""
        if "Pct" in hint:
            suffix = "%"
        if "10K" in hint:
            value /= 10000
        if "HdPct" in hint:
            value *= 100
        return f"{value:.1f}{suffix}"

    segments = param.split(',')
    if len(segments) > 4:
        hint = segments[-1]
    else:
        hint = "10K"
    file_name = segments[0]
    data = load_json(file_name)
    if not data:
        raise RuntimeError(f"No data found for {file_name}")
    param_id = segments[2]
    dict_key_hint = segments[3] if len(segments) > 3 else ""
    row: dict = data.get(str(param_id), {})
    param_type = SkillParamType(row.get('levelTypeData', 0))
    if file_name == "Skill" and dict_key_hint == "Title":
        return param_type, row["Title"]
    if row is not None and "SkillPercentAmend" in row:
        return param_type, normalize_percentage(row["SkillPercentAmend"])
    if file_name in {"Shield", "Buff", "Effect"}:
        value_table = load_json(f"{file_name}Value")
        cur_id = int(param_id)
        if str(cur_id) not in value_table:
            cur_id += 10
        if str(cur_id) not in value_table:
            raise RuntimeError(f"{file_name} not found for {param}")
        result = []
        for i in range(0, 10):
            key = str(cur_id + i * 10)
            # Only 1/2 value(s); terminate early
            if i in {1, 2} and key not in value_table:
                return param_type, result[0]
            v = value_table[key][dict_key_hint]
            if dict_key_hint == "EffectTypeFirstSubtype":
                # Special case: this is an effect that needs to be looked up in a table
                type2 = value_table[key]["EffectTypeSecondSubtype"]
                effect = get_effect_by_type(v, type2)
                result.append(effect.desc)
            else:
                v = normalize_percentage(v)
                result.append(v)
        return param_type, result
    if file_name == "EffectValue":
        assert segments[1] == "NoLevel"
        value = row[dict_key_hint]
        if dict_key_hint == "EffectTypeFirstSubtype":
            value = get_effect_by_type(value, row['EffectTypeSecondSubtype']).desc
        return param_type, normalize_percentage(value)
    if file_name == "BuffValue":
        assert segments[3] == "Time"
        return param_type, int(row["Time"] / 10000)
    raise RuntimeError(f"Could not find matching file for param {param}")


def parse_param(param_string: str) -> SkillParam:
    param_type, param = process_param(param_string)
    if type(param) is not int:
        if type(param) is not list:
            param = [param]
        values: list[str] = param
        if all(".0" in value for value in values):
            param = [value.replace(".0", "") for value in values]
    return SkillParam(param_type, param)


def parse_params(d: dict, max_params: int) -> list[SkillParam]:
    params: list[SkillParam] = []
    for i in range(1, max_params + 1):
        param_key = f"Param{i}"
        try:
            param = parse_param(d[param_key])
        except Exception as e:
            print(d['Id'])
            print(e)
            param = SkillParam(SkillParamType.NONE, -1)
        params.append(param)
    return params


def skill_level_hint(param_type: SkillParamType, original: str) -> str:
    if param_type in {SkillParamType.ASCENSION, SkillParamType.BREAKTHROUGH}:
        return "{{SkillLevelHint|" + param_type.name.lower() + "|" + original + "}}"
    return original


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
                print(f"Failed to format {self.name} for level {level}")
                continue
            result.append(desc)
        return result

    def to_template(self) -> Template:
        t = Template("{{TrekkerSkill\n}}")

        set_arg(t, "name", self.name)
        set_arg(t, "brief", format_desc(self.brief_desc, self.params, 1))
        if self.cd != 0:
            set_arg(t, "cooldown", self.cd)
        if self.energy != 0:
            set_arg(t, "energy", self.energy)
        long_desc = self.format_params()
        if long_desc:
            for index, desc in enumerate(long_desc, 1):
                set_arg(t, f"desc_{index}", desc)

        return t


def format_desc(desc: str, params: list[SkillParam], level: int) -> str | None:
    for param_num, skill_param in enumerate(params):
        search_string = "{" + str(param_num + 1) + "}"
        if search_string not in desc:
            continue
        param = skill_param.params
        if param == -1:
            return None
        if type(param) != list:
            desc = desc.replace(search_string, str(param))
        else:
            if skill_param.param_type == SkillParamType.SKILL_LEVEL:
                desc = desc.replace(search_string, str(param[level]))
            else:
                # At most 9 levels. Sometimes we get filler data with 0s.
                string = "/".join(param[:9])
                string = skill_level_hint(skill_param.param_type, string)
                desc = desc.replace(search_string, string)
    return desc


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
    for char, page in get_character_pages():
        skills = all_skills.get(char.name)
        if skills is None:
            continue
        result = []
        for skill, skill_type in [(skills.attack, "auto"),
                     (skills.main, "main"),
                     (skills.support, "support"),
                     (skills.ultimate, "ultimate")]:
            t = skill.to_template()
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


def main():
    upload_skill_icons()
    update_skills()


if __name__ == "__main__":
    main()
