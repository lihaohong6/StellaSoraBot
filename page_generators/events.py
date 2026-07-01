import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import cache
from pathlib import Path
from typing import Any

from page_generators.items import get_all_items
from utils.data_utils import assets_root, autoload
from utils.upload_utils import UploadRequest, process_uploads
from utils.wiki_utils import PageCreationRequest, process_page_creation_requests, save_json_page

WIKI_TIMEZONE = timezone(timedelta(hours=-7))

EVENT_PAGE_TITLES = {
    10100: "Daring Adventure! The Ghost Ship Haunts the Deep/2025-10-27",
    10101: "Guild Sweet Guild (event)",
    10102: "Beyond the Dream (event)",
}

@dataclass
class ItemQty:
    item_id: int
    item_name: str
    qty: int


@dataclass
class EventMission:
    id: int
    title: str
    desc: str
    rarity: int
    complete_cond: int
    aim_num: int
    rewards: list[ItemQty]


@dataclass
class EventMissionGroup:
    id: int
    tab_type: int
    tab_text: str
    order: int
    completion_rewards: list[ItemQty]
    missions: list[EventMission]


@dataclass
class EventShopItem:
    id: int
    name: str
    desc: str
    sale_number: int
    item_id: int
    item_qty: int
    max_limit: int
    price: int


@dataclass
class EventShop:
    id: int
    currency_item_id: int
    items: list[EventShopItem]


@dataclass
class Event:
    id: int
    name: str
    start_time: str
    end_time: str
    enter_end_time: str
    desc: str


@dataclass
class EventPage:
    event: Event
    page_title: str
    image: str
    image_path: Path | None
    requirement_level: int | None


def _item_qty(items: dict, item_id: int, qty: int) -> ItemQty:
    name = items[item_id].title if item_id in items else ""
    return ItemQty(item_id=item_id, item_name=name, qty=qty)


def _event_name_from_desc(desc: str) -> str:
    lines = [line.strip() for line in desc.split("<br/>") if line.strip()]
    for line in lines:
        for pattern in (
            r"^The event:\s*(.+?)\s+has begun!?$",
            r"^The \[(.+?)] event has begun!?$",
            r"^The (.+?) event has begun!?$",
            r"^The (.+?) has begun!?$",
        ):
            match = re.match(pattern, line)
            if match:
                return match.group(1).strip()
    return ""


def _event_name_from_activities(activities: list[dict[str, Any]]) -> str:
    for activity in sorted(activities, key=lambda a: a.get("SortId", 0)):
        name = activity.get("Name", "")
        if name and name.isascii():
            return name
    return ""


@cache
def get_event_group_rows() -> dict[int, dict[str, Any]]:
    return {v["Id"]: v for v in autoload("ActivityGroup").values()}


@cache
def get_all_events() -> dict[int, Event]:
    group_data = get_event_group_rows()
    activity_data = autoload("Activity")

    activities_by_group: dict[int, list[dict[str, Any]]] = {}
    for activity in activity_data.values():
        mid_group_id = activity.get("MidGroupId")
        if mid_group_id is None:
            continue
        activities_by_group.setdefault(mid_group_id, []).append(activity)

    desc_names = {v["Id"]: _event_name_from_desc(v.get("DesText", "")) for v in group_data.values()}

    events: dict[int, Event] = {}
    for v in group_data.values():
        event_id = v["Id"]
        child_activities = activities_by_group.get(event_id, [])
        name = desc_names[event_id]
        events[event_id] = Event(
            id=event_id,
            name=name or _event_name_from_activities(child_activities),
            start_time=v["StartTime"],
            end_time=v["EndTime"],
            enter_end_time=v.get("EnterEndTime", ""),
            desc=v.get("DesText", ""),
        )

    return events


@cache
def get_all_mission_groups() -> dict[int, EventMissionGroup]:
    task_group_data = autoload("ActivityTaskGroup")
    task_data = autoload("ActivityTask")
    items = get_all_items()

    groups: dict[int, EventMissionGroup] = {}
    for v in task_group_data.values():
        completion_rewards = []
        for i in range(1, 7):
            item_id = v.get(f"Reward{i}", 0)
            qty = v.get(f"RewardQty{i}", 0)
            if item_id > 0:
                completion_rewards.append(_item_qty(items, item_id, qty))
        groups[v["Id"]] = EventMissionGroup(
            id=v["Id"],
            tab_type=v["TaskTabType"],
            tab_text=v["TabText"],
            order=v["Order"],
            completion_rewards=completion_rewards,
            missions=[],
        )

    for v in task_data.values():
        group_id = v["ActivityTaskGroupId"]
        if group_id not in groups:
            continue
        rewards = [_item_qty(items, v["Tid1"], v["Qty1"])]
        if v.get("Qty2", 0) > 0:
            rewards.append(_item_qty(items, v["Tid2"], v["Qty2"]))
        groups[group_id].missions.append(EventMission(
            id=v["Id"],
            title=v["Title"],
            desc=v["Desc"],
            rarity=v["Rarity"],
            complete_cond=v["CompleteCond"],
            aim_num=v["AimNumShow"],
            rewards=rewards,
        ))

    for group in groups.values():
        group.missions.sort(key=lambda m: m.id)

    return groups


@cache
def get_all_shops() -> dict[int, EventShop]:
    shop_data = autoload("ActivityShop")
    goods_data = autoload("ActivityGoods")

    shops: dict[int, EventShop] = {}
    for v in shop_data.values():
        shops[v["Id"]] = EventShop(
            id=v["Id"],
            currency_item_id=v["CurrencyItemId"],
            items=[],
        )

    for v in goods_data.values():
        shop_id = v["ShopId"]
        if shop_id not in shops:
            continue
        shops[shop_id].items.append(EventShopItem(
            id=v["Id"],
            name=v["Name"],
            desc=v["Desc"],
            sale_number=v["SaleNumber"],
            item_id=v["ItemId"],
            item_qty=v["ItemQuantity"],
            max_limit=v.get("MaximumLimit", 0),
            price=v["Price"],
        ))

    for shop in shops.values():
        shop.items.sort(key=lambda i: i.sale_number)

    return shops


@cache
def get_event_missions() -> dict[int, list[EventMissionGroup]]:
    group_data = get_event_group_rows()
    all_groups = get_all_mission_groups()

    # Build ActivityId → list of mission groups
    activity_to_groups: dict[int, list[EventMissionGroup]] = {}
    for group in all_groups.values():
        activity_to_groups.setdefault(group.id // 100, []).append(group)

    # Actually group by ActivityId directly
    activity_to_groups = {}
    task_group_data = autoload("ActivityTaskGroup")
    for v in task_group_data.values():
        activity_id = v["ActivityId"]
        activity_to_groups.setdefault(activity_id, []).append(all_groups[v["Id"]])

    result: dict[int, list[EventMissionGroup]] = {}
    for v in group_data.values():
        event_id = v["Id"]
        enter = json.loads(v.get("Enter", "{}"))
        if "Task" not in enter:
            continue
        task_activity_id = enter["Task"][0]
        if task_activity_id not in activity_to_groups:
            continue
        groups = sorted(activity_to_groups[task_activity_id], key=lambda g: g.order)
        result[event_id] = groups

    return result


@cache
def get_event_shops() -> dict[int, EventShop]:
    group_data = get_event_group_rows()
    shop_control_data = autoload("ActivityShopControl")
    all_shops = get_all_shops()

    result: dict[int, EventShop] = {}
    for v in group_data.values():
        event_id = v["Id"]
        enter = json.loads(v.get("Enter", "{}"))
        if "Store" not in enter:
            continue
        store_activity_id = str(enter["Store"][0])
        if store_activity_id not in shop_control_data:
            continue
        shop_ids = shop_control_data[store_activity_id]["ShopIds"]
        if not shop_ids:
            continue
        shop_id = shop_ids[0]
        if shop_id not in all_shops:
            continue
        result[event_id] = all_shops[shop_id]

    return result


def _event_start_dt(event: Event) -> datetime:
    start = datetime.fromisoformat(event.start_time).astimezone(WIKI_TIMEZONE)
    row = get_event_group_rows()[event.id]
    if row.get("ActivityGroupType") in (1, 2):
        start -= timedelta(hours=8)
    return start


def _event_end_dt(event: Event) -> datetime:
    end = datetime.fromisoformat(event.end_time)
    if end.second == 0 and end.microsecond == 0:
        end -= timedelta(minutes=1)
    return end.astimezone(WIKI_TIMEZONE)


def _wiki_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _wiki_time(dt: datetime) -> str:
    if dt.second:
        return dt.strftime("%H:%M:%S")
    return dt.strftime("%H:%M")


def _wiki_timestamp(dt: datetime) -> str:
    if dt.second:
        return dt.strftime("%Y-%m-%dT%H:%M:%S-07:00")
    return dt.strftime("%Y-%m-%dT%H:%M-07:00")


def _time_template(dt: datetime) -> str:
    text = f"{_wiki_date(dt)} {_wiki_time(dt)} UTC\u20137"
    return (
        "{{Time|"
        f"{text}|date={_wiki_date(dt)}|time={_wiki_time(dt)}|timezone=-07:00"
        "}}"
    )


def _period_text(event: Event) -> str:
    start = _event_start_dt(event)
    end = _event_end_dt(event)
    return (
        f"{_time_template(start)} \u2014 {_time_template(end)} "
        f"({{{{Countdown|start-time={_wiki_timestamp(start)}|end-time={_wiki_timestamp(end)}}}}})."
    )


def _event_page_title(event: Event, duplicate_names: set[str]) -> str:
    if event.id in EVENT_PAGE_TITLES:
        return EVENT_PAGE_TITLES[event.id]
    if event.name in duplicate_names:
        return f"{event.name}/{_wiki_date(_event_start_dt(event))}"
    return event.name


def _event_image_name(event: Event) -> str:
    return f"{event.name} BG.png"


def _asset_path_from_res(res: str) -> Path | None:
    if not res:
        return None
    parts = res.split("/")
    candidates = [
        assets_root.joinpath(*(p.lower() for p in parts[:-1]), parts[-1] + ".png"),
        assets_root.joinpath(*(p.lower() for p in parts)).with_suffix(".png"),
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _event_requirement_level(row: dict[str, Any]) -> int | None:
    if row.get("StartCondType") != 71:
        return None
    params = row.get("StartCondParams", [])
    if not params:
        return None
    return int(params[0])


def _is_major_event_row(row: dict[str, Any]) -> bool:
    return row.get("ActivityGroupType") in (1, 2)


def _build_event_page_text(page: EventPage) -> str:
    event = page.event
    start = _event_start_dt(event)
    end = _event_end_dt(event)
    title_arg = f"| title = {event.name}\n" if "/" not in page.page_title and page.page_title != event.name else ""
    requirements = ""
    if page.requirement_level is not None:
        requirements = f"* [[Authorization Level]] {page.requirement_level}"
    gallery = f"<gallery>\nFile:{page.image}\n</gallery>" if page.image else ""
    return f"""{{{{EventData
{title_arg}| image = {page.image}
| type = 
| start = {_wiki_date(start)}
| end = {_wiki_date(end)}
}}}}
'''{event.name}''' is an event in ''[[Stella Sora]]''.

== Details ==

== Story ==

== Period ==
{_period_text(event)}

== Missions ==
{{{{EventMissions|id={event.id}}}}}

== Shop ==
{{{{EventShop|id={event.id}}}}}

== Requirements ==
{requirements}

== Gallery ==
=== Images ===
{gallery}

=== Videos ===
"""


def build_event_pages() -> dict[str, str]:
    pages = {}
    for page in get_event_pages().values():
        pages[page.page_title] = _build_event_page_text(page)
    return pages


@cache
def get_event_pages() -> dict[int, EventPage]:
    events = get_all_events()
    rows = get_event_group_rows()
    first_event_ids_by_name: dict[str, int] = {}
    for event in sorted(events.values(), key=_event_start_dt):
        row = rows[event.id]
        if event.name and _is_major_event_row(row) and event.name not in first_event_ids_by_name:
            first_event_ids_by_name[event.name] = event.id

    pages: dict[int, EventPage] = {}
    for event in events.values():
        row = rows[event.id]
        if not _is_major_event_row(row):
            continue
        if first_event_ids_by_name.get(event.name) != event.id:
            continue
        pages[event.id] = EventPage(
            event=event,
            page_title=_event_page_title(event, set()),
            image=_event_image_name(event),
            image_path=None,
            requirement_level=_event_requirement_level(row),
        )
    return pages


def save_event_missions() -> None:
    save_json_page("Module:EventMissions/data.json", get_event_missions())


def save_event_pages(overwrite: bool = False) -> None:
    requests = [
        PageCreationRequest(page.page_title, _build_event_page_text(page), "batch create event pages")
        for page in get_event_pages().values()
    ]
    process_page_creation_requests(requests, overwrite=overwrite)


def save_event_shop() -> None:
    save_json_page("Module:EventShop/data.json", get_event_shops())


def save_events() -> None:
    save_json_page("Module:Events/data.json", get_all_events())


def save_event_all() -> None:
    save_events()
    save_event_missions()
    save_event_shop()
    save_event_pages(overwrite=False)


def main() -> None:
    save_event_all()


if __name__ == "__main__":
    main()
