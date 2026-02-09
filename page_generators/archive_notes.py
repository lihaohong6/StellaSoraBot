from dataclasses import dataclass

from wikitextparser import parse

from character_info.characters import get_character_pages
from utils.data_utils import autoload
from utils.wiki_utils import force_section_text, save_page


@dataclass
class ArchiveNote:
    id: int
    name: str
    story: str
    unlock: str

def get_archive_notes() -> dict[int, ArchiveNote]:
    data = autoload("StarTowerBookEventReward")
    notes: dict[int, ArchiveNote] = {}
    for k, v in data.items():
        if "???" in v['Name']:
            continue
        story_id = v['Id']
        notes[story_id] = ArchiveNote(story_id, v['Name'], v['Story'].replace("\n", "<br/>"), v['Source'])
    return notes

def update_archive_notes() -> None:
    notes = get_archive_notes()
    for char, page in get_character_pages("/story").items():
        parsed = parse(page.text)
        result = []
        for i in range(1, 4):
            note = notes.get(char.id * 100 + i, None)
            assert note is not None
            result.append("{{Collapse\n|1=" + note.name + f"\n|2=<p>'''Unlock''': {note.unlock}</p>\n\n{note.story}" + "\n}}")
        force_section_text(parsed,
                           section_title="Anecdotes",
                           text="\n\n".join(result),
                           prepend="Invitation stories")
        save_page(page, str(parsed), "update anecdotes")

if __name__ == "__main__":
    update_archive_notes()
