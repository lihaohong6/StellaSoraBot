import re
from dataclasses import dataclass

from wikitextparser import parse, Template

from characters import get_id_to_char, get_character_pages
from data_utils import autoload


@dataclass
class Skill:
    name: str
    brief_desc: str
    desc: str
    cd: float
    energy: float

    def skill_escape(self, bd) -> str:
        bd = bd.replace('\v', ' ')
        bd, _ = re.subn(r'##([^#]+)#[^#]+#', lambda m: m.group(1), bd)
        bd, _ = re.subn(r'<color=(#[^>]{3,8})>([^<]+)</color>',
                        lambda m: f"{{{{color|{m.group(1)}|{m.group(2)}}}}}",
                        bd)
        bd, _ = re.subn(r"&Param\d+&", "<param>", bd)
        return bd

    def __init__(self, d):
        self.name = d['Title']
        self.brief_desc = self.skill_escape(d['BriefDesc'])
        self.desc = self.skill_escape(d['Desc'])
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
        for sec in parsed.sections:
            if not sec.title:
                continue
            if sec.title.strip() == "Gallery":
                sec.string = "==Skills==\n" + text + "\n" + sec.string
                break
            if sec.title.strip() == "Skills":
                sec.contents = text + "\n"
                break
        else:
            print(f"Warning: skill section not found for {char_name}")
            continue
        page.text = str(parsed)
        page.save(summary="Generate character skills")


def main():
    update_skills()


if __name__ == "__main__":
    main()
