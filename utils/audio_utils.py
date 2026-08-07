from functools import cache
from pathlib import Path

import librosa
import numpy as np
import requests
from fastdtw import fastdtw
from scipy.spatial.distance import euclidean

from unpack.unpack_paths import vendor_library_dir

WWISER_VERSION = "v20250928"
WWISER_FILES = ("wwiser.pyz", "wwnames.db3")


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
    wwiser_path.mkdir(exist_ok=True, parents=True)
    for file_name in WWISER_FILES:
        target = wwiser_path / file_name
        if target.exists():
            continue
        url = f"https://github.com/bnnm/wwiser/releases/download/{WWISER_VERSION}/{file_name}"
        print(f"Downloading {url}")
        with requests.get(url, stream=True, timeout=60) as response:
            response.raise_for_status()
            # download to a temp name so an interrupted download isn't mistaken for a complete one
            partial = target.with_suffix(target.suffix + ".part")
            with open(partial, "wb") as f:
                for chunk in response.iter_content(chunk_size=1 << 16):
                    f.write(chunk)
            partial.replace(target)
    executable_path = wwiser_path / "wwiser.pyz"
    assert executable_path.exists()
    return executable_path


def _extract_mfcc(path: Path, sr: int, n_mfcc: int) -> np.ndarray:
    y, _ = librosa.load(path, sr=sr)
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=n_mfcc)
    # CMVN per coefficient
    mfcc = (mfcc - mfcc.mean(axis=1, keepdims=True)) / (mfcc.std(axis=1, keepdims=True) + 1e-8)
    return mfcc.T  # (n_frames, n_mfcc)

def compute_audio_distance(p1: Path, p2: Path, sr: int = 22050, n_mfcc: int = 13) -> float:
    m1, m2 = _extract_mfcc(p1, sr, n_mfcc), _extract_mfcc(p2, sr, n_mfcc)
    distance, path = fastdtw(m1, m2, dist=euclidean)
    return distance / len(path)  # symmetric, length-normalized
