import json
from pathlib import Path

from UnityPy import Environment
from UnityPy.files import ObjectReader

from unpack.unpack_paths import unity_asset_dir_1, unity_asset_dir_2
from unpack.unpack_utils import UnityJsonEncoder, asset_map


def image_exporter(obj: ObjectReader, _: Environment) -> None:
    if not obj.container:
        return
    if not obj.container.endswith("png"):
        return
    if "lightmap" in obj.container:
        return
    path = Path(obj.container)
    path.parent.mkdir(parents=True, exist_ok=True)
    image_exported = True
    if not path.exists():
        try:
            data = obj.read()
            data.image.save(path)
            print(f"Saved: {path}")
        except Exception as e:
            image_exported = False
            print(f"Failed to save {path}: {e}")
    json_path = Path(obj.container).with_suffix(".json")
    if not json_path.exists() and image_exported:
        try:
            data = obj.read_typetree()
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False, cls=UnityJsonEncoder)
                print(f"Written to {json_path}")
        except Exception as e:
            print(f"Failed to save {json_path}: {e}")


def export_images():
    asset_map([unity_asset_dir_1, unity_asset_dir_2], image_exporter)
