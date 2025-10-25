import re
from dataclasses import dataclass
from functools import cache

from utils.data_utils import autoload


@dataclass
class Word:
    id: int
    name: str
    color: str


@cache
def get_words() -> dict[int, Word]:
    words = autoload("Word")
    result: dict[int, Word] = {}
    for w in words.values():
        result[w['Id']] = Word(w['Id'], w['Title'], '#' + w['Color'])
    return result


def skill_escape_word(o: str) -> str:
    words = get_words()

    def get_word(m: re.Match) -> str:
        word = m.group(1)
        word_id = m.group(2)
        if word_id in words:
            word = words[int(word_id)]
            return "{{color|" + word.color + "|" + word.name + "}}"
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
