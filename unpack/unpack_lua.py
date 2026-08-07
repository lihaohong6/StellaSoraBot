import shutil
import subprocess
import sys
from pathlib import Path

from unpack.unpack_paths import data_dir
from unpack.unpack_utils import build_fk_stella_sora, native_exe


def export_lua():
    unpacker_dir = build_fk_stella_sora()
    lua_source = data_dir / "Persistent_Store/Scripts/lua.arcx"
    lua_source_dir = lua_source.parent / "luaUnpack"
    shutil.rmtree(lua_source_dir, ignore_errors=True)
    archive_parser = native_exe(unpacker_dir / "ArchiveParser/bin/Debug/net8.0/ArchiveParser")
    subprocess.run([archive_parser.absolute(), lua_source],
                   check=True,
                   cwd=unpacker_dir)
    assert lua_source_dir.exists() and lua_source_dir.is_dir()
    subprocess.run([sys.executable, 'decompile.py', lua_source_dir], check=True, cwd=unpacker_dir / "Luadec")
    lua_source_dir = lua_source_dir.parent / "luaUnpackdec"
    lua_target_dir = Path("assets") / "lua"
    if lua_target_dir.exists():
        shutil.rmtree(lua_target_dir)
    shutil.move(lua_source_dir, lua_target_dir)


if __name__ == "__main__":
    export_lua()