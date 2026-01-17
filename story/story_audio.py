import re
import subprocess
from functools import cache
from pathlib import Path

from character_info.audio import wav_to_ogg
from page_generators.discs import txtp_to_wav
from unpack.unpack_paths import sound_dir, bgm_wem_dir
from utils.audio_utils import wwise_fnv_hash, get_wwiser_executable_path
from utils.data_utils import audio_wav_root


@cache
def get_hash_to_txtp_mapping() -> dict[str, Path]:
    wwiser_path = get_wwiser_executable_path()
    bnk_path = sound_dir / "AVG.bnk"
    txtp_path = sound_dir / "avg_txtp"
    subprocess.run(
        [
            "python",
            wwiser_path.absolute(),
            "--txtp",
            bnk_path.absolute()
        ],
        check=True,
        cwd=sound_dir,
    )
    (sound_dir / "txtp").rename(txtp_path)
    result: dict[str, Path] = {}
    for file in txtp_path.glob("*.txtp"):
        with open(file, "r") as f:
            m = re.search(r"CAkEvent\[\d+] (\d+)", f.read())
            if m:
                result[m.group(1)] = file
    return result


def get_sound_effect_path(name: str) -> Path:
    hashed = wwise_fnv_hash(name)
    sound_effect_root = audio_wav_root / "se"
    sound_effect_root.mkdir(parents=True, exist_ok=True)
    se_ogg_root = sound_effect_root / "ogg"
    se_ogg_root.mkdir(parents=True, exist_ok=True)
    ogg_path = se_ogg_root / f"{name}.ogg"
    if not ogg_path.exists():
        wav_path = sound_effect_root / f"{name}.wav"
        if not wav_path.exists():
            txtp_path = get_hash_to_txtp_mapping()[str(hashed)]
            txtp_to_wav(txtp_path, wav_path)
        wav_to_ogg(wav_path, ogg_path)
    return ogg_path


@cache
def get_bgm_hash_to_txtp_mapping() -> dict[str, Path]:
    wwiser_path = get_wwiser_executable_path()
    bnk_path = sound_dir / "Music_AVG.bnk"

    subprocess.run(
        [
            "python",
            wwiser_path.absolute(),
            "--txtp",
            bnk_path.absolute()
        ],
        check=True,
        cwd=sound_dir,
    )
    txtp_path = sound_dir / "music_avg_txtp"
    (sound_dir / "txtp").rename(txtp_path)

    result: dict[str, Path] = {}
    for file in txtp_path.glob("*.txtp"):
        m = re.search(r"\d+=(\d+)\)", file.name)
        result[m.group(1)] = file
    return result


def get_bgm_path(name: str) -> Path:
    bgm_root = audio_wav_root / "bgm"
    bgm_root.mkdir(parents=True, exist_ok=True)
    bgm_ogg_root = bgm_root / "ogg"
    bgm_ogg_root.mkdir(parents=True, exist_ok=True)
    ogg_path = bgm_ogg_root / f"{name}.ogg"
    if not ogg_path.exists():
        wav_path = bgm_root / f"{name}.wav"
        if not wav_path.exists():
            hashed = wwise_fnv_hash(name)
            txtp_path = get_bgm_hash_to_txtp_mapping()[str(hashed)]
            txtp_to_wav(txtp_path, wav_path)
        wav_to_ogg(wav_path, ogg_path)
    return ogg_path


def main():
    pass


if __name__ == "__main__":
    main()
