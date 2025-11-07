import json
from functools import cache
from pathlib import Path
from typing import Any, Callable

data_root = Path("StellaSoraData")
jp_root = data_root / "JP"
cn_root = data_root / "CN"
en_root = data_root / "EN"
json_root = en_root / "bin"
strings_root = en_root / "language/en_US"

assets_root = Path("assets") / "assetbundles"
audio_wav_root = Path("assets/audio")

temp_dir = Path("/tmp/stellasorabot")
temp_dir.mkdir(parents=True, exist_ok=True)

assert en_root.exists()
assert json_root.exists()
assert strings_root.exists()

@cache
def load_json_from_path(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.load(open(path, "r", encoding="utf-8"))

@cache
def load_json(name: str) -> dict[str, Any]:
    path = json_root / f"{name}.json"
    return load_json_from_path(path)

@cache
def load_json_pair(name: str) -> tuple[dict, dict]:
    f1 = load_json_from_path(json_root / f"{name}.json")
    f2 = load_json_from_path(strings_root / f"{name}.json")
    return f1, f2

def string_postprocessor(string: str) -> str:
    string = string.strip()
    string = string.replace("\v", " ")
    string = string.replace("\n", "<br/>")
    return string

@cache
def autoload(name: str, postprocessor: Callable[[str], str] = string_postprocessor) -> dict:
    data, i18n = load_json_pair(name)

    def replace_with_new_string(d: dict):
        for k, v in d.items():
            if isinstance(v, str):
                if v in i18n:
                    d[k] = postprocessor(i18n[v])
            elif isinstance(v, dict):
                replace_with_new_string(v)

    if i18n:
        replace_with_new_string(data)
    return data


def data_to_dict(v: dict[str, Any], attrs: list[str]) -> dict[str, Any]:
    result = {}
    for attr in attrs:
        key = "".join(s.capitalize() for s in attr.split("_"))
        assert key in v
        result[attr] = v[key]
    return result


def main():
    out_dir = assets_root.parent / "autoload"
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in json_root.glob("*.json"):
        data = autoload(f.name.split(".")[0])
        out_file = out_dir / f.name
        with open(out_file, "w", encoding="utf-8") as f2:
            json.dump(data, f2, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    main()
