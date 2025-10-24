import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from pywikibot import Page
from pywikibot.pagegenerators import PreloadingGenerator
from wikitextparser import parse

from utils.data_utils import autoload, load_json, assets_root
from utils.upload_utils import UploadRequest, process_uploads
from utils.wiki_utils import s, find_template_by_name, set_arg, save_page, find_section


@dataclass
class Disc:
    id: int
    name: str = None
    rarity: int = 0
    lines_short: str = None
    story: str = None
    disc_bg: str = None

    @property
    def image_path(self) -> Path:
        return assets_root / "disc" / self.disc_bg / f"{self.disc_bg}_b.png"

    @property
    def icon_path(self) -> Path:
        return assets_root / "icon" / "outfit" / f"outfit_{self.disc_bg}_b.png"

    @property
    def image_file(self) -> str:
        return f"Disc {self.name}.png"

    @property
    def icon_file(self) -> str:
        return f"Disc icon {self.name}.png"


@cache
def get_disks() -> dict[int, Disc]:
    data = load_json("Disc")
    items = autoload("Item")
    disc_ips = autoload("DiscIP")
    result: dict[int, Disc] = {}
    for k, v in data.items():
        disc = Disc(id=int(k))
        item = items[k]
        disc_ip = disc_ips[k]
        disc.name = item["Title"]
        if disc.name == "???":
            continue
        disc.lines_short = item['Literary']
        disc.rarity = 6 - item['Rarity']
        disc.story = disc_ip['StoryDesc']
        disc.disc_bg = v['DiscBg'].split("/")[-1]
        result[int(k)] = disc
    return result


def upload_disc_images():
    disks = get_disks()
    upload_requests = []
    for disc in disks.values():
        upload_requests.append(UploadRequest(disc.image_path, disc.image_file, "[[Category:Disc images]]"))
        upload_requests.append(UploadRequest(disc.icon_path, disc.icon_file, "[[Category:Disc icons]]"))
    process_uploads(upload_requests)


def get_disc_pages() -> list[tuple[Disc, Page]]:
    discs = get_disks()
    name_to_disc = dict((d.name, d) for d in discs.values())
    pages = PreloadingGenerator([Page(s, d.name) for d in discs.values()])
    result = []
    for p in pages:
        result.append((name_to_disc[p.title()], p))
    return result


def save_disc_infobox():
    for disc, p in get_disc_pages():
        parsed = parse(p.text)
        t = find_template_by_name(parsed, "DiscData")
        assert t is not None
        set_arg(t, "rarity", disc.rarity)
        set_arg(t, "image_artwork", disc.image_file)
        set_arg(t, "image_icon", disc.icon_file)
        text = str(parsed)
        text = re.sub(r"\d-star", f"{disc.rarity}-star", text)
        save_page(p, text, "update infobox")


def save_disc_story():
    for disc, p in get_disc_pages():
        parsed = parse(p.text)
        section = find_section(parsed, "Story")
        assert section is not None
        section.contents = f"""
===Lines===
{disc.lines_short}
===Full story===
{disc.story}

"""
        save_page(p, str(parsed), "update disc story")


def create_disc_pages():
    for disc, p in get_disc_pages():
        if p.exists():
            continue
        p.text = f"""{{{{DiscData
}}}}
'''{disc.name}''' is a {disc.rarity}-star Disc in Stella Sora.

==Melody Skill==

==Harmony Skill==

==Acquisition==

==Story==

==See also==
{{{{DiscsList}}}}"""
        p.save(summary="batch create disc pages")

def main():
    save_disc_story()

if __name__ == '__main__':
    main()