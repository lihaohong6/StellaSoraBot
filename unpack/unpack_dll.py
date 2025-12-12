import shutil
import subprocess
from pathlib import Path

from unpack.unpack_paths import data_dir
from unpack.unpack_utils import build_fk_stella_sora


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
