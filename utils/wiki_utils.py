import dataclasses
import enum
import json
from typing import Any

from pywikibot import Site, Page
from pywikibot.pagegenerators import PreloadingGenerator
from wikitextparser import WikiText, Template, Section

s = Site()


def find_section(wikitext: WikiText, title: str) -> Section | None:
    for sec in wikitext.sections:
        if not sec.title:
            continue
        if sec.title.strip() == title.strip():
            return sec
    return None


def set_section_content(wikitext: WikiText, title: str, content: str) -> None:
    section = find_section(wikitext, title)
    assert section is not None
    section.contents = content + "\n"


def force_section_text(wikitext: WikiText, section_title: str, text: str, prepend: str = None, level: int = 2) -> bool:
    for sec in wikitext.sections:
        if not sec.title:
            continue
        if sec.title.strip() == prepend:
            heading = "=" * level
            sec.string = f"{heading}{section_title}{heading}\n" + text + "\n" + sec.string
            return True
        if sec.title.strip() == section_title:
            heading = "=" * sec.level
            sec.string = f"{heading}{section_title}{heading}\n" + text + "\n"
            return True
    return False


def save_page(page: Page | str, text, summary: str = "update page"):
    if isinstance(page, str):
        page = Page(s, page)
    if page.text.strip() != text.strip():
        page.text = text
        page.save(summary=summary)


def dump_json(obj):
    class EnhancedJSONEncoder(json.JSONEncoder):
        def default(self, o):
            if dataclasses.is_dataclass(o):
                return dataclasses.asdict(o)
            if isinstance(o, enum.Enum):
                return o.value
            return super().default(o)

    return json.dumps(obj, indent=4, cls=EnhancedJSONEncoder)


def save_json_page(page: Page | str, obj, summary: str = "update json page"):
    if isinstance(page, str):
        page = Page(s, page)

    if page.text != "":
        original_json = json.loads(page.text)
        original = dump_json(original_json)
    else:
        original = ""
    modified = dump_json(obj)
    if original != modified:
        page.text = modified
        page.save(summary=summary)


def set_arg(t: Template, name: str, value: Any, **kwargs):
    t.set_arg(f" {name.strip()} ", f" {value}\n", **kwargs)


def find_template_by_name(wikitext: WikiText, name: str) -> Template | None:
    for t in wikitext.templates:
        if t.name.strip() == name:
            return t
    return None


def find_templates_by_name(wikitext: WikiText, name: str) -> list[Template]:
    result = []
    for t in wikitext.templates:
        if t.name.strip() == name:
            result.append(t)
    return result


@dataclasses.dataclass
class PageCreationRequest:
    page: Page | str
    text: str
    summary: str


def process_page_creation_requests(request_list: list[PageCreationRequest]) -> None:
    title_to_request: dict[str, PageCreationRequest] = {}
    for r in request_list:
        if isinstance(r.page, str):
            r.page = Page(s, r.page)
        title_to_request[r.page.title()] = r
    gen = PreloadingGenerator(r.page for r in request_list)
    for page in gen:
        r = title_to_request.get(page.title(), None)
        assert r is not None
        save_page(page, r.text, r.summary)
