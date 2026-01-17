import subprocess
from functools import cache
from pathlib import Path

from unpack.unpack_paths import vendor_library_dir


def wwise_fnv_hash(string) -> int:
    string = string.lower().encode('utf-8')
    hash_value = 2166136261
    prime = 16777619
    for char in string:
        hash_value = (hash_value * prime) % (2 ** 32)
        hash_value = hash_value ^ char
    return hash_value


@cache
def get_wwiser_executable_path() -> Path:
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
    return executable_path
