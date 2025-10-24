import re
from dataclasses import dataclass
from functools import cache

from wikitextparser import parse, Template

from character_info.characters import get_id_to_char, get_character_pages
from utils.data_utils import autoload, load_json
from utils.wiki_utils import force_section_text


def skill_escape(bd) -> str:
    bd = bd.replace('\v', ' ')
    bd, _ = re.subn(r'##([^#]+)#[^#]+#', lambda m: m.group(1), bd)
    bd, _ = re.subn(r'<color=(#[^>]{3,8})>([^<]+)</color>',
                    lambda m: f"{{{{color|{m.group(1)}|{m.group(2)}}}}}",
                    bd)
    bd, _ = re.subn(r"&Param\d+&", "<param>", bd)
    return bd


def parse_param(param: str) -> list[int] | int:
    segments = param.split(',')
    file_name = segments[0]
    data = load_json(file_name)
    param_id = segments[2]
    row: dict | None = data.get(str(param_id), None)
    if row is not None and "SkillPercentAmend" in row:
        return row["SkillPercentAmend"]
    if file_name == "Effect":
        effect_value = load_json("EffectValue")
        cur_id = int(param_id) + 10
        if str(cur_id) not in effect_value:
            raise RuntimeError(f"Effect not found for {param}")
        result = []
        for i in range(0, 10):
            result.append(effect_value[str(cur_id + i * 10)]['EffectTypeParam1'])
        return result
    if file_name == "EffectValue":
        assert segments[1] == "NoLevel"
        return row['EffectTypeParam1']
    if file_name == "BuffValue":
        assert row["Time"] > 0
        print(row['Time'])
        return row["Time"] / 10000
    if file_name == "Buff":
        load_json("HitDamage")

    raise RuntimeError(f"Could not find matching file for param {param}")


def parse_params(d: dict) -> list[list[str]]:
    params = []
    for i in range(1, 100):
        param_key = f"Param{i}"
        if param_key not in d:
            break
        try:
            param = parse_param(d[param_key])
        except RuntimeError as e:
            print(e)
            param = [-1]
        params.append(param)
    return params


@dataclass
class Skill:
    name: str
    brief_desc: str
    desc: str
    cd: float
    energy: float
    params: list[list[str]]

    def __init__(self, d):
        self.name = d['Title']
        try:
            self.params = parse_params(d)
        except Exception:
            self.params = []
        self.brief_desc = skill_escape(d['BriefDesc'])
        self.desc = skill_escape(d['Desc'])
        self.cd = d.get('SkillCD', 0) / 10000.0
        self.energy = d.get('UltraEnergy', 0) / 10000.0

    def to_template(self) -> Template:
        t = Template("{{TrekkerSkill\n}}")

        def set_arg(k, v):
            t.set_arg(" " + k + " ", " " + v + "\n")

        set_arg("name", self.name)
        set_arg("desc_1", self.brief_desc)
        if self.cd != 0:
            set_arg("cooldown", str(self.cd))
        if self.energy != 0:
            set_arg("energy", str(self.energy))
        return t


@dataclass
class CharSkills:
    attack: Skill
    main: Skill
    support: Skill
    ultimate: Skill


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
    pages = get_character_pages()
    for char_name, page in pages.items():
        skills = all_skills.get(char_name)
        if skills is None:
            continue
        result = []
        for k, v in [(skills.attack, "auto"),
                     (skills.main, "main"),
                     (skills.support, "support"),
                     (skills.ultimate, "ultimate")]:
            t = k.to_template()
            t.set_arg(" type ", " " + v + "\n")
            result.append(str(t))

        parsed = parse(page.text)
        text = '\n'.join(result)
        res = force_section_text(parsed, "Skills", text, "Gallery")
        if not res:
            print(f"Warning: skill section not found for {char_name}")
            continue
        page.text = str(parsed)
        page.save(summary="Generate character skills")


def main():
    for v in get_skills().values():
        print(v)


if __name__ == "__main__":
    main()
