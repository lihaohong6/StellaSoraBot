import re


def escape_text(text: str) -> str:
    text = (text
            .replace("==RT==", "\n")
            .replace("\n", "<br/>")
            .replace("==PLAYER_NAME==", "<username>")
            .replace("==W==", ""))
    text = re.subn("~~(?=~)", "~~<nowiki/>", text)[0]
    def repl(m):
        b1, b2, b3 = (int(x) for x in m.groups())
        return bytes((b1, b2, b3)).decode('utf-8')

    text = re.subn(
        r'\\(\d{1,3})\\(\d{1,3})\\(\d{1,3})',
        repl,
        text
    )[0]
    text = text.replace("=", "{{=}}")
    return text


def main():
    raise RuntimeError("Should not be called")


if __name__ == "__main__":
    main()
