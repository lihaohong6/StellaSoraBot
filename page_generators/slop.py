import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from character_info.char_story import get_affinity_archives
from page_generators.discs import get_discs


@dataclass
class SlopFile:
    text: str
    ref: str


def get_all_prompt_data() -> list[SlopFile]:
    result: list[SlopFile] = []
    for char_name, archives in get_affinity_archives().items():
        for archive in archives:
            result.append(
                SlopFile(archive.content, f"[[{char_name}/story#{archive.title}|{archive.title}]] from {char_name}'s stories"))
    for _, disc in get_discs().items():
        result.append(SlopFile(disc.story, f"Disc story of [[{disc.name}#Story|{disc.name}]]"))
    return result


def get_matching_prompt_data(f: str | Callable[[str], bool]) -> list[SlopFile]:
    if isinstance(f, str):
        text = str(f)
        f = lambda x: text in x
    matches = []
    for data in get_all_prompt_data():
        if f(data.text):
            matches.append(data)
    return matches


def write_prompt_data(prompts: list[SlopFile]) -> None:
    output_path = Path("~/Downloads/temp/prompt").expanduser()
    shutil.rmtree(output_path, ignore_errors=True)
    output_path.mkdir(parents=True, exist_ok=True)
    for index, data in enumerate(prompts, 1):
        with open(output_path / f"Story_{index}.txt", "w", encoding="utf-8") as f:
            f.write(data.ref + "\n\n" + data.text)


def main():
    data = get_matching_prompt_data("Nazuka")
    data.insert(0, SlopFile(
        "The story of Stella Sora occurs on the Nova Continent. People known as Trekkers climb Monoliths, large"
        "structures with lots of monster known as Stellaroids. As their reward, Trekkers can make wishes to the"
        "Monolith. They lost a piece of memory in exchange for an item from the Monolith.",
        "There is no need to cite this file. Everything contained here is treated as common sense."
    ))
    write_prompt_data(data)


if __name__ == "__main__":
    main()