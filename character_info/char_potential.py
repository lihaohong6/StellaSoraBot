import enum
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from textwrap import indent

from wikitextparser import Template, parse

from character_info.char_skills import parse_params, SkillParam, format_desc, SkillParamType
from character_info.characters import Character, id_to_char, get_character_pages
from utils.data_utils import autoload, data_to_dict, assets_root
from utils.skill_utils import skill_escape
from utils.upload_utils import UploadRequest, process_uploads
from utils.wiki_utils import set_arg, force_section_text, save_page, PageCreationRequest, process_page_creation_requests


class PotentialType(enum.Enum):
    ONCE = 1
    RARE = 2
    COMMON = 3


@dataclass
class Potential:
    id: int
    name: str
    brief: str
    desc: str
    rarity: int
    build: int
    branch_type: int
    max_level: int
    params: list[SkillParam]
    icon: str
    shape: int

    def get_icon_path(self) -> Path:
        return assets_root / "icon/potential" / self.icon


def get_potential_type(p: Potential) -> PotentialType:
    if p.max_level <= 1:
        return PotentialType.ONCE
    if p.rarity == 1:
        return PotentialType.RARE
    return PotentialType.COMMON


@dataclass
class PotentialBuild:
    name: str
    desc: str
    potentials: list[Potential]


@dataclass
class CharPotentials:
    char: Character
    main_builds: list[PotentialBuild]
    support_builds: list[PotentialBuild]


@cache
def parse_potentials() -> dict[int, Potential]:
    items = autoload("Item")
    potentials_raw = autoload("Potential")
    result: dict[int, Potential] = {}
    for k, v in potentials_raw.items():
        potential_id = v['Id']
        item = items[str(potential_id)]
        name = item['Title']
        rarity = item['Rarity']
        brief = skill_escape(v['BriefDesc'])
        attrs = data_to_dict(v, ["max_level", "branch_type", "build", "desc"])
        attrs['desc'] = skill_escape(attrs['desc'])
        params = parse_params(v, max_params=100)
        for p in params:
            p.param_type = SkillParamType.NONE
        icon = item['Icon'].split("/")[-1].lower() + "_a.png"
        result[potential_id] = Potential(
            id=potential_id,
            name=name,
            rarity=rarity,
            brief=brief,
            params=params,
            icon=icon,
            shape=v.get('Corner', 0),
            **attrs
        )
    return result


def construct_builds(potentials: list[Potential],
                     titles: list[str],
                     descriptions: list[str]) -> list[PotentialBuild]:
    builds: list[PotentialBuild] = []
    for i in range(3):
        pots = [p for p in potentials if p.build == i + 1]
        builds.append(PotentialBuild(titles[i], descriptions[i], pots))
    return builds


@cache
def get_potentials() -> dict[Character, CharPotentials]:
    all_potentials = parse_potentials()
    data = autoload("CharPotential")
    char_des_all = autoload("CharacterDes")
    result: dict[Character, CharPotentials] = {}
    for k, v in data.items():
        char_id = v['Id']
        char = id_to_char(char_id)
        if char is None:
            continue
        char_des = char_des_all[str(char_id)]
        builds = []
        for key1, key2 in [('Master', 'Main'), ('Assist', 'Assistant')]:
            potentials = v[f'{key1}SpecificPotentialIds'] + v[f'{key1}NormalPotentialIds'] + v['CommonPotentialIds']
            potentials = [all_potentials[p] for p in potentials]
            titles = [char_des[f'Potential{key2}1'], char_des[f'Potential{key2}2'], 'Generic']
            descriptions = [char_des[f'Potential{key2}Content1'], char_des[f'Potential{key2}Content2'], '']
            builds.extend(construct_builds(
                potentials,
                titles=titles,
                descriptions=descriptions)
            )
        result[char] = CharPotentials(char, builds[:3], builds[3:])
    return result


def format_potential(potential: Potential) -> str:
    t = Template("{{TrekkerPotential\n}}")
    set_arg(t, "name", potential.name)
    set_arg(t, "type", get_potential_type(potential).value)
    brief = format_desc(potential.brief, potential.params, level=-1, max_level=1)
    set_arg(t, "brief", brief)
    desc = format_desc(potential.desc, potential.params, level=-1, max_level=6 if potential.max_level > 1 else 1)
    assert desc is not None
    set_arg(t, "desc", desc)
    set_arg(t, "icon", potential.icon)
    set_arg(t, "shape", potential.shape)
    return str(t)


def format_potential_builds(builds: list[PotentialBuild]) -> str:
    t = Template("{{PotentialBuild\n}}")
    for index, b in enumerate(builds, 1):
        set_arg(t, f"name{index}", b.name)
        set_arg(t, f"desc{index}", b.desc)
    for index, b in enumerate(builds, 1):
        potentials = b.potentials
        potentials.sort(key=lambda p: (p.max_level, p.rarity))
        string = "\n".join(format_potential(p) for p in potentials)
        string = indent(string, prefix="  ").strip()
        set_arg(t, f"{index}", string)
    return str(t)


def upload_potential_icons():
    p = get_potentials()
    upload_requests = []
    for k, v in p.items():
        for b in v.main_builds + v.support_builds:
            for pot in b.potentials:
                upload_requests.append(UploadRequest(
                    pot.get_icon_path(),
                    pot.icon,
                    text="[[Category:Potential icons]]",
                    summary="upload potential icon")
                )
    process_uploads(upload_requests)


def main():
    upload_potential_icons()
    p = get_potentials()
    pages = get_character_pages()
    for k, v in p.items():
        page = pages[k]
        parsed = parse(page.text)
        text = """{{Tab
|group=potential
|type=buttons
|Show detailed descriptions
|Show brief descriptions
}}
<tabber>
|-|Main=""" + format_potential_builds(v.main_builds) + """
|-|Support=""" + format_potential_builds(v.support_builds) + """
</tabber>"""
        force_section_text(parsed, "Potentials", text, "Upgrade materials")
        save_page(page, str(parsed), summary="update potentials")


if __name__ == '__main__':
    main()
