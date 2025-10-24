from typing import Any

from pywikibot import Site, Page
from wikitextparser import WikiText, Template, Section

s = Site()


def find_section(wikitext: WikiText, title: str) -> Section | None:
    for sec in wikitext.sections:
        if not sec.title:
            continue
        if sec.title.strip() == title.strip():
            return sec
    return None

def force_section_text(wikitext: WikiText, section_title: str, text: str, prepend: str = None) -> bool:
    for sec in wikitext.sections:
        if not sec.title:
            continue
        if sec.title.strip() == prepend:
            sec.string = f"=={section_title}==\n" + text + "\n" + sec.string
            return True
        if sec.title.strip() == section_title:
            sec.contents = text + "\n"
            return True
    return False


def save_page(page: Page | str, text, summary: str = "update page"):
    if isinstance(page, str):
        page = Page(s, page)
    if page.text.strip() != text.strip():
        page.text = text
        page.save(summary=summary)


def set_arg(t: Template, name: str, value: Any, **kwargs):
    t.set_arg(f" {name.strip()} ", f" {value}\n", **kwargs)


def find_template_by_name(wikitext: WikiText, name: str) -> Template | None:
    for t in wikitext.templates:
        if t.name.strip() == name:
            return t
    return None
