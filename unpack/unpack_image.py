import json
from io import BytesIO
from pathlib import Path

from UnityPy import Environment
from UnityPy.enums import ClassIDType
from UnityPy.files import ObjectReader

from unpack.unpack_paths import unity_asset_dir_1, unity_asset_dir_2
from unpack.unpack_utils import UnityJsonEncoder, asset_map


def image_export(obj: ObjectReader, _: Environment, type_filter: ClassIDType) -> None:
    if not obj.container:
        return
    if obj.type != type_filter:
        return
    if not obj.container.endswith("png"):
        return
    if "lightmap" in obj.container:
        return
    image_exported = export_image(obj, overwrite=type_filter == ClassIDType.Texture2D)
    if image_exported and obj.type == ClassIDType.Sprite:
        export_image_metadata(obj)


def texture2d_export(obj: ObjectReader, env: Environment) -> None:
    image_export(obj, env, ClassIDType.Texture2D)


def sprite_export(obj: ObjectReader, env: Environment) -> None:
    image_export(obj, env, ClassIDType.Sprite)


def export_image(obj: ObjectReader, overwrite: bool = True) -> bool:
    path = Path(obj.container)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = obj.read()
        buffer = BytesIO()
        data.image.save(buffer, format='png')
        new_image_bytes = buffer.getvalue()
    except Exception as e:
        print(f"Failed to save {path}: {e}")
        return False
    if path.exists():
        if not overwrite:
            return True
        with open(path, "rb") as f:
            existing_image_bytes = f.read()
        if existing_image_bytes == new_image_bytes:
            # They're the same. No need for updates.
            return True
        # They're different. Writing to the file.
        pass
    with open(path, "wb") as f:
        f.write(new_image_bytes)
        print(f"Successfully saved: {path}")
    return True


def export_image_metadata(obj: ObjectReader):
    def dump(d) -> str:
        return json.dumps(d, indent=4, ensure_ascii=False, cls=UnityJsonEncoder)

    json_path = Path(obj.container).with_suffix(".json")
    try:
        data = dump(obj.read_typetree())
    except Exception as e:
        print(f"Failed to save {json_path}: {e}")
        return
    if json_path.exists():
        try:
            with open(json_path, "r") as f:
                existing = dump(json.load(f))
            if existing == data:
                return
        except Exception as e:
            pass
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(data)
        print(f"Written to {json_path}")



def export_images():
    asset_map([unity_asset_dir_1, unity_asset_dir_2], texture2d_export)
    asset_map([unity_asset_dir_1, unity_asset_dir_2], sprite_export)


if __name__ == "__main__":
    export_images()