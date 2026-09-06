"""Manifest of the models `unpack.unpack_model` exported, for Module:ModelViewer.

The .glb files themselves live in a GitHub repo served by jsDelivr; .glb cannot
be uploaded to the wiki, and the CSP allows that origin.

Clip part visibility comes from two places: the `show` lists `unpack_model`
derives from the game's context rigs (in each .anims.json), and PART_OVERRIDES
below for what no rig states.
"""

import json
import posixpath
from typing import Any

from character_info.characters import get_characters
from utils.data_utils import assets_root
from utils.wiki_utils import save_json_page

model_root = assets_root / "actor3d"

MODEL_REPO = "lihaohong6/StellaSoraModels"
# jsDelivr caches a branch for 12 hours; use a tag or sha to skip that wait.
MODEL_REPO_REF = "main"
CDN_BASE = f"https://cdn.jsdelivr.net/gh/{MODEL_REPO}@{MODEL_REPO_REF}/"

# Head of the animation dropdown; the hundreds of combat frames sort after.
FEATURED_CLIPS = [
    "Ready", "ReadyLoop", "Idle", "Standby", "Timeline", "timeline",
    "Victory", "VictoryLoop", "Walk", "Run", "Dodge", "Rush", "RushStop",
    "Attack_1", "Attack_2", "Attack_3", "Attack_4", "Attack_5",
    "Ultra_TL", "Ultra_NoTL", "HurtA1", "HurtA2", "HurtB", "Dazed", "Die",
]

# What no rig in the bundles states, by character id. `hideParts` joins the
# viewer's `optional` baseline for every clip; `clips` maps a clip name (as
# .anims.json names it) to `show`/`hide` lists of its own. Applied here rather
# than in the exporter so a tweak needs no re-export.
PART_OVERRIDES: dict[str, dict[str, Any]] = {}


def as_clip(clip: dict) -> str | dict:
    """Just the stem where the gadget can infer the name from it.

    A `show`/`hide` part rule needs the object form whatever the name, since a
    bare URL has nowhere to carry it.
    """
    stem = posixpath.basename(clip["file"]).removesuffix(".glb")
    rules = {key: clip[key] for key in ("show", "hide") if clip.get(key)}
    if not rules:
        return stem if stem == clip["name"] else {"name": clip["name"], "file": stem}
    entry: dict[str, Any] = dict(rules)
    entry["file"] = stem
    if stem != clip["name"]:
        entry["name"] = clip["name"]
    return entry


def disambiguate(clips: list[dict]) -> None:
    """Suffix repeated clip names, so the dropdown can tell them apart."""
    taken = {clip["name"] for clip in clips}
    seen: set[str] = set()
    for clip in clips:
        if clip["name"] not in seen:
            seen.add(clip["name"])
            continue
        suffix = 2
        while f"{clip['name']} ({suffix})" in taken:
            suffix += 1
        clip["name"] = f"{clip['name']} ({suffix})"
        taken.add(clip["name"])
        seen.add(clip["name"])


def clip_sort_key(name: str) -> tuple[int, str]:
    if name in FEATURED_CLIPS:
        return FEATURED_CLIPS.index(name), ""
    return len(FEATURED_CLIPS), name.lower()


def build_manifest() -> dict:
    """Every exported model and clip, grouped by character.

    An index label is `Character` or `Character: Skin`, and the prefix is the
    character's wiki page name.
    """
    index = json.loads((model_root / "index.json").read_text())
    characters = get_characters()
    grouped: dict[str, list[dict]] = {}
    for entry in index:
        name, _, skin = entry["label"].partition(": ")
        assert name in characters, f"{entry['label']} is not a character on the wiki"
        manifest = model_root / entry["file"].replace(".glb", ".anims.json")
        clips = json.loads(manifest.read_text())["clips"] if manifest.exists() else []
        override = PART_OVERRIDES.get(entry["id"], {})
        for clip in clips:
            rule = override.get("clips", {}).get(clip["name"], {})
            for key in ("show", "hide"):
                if rule.get(key):
                    clip[key] = rule[key]
        clips.sort(key=lambda clip: clip_sort_key(clip["name"]))
        disambiguate(clips)
        model = {"id": entry["id"], "label": entry["label"], "skin": skin,
                 "file": entry["file"]}
        if override.get("hideParts"):
            model["hideParts"] = override["hideParts"]
        if clips:
            model["anims"] = posixpath.dirname(clips[0]["file"]) + "/"
            model["clips"] = [as_clip(clip) for clip in clips]
        grouped.setdefault(name, []).append(model)
    return {
        "base": CDN_BASE,
        "characters": [{"name": name, "models": models}
                       for name, models in sorted(grouped.items())],
    }


def save_manifest() -> None:
    save_json_page("Module:ModelViewer/data.json", build_manifest(),
                   summary="update 3D model manifest")


if __name__ == "__main__":
    save_manifest()
