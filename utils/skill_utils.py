import re
from dataclasses import dataclass
from enum import Enum
from functools import cache

from utils.data_utils import autoload


@dataclass
class Word:
    id: int
    name: str
    color: str
    desc: str
    icon: str


@cache
def get_words() -> dict[int, Word]:
    words = autoload("Word")
    result: dict[int, Word] = {}
    for w in words.values():
        m = re.search(r"_([^_]+)1_", w.get('TitleIcon', ""))
        if m is None:
            icon = ""
        else:
            icon = m.group(1).lower()
        desc = skill_escape(w['Desc'], escape_word=False)
        params = parse_params(w, desc)
        desc = format_desc(desc, params, level=1, max_level=1)
        result[w['Id']] = Word(
            w['Id'],
            w['Title'],
            '#' + w['Color'],
            desc,
            icon
        )
    return result


@dataclass
class Effect:
    id: int
    type1: int
    type2: int
    desc: str


@cache
def get_effects() -> list[Effect]:
    data = autoload("EffectDesc")
    result = []
    for k, v in data.items():
        result.append(Effect(v['Id'], v.get('TypeID', -1), v.get('Type2ID', -1), v['Desc']))
    return result


def skill_escape_word(o: str) -> str:
    words = get_words()

    def get_word(m: re.Match) -> str:
        word = m.group(1)
        word_id = int(m.group(2))
        if word_id in words:
            word = words[word_id]
            return "{{word|" + word.name + "|" + word.icon + "}}"
        return word

    o, _ = re.subn(r'##([^#]+)#(\d+)#', get_word, o)
    return o


def skill_escape_color(o: str) -> str:
    o, _ = re.subn(r'<color=(#[^>]{3,8})>([^<]+)</color>',
                   lambda m: f"{{{{color|{m.group(1)}|{m.group(2)}}}}}",
                   o)
    return o


def skill_escape(bd, escape_word: bool = True) -> str:
    bd = bd.replace('\v', ' ')
    if escape_word:
        bd = skill_escape_word(bd)
    bd = skill_escape_color(bd)
    bd, _ = re.subn(r"&Param(\d+)&", lambda m: "{" + m.group(1) + "}", bd)
    return bd


class SkillParamType(Enum):
    NONE = 0
    ASCENSION = 1
    ACTOR = 2
    SKILL_LEVEL = 3
    BREAKTHROUGH = 4
    NOTE = 5
    DISC_SKILL = 6
    BUILD_LEVEL = 7
    SOLDIER_LEVEL = 8


@dataclass
class SkillParam:
    param_type: SkillParamType
    values: list[str]


def get_effect_by_type(type1: int, type2: int) -> Effect:
    effects = [e for e in get_effects() if e.type1 == type1 and e.type2 == type2]
    if len(effects) == 0:
        effects = [e for e in get_effects() if e.type1 == type1]
    if len(effects) == 0:
        raise RuntimeError(f"No effect description for type {type1}/{type2}")
    return effects[0]


@cache
def get_enum_descs() -> dict[tuple[str, int], str]:
    ui_text = autoload("UIText")
    return {(v['EnumName'], v['Value']): ui_text[v['Key']]['Text']
            for v in autoload("EnumDesc").values()}


def format_number(number: float) -> str:
    number = float(f"{number:.14g}")
    if number % 1 < 0.01:
        return str(int(number))
    return f"{number:.14g}"


def format_value(value: str | int | float, show_type: str, enum_type: str) -> str:
    if show_type == "Text":
        return str(value)
    if show_type == "Enum":
        key = (enum_type, int(value))
        if key not in get_enum_descs():
            raise RuntimeError(f"{enum_type} enum has no value {value}")
        return get_enum_descs()[key]
    number = float(value)
    if show_type in {"10K", "10KPct", "10KHdPct"}:
        number /= 10000
    if show_type in {"HdPct", "10KHdPct"}:
        number *= 100
    suffix = "%" if show_type in {"Pct", "HdPct", "10KPct", "10KHdPct"} else ""
    return format_number(abs(number)) + suffix


def format_hit_damage(row: dict, level: int) -> str:
    percent = row['SkillPercentAmend'][level - 1] / 10000
    flat = row['SkillAbsAmend'][level - 1]
    parts = []
    if percent > 0:
        parts.append(format_number(percent) + "%")
    if flat > 0:
        parts.append(format_number(flat))
    return "+".join(parts)


def parse_param(param_text: str) -> SkillParam:
    segments = param_text.split(',')
    table_name, parse_type, key = segments[0], segments[1], int(segments[2])
    field = segments[3] if len(segments) > 3 else ""
    show_type = segments[4] if len(segments) > 4 else ""
    enum_type = segments[5] if len(segments) > 5 else ""
    table = autoload(table_name)
    if table is None:
        raise RuntimeError(f"no config table named {table_name}")
    row = table.get(str(key))
    if row is None:
        raise RuntimeError(f"{table_name} has no row {key}")
    param_type = SkillParamType(row.get('levelTypeData', 0))

    if parse_type == "DamageNum":
        if param_type == SkillParamType.NONE:
            return SkillParam(param_type, [format_hit_damage(row, 1)])
        levels = range(1, len(row['SkillPercentAmend']) + 1)
        return SkillParam(param_type, [format_hit_damage(row, level) for level in levels])
    if parse_type == "NoLevel":
        if field not in row:
            raise RuntimeError(f"{table_name} row {key} has no field {field}")
        return SkillParam(param_type, [format_value(row[field], show_type, enum_type)])
    if parse_type != "LevelUp":
        raise RuntimeError(f"unsupported parse type {parse_type}")

    value_table = autoload(f"{table_name}Value")
    if value_table is None:
        raise RuntimeError(f"no config table named {table_name}Value")
    values = []
    level = 0 if param_type == SkillParamType.NONE else 1
    while (value_row := value_table.get(str(key + level * 10))) is not None:
        if field not in value_row:
            raise RuntimeError(f"{table_name}Value row {key} has no field {field}")
        values.append(format_value(value_row[field], show_type, enum_type))
        if param_type == SkillParamType.NONE:
            break
        level += 1
    if not values:
        raise RuntimeError(f"{table_name}Value has no values for {key}")
    return SkillParam(param_type, values)


def parse_params(d: dict, *descs: str) -> dict[int, SkillParam]:
    params: dict[int, SkillParam] = {}
    for param_num in sorted({int(n) for desc in descs for n in re.findall(r"\{(\d+)}", desc)}):
        param_text = d.get(f"Param{param_num}")
        if param_text is None:
            print(f"ERROR: {d['Id']} references Param{param_num} but does not define it")
            continue
        try:
            params[param_num] = parse_param(param_text)
        except Exception as e:
            print(f"ERROR: could not parse Param{param_num} ({param_text}) of {d['Id']}: {e}")
    return params


def skill_level_hint(param_type: SkillParamType, original: str) -> str:
    if param_type in {SkillParamType.ASCENSION, SkillParamType.BREAKTHROUGH}:
        return "{{SkillLevelHint|" + param_type.name.lower() + "|" + original + "}}"
    return original


def format_desc(desc: str, params: dict[int, SkillParam], level: int, max_level: int = 9) -> str:
    """
    :param desc:
    :param params:
    :param level: Skill level. -1 to force all params to be joined together.
    :param max_level:
    :return:
    """
    for param_num, skill_param in params.items():
        search_string = "{" + str(param_num) + "}"
        if search_string not in desc:
            continue
        values = skill_param.values
        if level != -1 and skill_param.param_type == SkillParamType.SKILL_LEVEL:
            string = values[min(level, len(values) - 1)]
        else:
            values = values[:max_level]
            if all(values[0] == v for v in values):
                string = values[0]
            else:
                string = "/".join(values)
            string = skill_level_hint(skill_param.param_type, string)
        desc = desc.replace(search_string, string)
    return desc
