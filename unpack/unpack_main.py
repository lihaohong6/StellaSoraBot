import json
import shutil
import subprocess
from concurrent.futures import as_completed
from concurrent.futures.process import ProcessPoolExecutor
from pathlib import Path
from typing import Callable, TypeVar

import UnityPy
from UnityPy import Environment
from UnityPy.files import ObjectReader

from unpack.unpack_paths import data_dir, sound_dir, unity_asset_dir_1, unity_asset_dir_2, text_dir, vendor_library_dir, \
    disc_bgm_wem_dir
from utils.data_utils import audio_wav_root

assert data_dir.exists() and unity_asset_dir_1.exists() and text_dir.exists()

T = TypeVar("T")


def for_each_object(f: Path, mapper: Callable[[ObjectReader, Environment], T]) -> list[T]:
    env = UnityPy.load(str(f))
    result: list[T] = []
    for obj in env.objects:
        r = mapper(obj, env)
        if r is not None:
            result.append(r)
    return result


def asset_map(directories: list[Path], mapper: Callable[[ObjectReader, Environment], T]) -> list[T]:
    files: list[Path] = []
    for directory in directories:
        files.extend(directory.rglob("*.unity3d"))
    files = [f for f in files if f.is_file()]
    print(f"Processing {len(files)} files...")
    result: list[T] = []
    with ProcessPoolExecutor(max_workers=20) as executor:
        future_to_file = {executor.submit(for_each_object, f, mapper): f for f in files}
        for future in as_completed(future_to_file):
            for res in future.result():
                result.append(res)
    return result


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


def build_fk_stella_sora(unpacker_dir: Path = vendor_library_dir / "fkStellaSora") -> Path:
    if not unpacker_dir.exists():
        subprocess.run(['git', 'clone', 'https://github.com/shiikwi/fkStellaSora'],
                       check=True,
                       cwd=vendor_library_dir)
    assert unpacker_dir.exists() and unpacker_dir.is_dir()
    subprocess.run(["git", "pull"], check=True, cwd=unpacker_dir)
    subprocess.run(['dotnet', 'build'], check=True, cwd=unpacker_dir)
    return unpacker_dir


def export_lua():
    unpacker_dir = build_fk_stella_sora()
    lua_source = data_dir / "Persistent_Store/Scripts/lua.arcx"
    lua_source_dir = lua_source.parent / "luaUnpack"
    shutil.rmtree(lua_source_dir, ignore_errors=True)
    subprocess.run(['./ArchiveParser/bin/Debug/net8.0/ArchiveParser', lua_source],
                   check=True,
                   cwd=unpacker_dir)
    assert lua_source_dir.exists() and lua_source_dir.is_dir()
    subprocess.run(['python', 'decompile.py', lua_source_dir], check=True, cwd=unpacker_dir / "Luadec")
    lua_source_dir = lua_source_dir.parent / "luaUnpackdec"
    lua_target_dir = Path("assets") / "lua"
    if lua_target_dir.exists():
        shutil.rmtree(lua_target_dir)
    lua_source_dir.rename(lua_target_dir)


def generate_dummy_dll():
    unpacker_dir = build_fk_stella_sora()
    game_assembly = data_dir / "GameAssembly.dll"
    assert game_assembly.exists()

    global_metadata_original = data_dir / "StellaSora_Data/il2cpp_data/Metadata/global-metadata.dat"
    assert global_metadata_original.exists()
    metadata_parser_dir = unpacker_dir / "MetaDataParser/bin/Debug/net8.0"
    global_metadata_copy = metadata_parser_dir / "global-metadata.dat"
    global_metadata_copy.unlink(missing_ok=True)
    shutil.copy(global_metadata_original, global_metadata_copy)
    global_metadata = metadata_parser_dir / "global-metadata.dec.dat"
    global_metadata.unlink(missing_ok=True)
    subprocess.run(["./MetaDataParser"], check=True, cwd=metadata_parser_dir)
    assert global_metadata.exists()

    il2_cpp_dir = Path("~/Documents/Programs/Il2CppDumper/Il2CppDumper/bin/Debug/net8.0").expanduser()
    assert il2_cpp_dir.is_dir()

    subprocess.run(['./Il2CppDumper',
                    game_assembly,
                    global_metadata.absolute(),
                    Path("assets").absolute()],
                   check=False,
                   cwd=il2_cpp_dir)


class UnityJsonEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, bytes):
            return obj.hex()
        return super().default(obj)


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


def export_all_assets():
    generate_dummy_dll()
    export_images()
    export_audio()
    export_lua()
    export_disc_txtp()


def main():
    export_all_assets()


if __name__ == "__main__":
    export_all_assets()
