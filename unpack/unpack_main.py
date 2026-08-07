from unpack.unpack_audio import export_audio, export_disc_txtp
from unpack.unpack_event_images import export_event_images
from unpack.unpack_image import export_images
from unpack.unpack_live2d import export_live2d
from unpack.unpack_lua import export_lua
from unpack.unpack_paths import data_dir, unity_asset_dir_1, text_dir

for _required in (data_dir, unity_asset_dir_1, text_dir):
    if not _required.exists():
        raise RuntimeError(
            f"Missing game installation directory: {_required}\n"
            f"Set the STELLA_SORA_DIR environment variable to the folder containing "
            f"StellaSora_Data and Persistent_Store."
        )


def export_all_assets():
    export_images()
    export_audio()
    export_lua()
    export_disc_txtp()
    export_live2d()
    export_event_images()


def main():
    export_all_assets()


if __name__ == "__main__":
    main()
