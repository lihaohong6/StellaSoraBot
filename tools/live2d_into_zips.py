"""Compresses Live2D skins into zip files.
The archives are named corrsponding to their respective
characters and skins. (<character> <skin>.zip)

Inside the ZIP file, the model manifest and related files are
two layers down from the root.

live2d/base/13503_L.moc3
live2d/base/13503_base.model3.json
live2d/base/motions/...
live2d/base/textures/...
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

from utils.data_utils import assets_root
from character_info.characters import id_to_char

DEFAULT_OUT = Path("assets") / "live2d_zips"
CHARACTER_ROOT = Path(assets_root / "actor2d/character")

def create_zips(
    out: Path = DEFAULT_OUT,
    overwrite: bool = False,
) -> list[Path]:
    out = Path(out)
    
    if not CHARACTER_ROOT.exists():
        print(f"Character root does not exist, you may need to run main2 or main")
        return []

    out.mkdir(parents=True, exist_ok=True)

    created: list[Path] = []

    for skin_dir in sorted(CHARACTER_ROOT.glob("*/")):
        skin_id = skin_dir.name
        live2d_root = skin_dir / "live2d"
        if not live2d_root.exists():
            print(f"Live2D root is missing for {skin_id}")
            continue

        char_name = id_to_char(int(skin_id[:-2])).name
        zip_path = out / f"{char_name} {int(skin_id[-2:]):02d}.zip"

        # Handle collisions (e.g. two skins mapping to same name)
        if zip_path.exists() and not overwrite:
            print(f"Skipping {zip_path.name}: exists")
            continue

        files = sorted(p for p in live2d_root.rglob("*") if p.is_file())

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for file in files:
                arcname = file.relative_to(skin_dir).as_posix()
                zf.write(file, arcname)

        print(f"Created {zip_path} ({len(files)} files) from {skin_id}")
        created.append(zip_path)

    print(f"Done: {len(created)} zip(s) in {out}" if created else "No zips created")
    return created


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Zip Live2D folders into sprite-named archives.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output directory for zips")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing zips")
    return parser.parse_args()

def main() -> None:
    args = _parse_args()
    create_zips(
        out=args.out,
        overwrite=args.overwrite,
    )

if __name__ == "__main__":
    main()
