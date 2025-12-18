import shutil
import subprocess
from pathlib import Path

from unpack.unpack_paths import data_dir
from unpack.unpack_utils import build_fk_stella_sora


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


if __name__ == "__main__":
    export_lua()