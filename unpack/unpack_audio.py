import subprocess
from pathlib import Path

from unpack.unpack_paths import sound_dir, unity_asset_dir_1, vendor_library_dir, disc_bgm_wem_dir
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
    wwiser_path = vendor_library_dir / "wwiser"
    if not wwiser_path.exists():
        wwiser_path.mkdir(exist_ok=True, parents=True)
        subprocess.run([
            "gh", "release", "download", "v20250928",
            "--repo", "bnnm/wwiser",
            "--pattern", "wwiser.pyz",
            "--pattern", "wwnames.db3"
        ], check=True, cwd=wwiser_path)
    assert wwiser_path.exists()
    executable_path = wwiser_path / "wwiser.pyz"
    assert executable_path.exists()
    bnk_path = sound_dir / "Music_Outfit.bnk"
    assert bnk_path.exists()
    assert disc_bgm_wem_dir.exists()
    subprocess.run(["python", executable_path.absolute(),
                    "--txtp", bnk_path.absolute()],
                   check=True, cwd=disc_bgm_wem_dir)
    subprocess.run(["fd", "-e", "txtp", "-x", "sed", "-i", "-E", r's|wem/([0-9]+)\.wem|../\1.media.wem|g'],
                   check=True, cwd=disc_bgm_wem_dir)


def main():
    export_audio()


if __name__ == "__main__":
    main()