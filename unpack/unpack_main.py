import subprocess
from pathlib import Path

import UnityPy

from utils.data_utils import audio_wav_root

data_dir = Path("~/.wine/drive_c/YostarGames/StellaSora_EN").expanduser()
sound_dir = data_dir / "Persistent_Store/SoundBanks"
image_dir = data_dir / "StellaSora_Data/StreamingAssets/InstallResource"
image_dir_2 = data_dir / "Persistent_Store/AssetBundles"
text_dir = data_dir / "Persistent_Store/AssetBundles"
assert data_dir.exists() and image_dir.exists() and text_dir.exists()


def export_images():
    for f in list(image_dir_2.iterdir()):
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
                if path.name.endswith(".exr") or "lightmap" in path.name:
                    continue
                try:
                    data = obj.read()
                    data.image.save(path)
                    print(f"Saved: {path}")
                except Exception as e:
                    print(f"Failed to save {path}: {e}")


def wem_to_wav(wem_path: Path, wav_path: Path):
    subprocess.run(["vgmstream-cli", wem_path, "-o", wav_path],
                   check=True,
                   stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)


def export_audio():
    target_dir = audio_wav_root
    target_dir.mkdir(parents=True, exist_ok=True)
    for f in sound_dir.iterdir():
        if not f.is_file() or not f.name.endswith(".wem"):
            continue
        source = f
        target = target_dir / f.name.replace(".wem", ".wav")
        if not target.exists():
            wem_to_wav(source, target)


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
    export_audio()


if __name__ == "__main__":
    main()
