from pywikibot import Site, Page
from wikitextparser import WikiText

s = Site()

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
