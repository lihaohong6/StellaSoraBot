import re


NAMED_COLORS = {
    "black": "#000000",
    "white": "#ffffff",
    "red": "#ff0000",
}


def _escape_ruby_markup(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        top_text = match.group(1)
        main_text = match.group(2)
        return f"{{{{Ruby|{main_text}|{top_text}}}}}"

    return re.subn(r"<r=([^>]*)>(.*?)</r>", repl, text)[0]


def _relative_luminance(rgb: list[float]) -> float:
    def linearize(channel: float) -> float:
        channel /= 255
        return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4

    r, g, b = (linearize(channel) for channel in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _readable_color(color: str, dark_background: bool) -> str:
    color = NAMED_COLORS.get(color.lower(), color)
    if not re.fullmatch(r"#(?:[0-9A-Fa-f]{3,4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})", color):
        return color
    hex_color = color[1:]
    if len(hex_color) <= 4:
        hex_color = "".join(char * 2 for char in hex_color[:3])

    rgb = [float(int(hex_color[i:i + 2], 16)) for i in range(0, 6, 2)]
    background_luminance = _relative_luminance([0x4C, 0x74, 0xD3] if dark_background else [0xF9, 0xF9, 0xF7])
    while True:
        darker, lighter = sorted([_relative_luminance(rgb), background_luminance])
        if (lighter + 0.05) / (darker + 0.05) >= 2:
            break
        if dark_background:
            rgb = [channel + (255 - channel) * 0.05 for channel in rgb]
        else:
            rgb = [channel * 0.95 for channel in rgb]
    return "#" + "".join(f"{round(channel):02x}" for channel in rgb)


def _escape_rich_text_markup(text: str, dark_background: bool) -> str:
    parts: list[str] = []
    open_tags: list[tuple[str, str, str]] = []
    last_end = 0

    def open_tag(name: str, value: str) -> tuple[str, str, str] | None:
        if name == "color":
            return name, f'<span style="color:{_readable_color(value, dark_background)}">', "</span>"
        if name == "align":
            if value in ("right", "center"):
                return name, f'<div style="text-align:{value}">', "</div>"
            return name, "", ""
        if name in ("i", "b"):
            return name, f"<{name}>", f"</{name}>"
        return None

    tag_pattern = r'<(/?)(color|align|i|b|size|alpha|voffset|space|margin(?:-left|-right)?)(?:\s*=\s*"?([^">]*)"?)?>'
    for match in re.finditer(tag_pattern, text):
        parts.append(text[last_end:match.start()])
        last_end = match.end()
        is_close, name, value = match.group(1), match.group(2), (match.group(3) or "").strip()
        if not is_close:
            tag = open_tag(name, value)
            if tag is not None:
                open_tags.append(tag)
                parts.append(tag[1])
            continue
        matching = [index for index, tag in enumerate(open_tags) if tag[0] == name]
        if not matching:
            continue
        reopened = open_tags[matching[-1] + 1:]
        parts.extend(tag[2] for tag in reversed(open_tags[matching[-1]:]))
        parts.extend(tag[1] for tag in reopened)
        open_tags = open_tags[:matching[-1]] + reopened

    parts.append(text[last_end:])
    parts.extend(tag[2] for tag in reversed(open_tags))
    text = "".join(parts)
    while True:
        text, count = re.subn(r"<(span|div|i|b)(?: [^>]*)?></\1>", "", text)
        if count == 0:
            return text


def escape_text(text: str, dark_background: bool = False) -> str:
    text = re.subn(r"==(?:Off|A-?[\d.]+)==", "", text)[0]
    text = _escape_ruby_markup(text)
    text = _escape_rich_text_markup(text, dark_background)
    text = (text
            .replace("==RT==", "\n")
            .replace("\n", "<br/>")
            .replace("==PLAYER_NAME==", "<username>")
            .replace("==W==", "")
            .replace("==B==", "")
            .replace("==P==", ""))
    text = re.subn(r"^(?:<br/>)+", "", text)[0]
    text = re.subn(r"(?:<br/>|</[a-z]+>)*$", lambda m: m.group(0).replace("<br/>", ""), text, count=1)[0]
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
