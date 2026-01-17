from pathlib import Path

data_dir = Path(
    "~/.var/app/com.usebottles.bottles/data/bottles/bottles/Stella-Sora/drive_c/YostarGames/StellaSora_EN").expanduser()
sound_dir = data_dir / "Persistent_Store/SoundBanks"
unity_asset_dir_1 = data_dir / "StellaSora_Data/StreamingAssets/InstallResource"
unity_asset_dir_2 = data_dir / "Persistent_Store/AssetBundles"
text_dir = data_dir / "Persistent_Store/AssetBundles"
bgm_wem_dir = sound_dir / "Media"
vendor_library_dir = Path("vendor")
vendor_library_dir.mkdir(exist_ok=True, parents=True)
