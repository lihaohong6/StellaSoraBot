from unpack.unpack_audio import export_audio, export_disc_txtp
from unpack.unpack_dll import generate_dummy_dll
from unpack.unpack_image import export_images
from unpack.unpack_lua import export_lua
from unpack.unpack_paths import data_dir, unity_asset_dir_1, text_dir

assert data_dir.exists() and unity_asset_dir_1.exists() and text_dir.exists()


def export_all_assets():
    generate_dummy_dll()
    export_images()
    export_audio()
    export_lua()
    export_disc_txtp()


def main():
    export_all_assets()


if __name__ == "__main__":
    main()
