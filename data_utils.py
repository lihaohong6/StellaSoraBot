import json
from functools import cache
from pathlib import Path

data_root = Path("StellaSoraData")
en_root = data_root / "EN"
json_root = en_root / "bin"
strings_root = en_root / "language/en_US"

assert en_root.exists()
assert json_root.exists()
assert strings_root.exists()

@cache
def load_json(name: str) -> tuple[dict, dict]:
    return json.load(open(json_root / f"{name}.json")), json.load(open(strings_root / f"{name}.json"))
