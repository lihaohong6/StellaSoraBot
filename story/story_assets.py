from story.parse_story import StoryEpisode
from story.story_audio import get_bgm_path, get_sound_effect_path
from utils.data_utils import assets_root
from utils.upload_utils import UploadRequest, process_uploads


def get_front_object_file_name(image_name: str) -> str:
    return f"Story element {image_name}.png"


def export_bgm_files(episodes: dict[str, StoryEpisode]) -> None:
    bgm_files: set[str] = set()
    for episode in episodes.values():
        for row in episode.rows:
            if row.name == "bgm":
                bgm_file = row.attributes.get("file", "")
                if bgm_file:
                    bgm_files.add(bgm_file)
    upload_requests = []
    for bgm in sorted(bgm_files):
        if not bgm.startswith("m"):
            print(f"WARNING: unrecognized bgm name: {bgm}")
        try:
            path = get_bgm_path(bgm)
        except KeyError:
            print(f"WARNING: Could not find BGM asset for {bgm}")
            continue
        upload_requests.append(UploadRequest(
            path,
            f"File:Bg{bgm}.ogg",
            "[[Category:Story BGMs]]",
            'batch upload story bgms')
        )
    process_uploads(upload_requests)


def export_sound_effects(episodes: dict[str, StoryEpisode]) -> None:
    sound_effects: set[str] = set()
    for episode in episodes.values():
        for row in episode.rows:
            if row.name == "sound_effect":
                for se_file in row.attributes.get("files", "").split(","):
                    if se_file:
                        sound_effects.add(se_file)
    upload_requests = []
    for se in sorted(sound_effects):
        if not se.startswith("se"):
            continue
        if "stop" in se:
            continue
        path = get_sound_effect_path(se)
        if path is None:
            continue
        upload_requests.append(UploadRequest(
            path,
            f"File:{se}.ogg",
            "[[Category:Sound effects]]",
            'batch upload story sound effects')
        )
    process_uploads(upload_requests)


def export_front_object_files(episodes: dict[str, StoryEpisode]) -> None:
    image_names: set[str] = set()
    for episode in episodes.values():
        for row in episode.rows:
            if row.name == "front_object":
                image_name = row.attributes.get("image", "")
                if image_name:
                    image_names.add(image_name)

    upload_requests = []
    for image_name in sorted(image_names):
        path = assets_root / "icon" / "avgelement" / f"{image_name}.png"
        if not path.exists():
            print(f"WARNING: Could not find front object asset for {image_name}")
            continue
        upload_requests.append(UploadRequest(
            path,
            f"File:{get_front_object_file_name(image_name)}",
            "[[Category:Story element images]]",
            "batch upload story element images"
        ))
    process_uploads(upload_requests)


def export_story_assets(episodes: dict[str, StoryEpisode]) -> None:
    export_bgm_files(episodes)
    export_sound_effects(episodes)
    export_front_object_files(episodes)
