from pathlib import Path

import UnityPy

data_dir = Path("~/.wine/drive_c/YostarGames/StellaSora_EN").expanduser()
image_dir = data_dir / "StellaSora_Data/StreamingAssets/InstallResource"
text_dir = data_dir / "Persistent_Store/AssetBundles"
assert data_dir.exists() and image_dir.exists() and text_dir.exists()


def export_images():
    for f in image_dir.iterdir():
        if not f.is_file():
            continue
        if not f.name.endswith("unity3d"):
            continue
        env = UnityPy.load(str(f))

        for obj in env.objects:
            if obj.type.name == "Texture2D":
                # export texture
                if not obj.container:
                    continue
                path = Path(obj.container)
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    continue
                try:
                    data = obj.read()
                    data.image.save(path)
                    print(f"Saved: {path}")
                except Exception as e:
                    print(f"Failed to save {path}: {e}")


def export_text():
    for f in text_dir.iterdir():
        if not f.is_file():
            continue
        if not f.name.endswith("unity3d"):
            continue
        env = UnityPy.load(str(f))
        for obj in env.objects:
            if obj.type.name != "TextAsset":
                continue
            if not obj.container:
                continue
            path = Path(obj.container)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                continue
            try:
                data = obj.read()
                with open(path, "wb") as f2:
                    f2.write(data.m_Script.encode("utf-8", "surrogateescape"))
                print(f"Saved: {path}")
            except Exception as e:
                print(f"Failed to save {path}: {e}")


def main():
    export_images()


if __name__ == "__main__":
    main()