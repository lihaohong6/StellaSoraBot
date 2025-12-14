from dataclasses import dataclass
from functools import cache
from pathlib import Path

from pywikibot import Page
from wikitextparser import Template

from utils.data_utils import autoload, assets_root
from utils.upload_utils import UploadRequest, process_uploads
from utils.wiki_utils import set_arg, s, save_page, PageCreationRequest, process_page_creation_requests


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


def make_item_page_template(item: Item, category: str | None) -> Template:
    t = Template("{{ItemData\n}}")
    set_arg(t, "id", item.id)
    set_arg(t, "name", item.title)
    set_arg(t, "icon", item.file_page())
    set_arg(t, "rarity", item.rarity)
    set_arg(t, "itemdesc", item.desc + "<br/>" + item.literary)
    if category:
        set_arg(t, "category", category)
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


def make_item_pages(ids: list[int], content: str = "is an item.", overwrite: bool = False, category: str | None = None) -> None:
    items = get_all_items()
    page_save_requests = []
    upload_requests = []
    for item_id in ids:
        item = items[item_id]
        t = make_item_page_template(item, category=category)
        text = str(t) + "\n\n" + f"'''{item.title}''' {content}"
        page_save_requests.append(PageCreationRequest(
            item.title,
            text,
            "batch create item pages"
        ))
        upload_requests.append(UploadRequest(
            item.file_path(),
            item.file_page(),
            "[[Category:Item icons]]",
            "Batch upload item icons"))
    process_uploads(upload_requests)
    process_page_creation_requests(page_save_requests, overwrite=True)


def main():
    make_item_pages([])


if __name__ == '__main__':
    main()
