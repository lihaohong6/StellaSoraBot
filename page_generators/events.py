import json
import re
from dataclasses import dataclass, field
from functools import cache
from typing import Any

from page_generators.items import get_all_items
from utils.data_utils import autoload
from utils.wiki_utils import save_json_page


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
        if name:
            return name
    return ""


@cache
def get_all_events() -> dict[int, Event]:
    group_data = autoload("ActivityGroup")
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
    group_data = autoload("ActivityGroup")
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
    group_data = autoload("ActivityGroup")
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


def save_event_missions():
    save_json_page("Module:EventMissions/data.json", get_event_missions())


def save_event_shop():
    save_json_page("Module:EventShop/data.json", get_event_shops())


def save_events():
    save_json_page("Module:Events/data.json", get_all_events())


def main():
    save_events()
    save_event_missions()
    save_event_shop()


if __name__ == "__main__":
    main()
