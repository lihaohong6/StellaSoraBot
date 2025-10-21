from dataclasses import dataclass

from data_utils import autoload

@dataclass
class ArchiveNote:
    id: int
    name: str
    story: str
    unlock: str

def main():
    data = autoload("StarTowerBookEventReward")
    notes: list[ArchiveNote] = []
    for k, v in data.items():
        if "???" in v['Name']:
            continue
        notes.append(ArchiveNote(v['Id'], v['Name'], v['Story'].replace("\n", "<br/>"), v['Source']))
    for note in notes:
        print("{{ArchiveNote\n"
              f"|name={note.name}\n"
              f"|story={note.story}\n"
              f"|unlock={note.unlock}\n"
              "}}")

if __name__ == "__main__":
    main()