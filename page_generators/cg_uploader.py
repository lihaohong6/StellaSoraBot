from utils.data_utils import assets_root
from utils.upload_utils import UploadRequest, process_uploads


def upload_cgs():
    p = assets_root / "imageavg" / "avgcg"
    images = p.glob("*.png")
    image_categories = [
        ("story_event", "Event story CGs"),
        ("story_main", "Main story CGs"),
        ("story_tales", "Side story CGs"),
    ]
    upload_requests = []
    for f in images:
        for search_keyword, category in image_categories:
            if search_keyword not in f.name:
                continue
            upload_requests.append(UploadRequest(
                f,
                "File:" + f.name,
                f"[[Category:{category}]]",
                "batch upload cutscenes"))
            break
    process_uploads(upload_requests)


def upload_background_images():
    p = assets_root / "imageavg" / "avgbg"
    images = p.glob("*.png")
    upload_requests = []
    for f in images:
        upload_requests.append(UploadRequest(
            f,
            "File:BG_" + f.name,
            f"[[Category:Background images]]",
            "batch upload story background images"
        ))
    process_uploads(upload_requests)


def main():
    upload_cgs()
    upload_background_images()


if __name__ == "__main__":
    main()