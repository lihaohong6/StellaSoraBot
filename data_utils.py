import json
from functools import cache
from pathlib import Path
from typing import Any

data_root = Path("StellaSoraData")
en_root = data_root / "EN"
json_root = en_root / "bin"
strings_root = en_root / "language/en_US"

assert en_root.exists()
assert json_root.exists()
assert strings_root.exists()

def load_json(name: str) -> dict[str, Any]:
    path = json_root / f"{name}.json"
    return json.load(open(path, "r", encoding="utf-8"))

@cache
def load_json_pair(name: str) -> tuple[dict, dict]:
    return (json.load(open(json_root / f"{name}.json", "r", encoding="utf-8")),
            json.load(open(strings_root / f"{name}.json", "r", encoding="utf-8")))

@cache
def autoload(name: str) -> dict:
    data, i18n = load_json_pair(name)

    def replace_with_new_string(d: dict):
        for k, v in d.items():
            if isinstance(v, str):
                if v in i18n:
                    d[k] = i18n[v]
            elif isinstance(v, dict):
                replace_with_new_string(v)

    replace_with_new_string(data)
    return data
