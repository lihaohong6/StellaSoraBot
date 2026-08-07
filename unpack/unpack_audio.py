import re
import subprocess
import sys
from pathlib import Path

from unpack.unpack_paths import sound_dir, unity_asset_dir_1, bgm_wem_dir
from utils.audio_utils import get_wwiser_executable_path
from utils.data_utils import audio_wav_root


def wem_to_wav(wem_path: Path, wav_path: Path):
    subprocess.run(["vgmstream-cli", wem_path, "-o", wav_path],
                   check=True,
                   stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)


def export_audio():
    target_dir = audio_wav_root
    target_dir.mkdir(parents=True, exist_ok=True)
    for f in (list(sound_dir.rglob("*.wem")) +
              list(unity_asset_dir_1.glob("*.wem"))):
        if not f.is_file() or not f.name.endswith(".wem"):
            continue
        source = f
        target = target_dir / f.with_suffix(".wav").name
        if not target.exists():
            wem_to_wav(source, target)
            print(target.name, "saved")


def export_disc_txtp():
    executable_path = get_wwiser_executable_path()
    bnk_path = sound_dir / "Music_Outfit.bnk"
    assert bnk_path.exists()
    assert bgm_wem_dir.exists()
    subprocess.run([sys.executable, executable_path.absolute(),
                    "--txtp", bnk_path.absolute()],
                   check=True, cwd=bgm_wem_dir)
    for txtp in bgm_wem_dir.rglob("*.txtp"):
        text = txtp.read_text(encoding="utf-8")
        text = re.sub(r"wem/([0-9]+)\.wem", r"../\1.media.wem", text)
        text = text.replace("wem/Music_Outfit.bnk", "../../Music_Outfit.bnk")
        txtp.write_text(text, encoding="utf-8")


def main():
    export_audio()
    export_disc_txtp()


if __name__ == "__main__":
    main()