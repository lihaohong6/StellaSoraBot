from pathlib import Path

import UnityPy

data_dir = Path("~/.wine/drive_c/YostarGames/StellaSora_EN/StellaSora_Data/StreamingAssets/InstallResource").expanduser()
assert data_dir.exists()

for f in data_dir.iterdir():
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

