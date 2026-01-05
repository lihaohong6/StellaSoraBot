import re


def escape_text(text: str) -> str:
    text = text.replace("==RT==", "\n").replace("\n", "<br/>").replace("==PLAYER_NAME==", "<username>")
    text = re.subn("~~(?=~)", "~~<nowiki/>", text)[0]
    text = (text.replace(r"\226\128\148", "—")
            .replace(r"\226\128\166", "…")
            .replace(r"\226\128\153", "’"))
    text = text.replace("=", "{{=}}")
    return text


def main():
    raise RuntimeError("Should not be called")


if __name__ == "__main__":
    main()
