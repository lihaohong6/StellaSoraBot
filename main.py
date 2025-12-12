import subprocess
from pathlib import Path

from character_info.audio import generate_audio_page
from character_info.char_advance import update_character_advancement_material
from character_info.char_images import upload_char_images
from character_info.char_infobox import update_infobox
from character_info.char_skills import upload_skill_icons, update_skills
from character_info.char_sprites import char_gallery_page
from character_info.char_story import update_character_stories
from character_info.private_message import update_private_messages
from page_generators.discs import update_disc_all
from unpack.unpack_main import export_all_assets
from utils.data_utils import autoload_all_files


def update_character_page():
    upload_char_images()
    update_infobox()
    upload_skill_icons()
    update_skills()
    update_character_advancement_material()
    update_character_stories()
    update_private_messages()
    char_gallery_page()
    generate_audio_page()


def main():
    subprocess.run(["git", "pull"], check=True, cwd=Path("./StellaSoraData"))
    autoload_all_files()
    export_all_assets()
    update_character_page()
    update_disc_all()


if __name__ == "__main__":
    main()
