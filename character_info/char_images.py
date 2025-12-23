from character_info.characters import get_characters
from utils.data_utils import assets_root
from utils.upload_utils import UploadRequest, process_uploads


def upload_char_images():
    chars = get_characters()
    req = []
    for char in chars.values():
        head_root = assets_root / "icon" / "head"

        path = head_root / f"head_{char.id}01_xxl.png"
        page = f"{char.name}-head-xxl.png"
        req.append(UploadRequest(path, page, ""))

        path = head_root / f"head_{char.id}01_xl.png"
        page = f"{char.name}.png"
        req.append(UploadRequest(path, page, ""))

        path = head_root / f"head_{char.id}01_s.png"
        page = f"{char.name}-head-s.png"
        req.append(UploadRequest(path, page, ""))

        path = assets_root / "actor2d/character" / f"{char.id}01/{char.id}01_cg.png"
        page = f"{char.name}_Memory_Snapshot.png"
        req.append(UploadRequest(path, page, ""))
    process_uploads(req)


def main():
    upload_char_images()


if __name__ == "__main__":
    main()
