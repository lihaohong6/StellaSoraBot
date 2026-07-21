from character_info.char_sprites import char_gallery_page
from page_generators.cg_uploader import cg_uploader_main
from unpack.unpack_main import export_all_assets


def main():
    export_all_assets()
    char_gallery_page()
    cg_uploader_main()


if __name__ == "__main__":
    main()