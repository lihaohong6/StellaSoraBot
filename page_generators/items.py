from dataclasses import dataclass
from functools import cache
from pathlib import Path

from pywikibot import Page
from wikitextparser import Template

from utils.data_utils import autoload, assets_root
from utils.upload_utils import UploadRequest, process_uploads
from utils.wiki_utils import set_arg, s, save_page


@dataclass
class Item:
    id: int
    title: str
    desc: str
    literary: str
    type: int
    rarity: int | None
    icon: str

    def file_path(self) -> Path:
        return assets_root / (self.icon + ".png")

    def file_page(self) -> str:
        return "Icon " + self.title.lower() + ".png"


def make_item_page_template(item: Item) -> Template:
    t = Template("{{ItemData\n}}")
    set_arg(t, "id", item.id)
    set_arg(t, "name", item.title)
    set_arg(t, "icon", item.file_page())
    set_arg(t, "rarity", item.rarity)
    set_arg(t, "itemdesc", item.desc)
    return t


def make_item_template(item: Item, quantity: int) -> Template:
    t = Template("{{Item}}")
    t.set_arg("1", item.title, positional=True)
    if quantity != 1:
        t.set_arg("quantity", str(quantity))
    return t


@cache
def get_all_items() -> dict[int, Item]:
    data = autoload("Item")
    result: dict[int, Item] = {}
    for k, v in data.items():
        item_id = v['Id']
        result[item_id] = Item(
            id=item_id,
            title=v['Title'],
            desc=v['Desc'],
            literary=v['Literary'],
            type=v['Type'],
            rarity=v.get('Rarity', None),
            icon=v.get('Icon', "").lower(),
        )
    return result


def make_item_pages(ids: list[int], overwrite: bool = False) -> None:
    items = get_all_items()
    upload_requests = []
    for item_id in ids:
        item = items[item_id]
        t = make_item_page_template(item)
        text = str(t) + "\n\n" + f"'''{item.title}''' is an item in [[Stella Sora]]."
        p = Page(s, item.title)
        if not overwrite and p.exists():
            continue
        save_page(p, text, "batch create item pages")
        upload_requests.append(UploadRequest(
            item.file_path(),
            item.file_page(),
            "[[Category:Item icons]]",
            "Batch upload item icons"))
    process_uploads(upload_requests)


def main():
    make_item_pages([])


if __name__ == '__main__':
    main()
