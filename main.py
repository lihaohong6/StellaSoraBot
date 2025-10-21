from wikitextparser import parse

from character_info.characters import get_characters, get_character_pages


def main():
    chars = get_characters()
    pages = get_character_pages()
    for char_name, page in pages.items():
        char = chars[char_name]
        parsed = parse(page.text)
        for t in parsed.templates:
            if t.name.strip() == "TrekkerData":
                target = t
                break
        else:
            continue
        target.set_arg("birthday ", " " + char.birthday + "\n")
        page.text = str(parsed)
        page.save(summary="update birthday")


if __name__ == "__main__":
    main()