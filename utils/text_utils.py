import re


COLOR_LIGHTEN_AMOUNT = 0.45


def _escape_ruby_markup(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        top_text = match.group(1)
        main_text = match.group(2)
        return f"{{{{Ruby|{main_text}|{top_text}}}}}"

    return re.subn(r"<r=([^>]*)>(.*?)</r>", repl, text)[0]


def _lighten_color(color: str) -> str:
    if not color.startswith("#"):
        return color

    hex_color = color[1:]
    if len(hex_color) == 3:
        rgb = [int(char * 2, 16) for char in hex_color]
        alpha = ""
    elif len(hex_color) == 6:
        rgb = [int(hex_color[i:i + 2], 16) for i in range(0, 6, 2)]
        alpha = ""
    elif len(hex_color) == 8:
        rgb = [int(hex_color[i:i + 2], 16) for i in range(0, 6, 2)]
        alpha = hex_color[6:8]
    else:
        return color

    lightened = [
        round(channel + (255 - channel) * COLOR_LIGHTEN_AMOUNT)
        for channel in rgb
    ]
    return f"#{lightened[0]:02x}{lightened[1]:02x}{lightened[2]:02x}{alpha.lower()}"


def _escape_color_markup(text: str) -> str:
    parts: list[str] = []
    last_end = 0
    open_colors = 0

    for match in re.finditer(r"<color=(#[0-9A-Fa-f]{3,8}|[A-Za-z]+)>|</color>", text):
        parts.append(text[last_end:match.start()])
        if match.group(1) is None:
            if open_colors:
                parts.append("</span>")
                open_colors -= 1
        else:
            color = _lighten_color(match.group(1).strip())
            parts.append(f'<span style="color:{color}">')
            open_colors += 1
        last_end = match.end()

    parts.append(text[last_end:])
    parts.extend("</span>" for _ in range(open_colors))
    return "".join(parts)


def _escape_align_markup(text: str) -> str:
    parts: list[str] = []
    last_end = 0
    open_aligns = 0

    for match in re.finditer(r'<align\s*=\s*"?(right)"?>|</align>', text):
        parts.append(text[last_end:match.start()])
        if match.group(1) is None:
            if open_aligns:
                parts.append("</div>")
                open_aligns -= 1
        else:
            parts.append('<div style="text-align:right">')
            open_aligns += 1
        last_end = match.end()

    parts.append(text[last_end:])
    parts.extend("</div>" for _ in range(open_aligns))
    return "".join(parts)


def escape_text(text: str) -> str:
    text = re.subn(r"</?size(?:\s*=\s*[^>]*)?>", "", text)[0]
    text = _escape_ruby_markup(text)
    text = _escape_color_markup(text)
    text = _escape_align_markup(text)
    text = (text
            .replace("==RT==", "\n")
            .replace("\n", "<br/>")
            .replace("==PLAYER_NAME==", "<username>")
            .replace("==W==", "")
            .replace("==B==", "")
            .replace("==A-1==", "")
            .replace("==P==", ""))
    text = re.subn("~~(?=~)", "~~<nowiki/>", text)[0]
    def repl(m: re.Match[str]) -> str:
        try:
            return bytes(int(x) for x in m.groups()).decode('utf-8')
        except (ValueError, UnicodeDecodeError):
            return m.group(0)

    text = re.subn(
        r'\\(\d{1,3})\\(\d{1,3})\\(\d{1,3})',
        repl,
        text
    )[0]
    text = re.subn(
        r'\\(\d{1,3})\\(\d{1,3})',
        repl,
        text
    )[0]
    text = text.replace("=", "{{=}}")
    return text.strip()


def main():
    raise RuntimeError("Should not be called")


if __name__ == "__main__":
    main()
