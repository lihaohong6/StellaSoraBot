import json
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import cache
from pathlib import Path
from typing import TypeVar, Callable

import UnityPy
from UnityPy import Environment
from UnityPy.files import ObjectReader

from unpack.unpack_paths import vendor_library_dir, unity_asset_dir_2, unity_asset_dir_1

T = TypeVar("T")


def for_each_object(f: Path, mapper: Callable[[ObjectReader, Environment], T]) -> list[T]:
    env = UnityPy.load(str(f))
    result: list[T] = []
    for obj in env.objects:
        r = mapper(obj, env)
        if r is not None:
            result.append(r)
    return result


@cache
def get_unity3d_files() -> list[Path]:
    files: dict[str, Path] = dict((f.name, f) for f in unity_asset_dir_2.rglob("*.unity3d"))
    for f in unity_asset_dir_1.rglob("*.unity3d"):
        if f.name not in files:
            files[f.name] = f
    return list(files.values())


def asset_map(files: list[Path], mapper: Callable[[ObjectReader, Environment], T], max_workers: int = 20) -> list[T]:
    print(f"Processing {len(files)} files...")
    result: list[T] = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {executor.submit(for_each_object, f, mapper): f for f in files}
        for future in as_completed(future_to_file):
            for res in future.result():
                result.append(res)
    return result


def build_fk_stella_sora(unpacker_dir: Path = vendor_library_dir / "fkStellaSora") -> Path:
    if not unpacker_dir.exists():
        subprocess.run(['git', 'clone', 'https://github.com/shiikwi/fkStellaSora'],
                       check=True,
                       cwd=vendor_library_dir)
    assert unpacker_dir.exists() and unpacker_dir.is_dir()
    subprocess.run(["git", "pull"], check=True, cwd=unpacker_dir)
    subprocess.run(['dotnet', 'build'], check=True, cwd=unpacker_dir)
    return unpacker_dir


class UnityJsonEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, bytes):
            return obj.hex()
        return super().default(obj)
