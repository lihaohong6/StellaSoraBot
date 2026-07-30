import re

from character_info.characters import get_characters
from utils.data_utils import autoload
from utils.wiki_utils import find_section, save_page, set_section_content

SEASON4_CHARACTER_IDS = [114, 126, 135, 140]
SEASON4_ITEM_ID = 1031

ROMAN_NUMERALS = {
    "Ⅰ": "I",
    "Ⅱ": "II",
    "Ⅲ": "III",
    "Ⅳ": "IV",
}

SEASON_ACTIVITY_IDS = {
    1: 102001,
    2: 102002,
    3: 102003,
    4: 102004,
}


def _normalize_level_name(name: str) -> str:
    for unicode_numeral, ascii_numeral in ROMAN_NUMERALS.items():
        name = name.replace(unicode_numeral, ascii_numeral)
    return name


def _character_skills_potentials_text(char_id: int) -> str | None:
    skill_data = autoload("Skill")
    potential_data = autoload("TowerDefensePotential")
    characters = get_characters()
    char = next((c for c in characters.values() if c.id == char_id), None)
    if char is None:
        return None
    skill_key = f"80{char.id}01"
    if skill_key not in skill_data:
        return None
    result: list[str] = [f"==== {char.name} ====", ";Skills"]
    for i in range(1, 3):
        value = skill_data[f"80{char.id}{i:02d}"]
        result.append(f"*'''{value['Title']}''': {value['Desc']}")
    result.append(";Potentials")
    for i in range(1, 5):
        value = potential_data[f"{char.id}01{i:02d}"]
        result.append(f"*'''{value['Name']}''': {value['PotentialDes']}")
    return "\n".join(result)


def get_season4_characters_text() -> str:
    blocks = [_character_skills_potentials_text(char_id) for char_id in SEASON4_CHARACTER_IDS]
    blocks = [b for b in blocks if b is not None]
    return "=== Season 4 ===\n\n" + "\n\n".join(blocks)


def get_season4_item_text() -> str:
    item_data = autoload("TowerDefenseItem")
    item = item_data[str(SEASON4_ITEM_ID)]
    cooldown = item.get("Cd", item.get("ChargeParam2"))
    return (
        "=== Season 4 ===\n"
        f"'''{item['Name']}'''\n\n"
        f"* {item['Des']}\n"
        f"* '''Cooldown:''' {cooldown}s"
    )


def _levels_by_season_and_tier() -> dict[int, dict[int, list[str]]]:
    level_data = autoload("TowerDefenseLevel")
    result: dict[int, dict[int, list[str]]] = {}
    for season, activity_id in SEASON_ACTIVITY_IDS.items():
        rows = [v for v in level_data.values() if v.get("activityId") == activity_id]
        rows.sort(key=lambda v: v["Id"])
        for row in rows:
            if row.get("Skip"):
                continue
            tier = row["LevelPage"]
            name = _normalize_level_name(row["LevelName"])
            result.setdefault(tier, {}).setdefault(season, []).append(name)
    return result


def get_levels_section_text() -> str:
    by_tier = _levels_by_season_and_tier()
    tier_titles = {1: "Normal", 2: "Hard"}
    parts: list[str] = []
    for tier in (1, 2):
        parts.append(f"=== {tier_titles[tier]} ===\n")
        for season in sorted(by_tier[tier]):
            parts.append(f"==== Season {season} ====")
            for name in by_tier[tier][season]:
                parts.append(f"===== {name} =====")
            parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def build_page_updates(wikitext) -> None:
    chess_pieces = find_section(wikitext, "Chess Pieces")
    assert chess_pieces is not None
    chess_pieces.contents = chess_pieces.contents.rstrip("\n") + "\n\n" + get_season4_characters_text() + "\n\n"

    special_items = find_section(wikitext, "Special Items")
    assert special_items is not None
    special_items.contents = special_items.contents.rstrip("\n") + "\n\n" + get_season4_item_text() + "\n\n"

    set_section_content(wikitext, "Levels", get_levels_section_text())


def main() -> None:
    import pywikibot
    from wikitextparser import parse

    page = pywikibot.Page(pywikibot.Site(), "Chess_Defense")
    wikitext = parse(page.text)
    build_page_updates(wikitext)
    save_page(page, str(wikitext), "add Chess Defense Season 4 content")


if __name__ == "__main__":
    main()
