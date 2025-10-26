import re
from dataclasses import dataclass
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
        result[w['Id']] = Word(
            w['Id'],
            w['Title'],
            '#' + w['Color'],
            w['Desc'],
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

    o, _ = re.subn(r'##([^#]+)#([^#]+)#', get_word, o)
    return o


def skill_escape_color(o: str) -> str:
    o, _ = re.subn(r'<color=(#[^>]{3,8})>([^<]+)</color>',
                   lambda m: f"{{{{color|{m.group(1)}|{m.group(2)}}}}}",
                   o)
    return o


def skill_escape(bd) -> str:
    bd = bd.replace('\v', ' ')
    bd = skill_escape_word(bd)
    bd = skill_escape_color(bd)
    bd, _ = re.subn(r"&Param(\d+)&", lambda m: "{" + m.group(1) + "}", bd)
    return bd
