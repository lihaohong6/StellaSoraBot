from wikitextparser import parse

from character_info.characters import get_characters, get_character_pages
from utils.wiki_utils import find_template_by_name, save_page

def update_infobox():
    auto_link = ["Lucky Oasis"]
    chars = get_characters()
    pages = get_character_pages()
    for char_name, page in pages.items():
        char = chars[char_name]
        parsed = parse(page.text)
        target = find_template_by_name(parsed, "TrekkerData")
        if not target:
            continue
        pairs = [
            ("birthday", char.birthday),
            ("affiliation", char.affiliation),
            ("skills", char.skills),
            ("address", char.address),
            ("experience", char.experience),
            ("weapon", char.weapon),
            ("rate", char.rate),
        ]
        for arg, value in pairs:
            for link in auto_link:
                value = value.replace(link, f"[[{link}]]")
            target.set_arg(f" {arg} ", f" {value}\n")
        save_page(page, str(parsed), "update infobox")


def main():
    update_infobox()


if __name__ == "__main__":
    main()
