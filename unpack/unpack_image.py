import json
from io import BytesIO
from pathlib import Path

from UnityPy import Environment
from UnityPy.enums import ClassIDType
from UnityPy.files import ObjectReader

from unpack.unpack_utils import UnityJsonEncoder, asset_map, get_unity3d_files


def image_export(obj: ObjectReader, _: Environment, type_filter: ClassIDType | None) -> None:
    if not obj.container:
        return
    if type_filter and obj.type != type_filter:
        return
    if not obj.container.endswith("png"):
        return
    exclude_patterns = ['/ui/', '/fonts/', 'lightmap', '/ui_gachacover/commonfx/']
    if any(pat in obj.container for pat in exclude_patterns):
        return
    path = Path(obj.container)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Prefer sprites over tex2d
    image_exported = export_image(obj, path, overwrite=type_filter == ClassIDType.Sprite)
    if image_exported and obj.type == ClassIDType.Sprite:
        export_image_metadata(obj, path.with_suffix(".json"))


def texture2d_export(obj: ObjectReader, env: Environment) -> None:
    image_export(obj, env, ClassIDType.Texture2D)


def sprite_export(obj: ObjectReader, env: Environment) -> None:
    image_export(obj, env, ClassIDType.Sprite)


def export_image(obj: ObjectReader, path: Path, overwrite: bool = True) -> bool:
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


def export_image_metadata(obj: ObjectReader, path: Path) -> None:
    def dump(d) -> str:
        return json.dumps(d, indent=4, ensure_ascii=False, cls=UnityJsonEncoder)

    try:
        data = dump(obj.read_typetree())
    except Exception as e:
        print(f"Failed to save {path}: {e}")
        return
    if path.exists():
        try:
            with open(path, "r") as f:
                existing = dump(json.load(f))
            if existing == data:
                return
        except Exception as e:
            pass
    with open(path, "w", encoding="utf-8") as f:
        f.write(data)
        print(f"Written to {path}")



def export_images():
    files = get_unity3d_files()
    asset_map(files, texture2d_export)
    asset_map(files, sprite_export)


if __name__ == "__main__":
    export_images()