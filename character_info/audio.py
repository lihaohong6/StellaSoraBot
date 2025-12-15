import subprocess
from collections import defaultdict
from dataclasses import dataclass
from functools import cache
from itertools import groupby
from pathlib import Path

from pywikibot import Page
from wikitextparser import Template

from character_info.characters import Character, get_characters, get_character_pages
from utils.data_utils import autoload, load_json_from_path, en_root, jp_root, audio_wav_root, temp_dir, cn_root
from utils.upload_utils import UploadRequest, process_uploads
from utils.wiki_utils import save_page


@dataclass
class AudioLine:
    id: int
    title: str
    source: str
    transcription_jp: str
    transcription_cn: str
    translation: str
    voice_type: int
    sort_key: int = -1

    def file_name(self, lang: str):
        return f"{self.source}_{lang}"

    def file_page(self, lang: str):
        return f"{self.file_name(lang)}.ogg"


@dataclass
class CharacterAudio:
    char: Character
    lines: AudioLine


def process_transcription(original: list[str] | str) -> str:
    if type(original) is str:
        original = [original]
    return "<br/>".join(o.replace("==RT==", "") for o in original if o.strip() != "")


@cache
def get_transcriptions(source: str) -> tuple[str, str, str] | None:
    bubble_data_jp: dict = load_json_from_path(jp_root / "bubble/_jp/BubbleData.json")
    if source not in bubble_data_jp:
        return None
    bubble_data_cn: dict = load_json_from_path(cn_root / "bubble/_cn/BubbleData.json")
    bubble_data_en: dict = load_json_from_path(en_root / "bubble/_en/BubbleData.json")
    transcription_jp = process_transcription(bubble_data_jp[source]['text']['female_jp'])
    transcription_cn = process_transcription(bubble_data_cn[source]['text']['female_cn'])
    translation = process_transcription(bubble_data_en[source]['text']['female_jp'])
    return transcription_jp, transcription_cn, translation


voice_title_mapping = {
    'valentine': "Valentine's day",
    'xmas': "Christmas",
    'newyear': "New Year",
    'yostar': "Title screen",
    "yourbirth": "Player birthday",
    "birth": "Trekker birthday",
}


def append_vo_directory_data(result: dict[int, list[AudioLine]]):
    existing_sources: set[str] = set()
    for _, lst in result.items():
        for line in lst:
            existing_sources.add(line.source)
    data = autoload("VoDirectory")
    vo_types: set[str] = set()
    for k, v in data.items():
        voice_id = int(k)
        source = v['voResource']
        if source in existing_sources:
            continue
        char_id = v['characterId']
        if char_id not in result:
            continue
        voice_type = v['votype']
        title = voice_title_mapping[voice_type]
        transcription_jp, transcription_cn, translation = get_transcriptions(source)
        result[char_id].append(AudioLine(
            id=voice_id,
            title=title,
            source=source,
            transcription_jp=transcription_jp,
            transcription_cn=transcription_cn,
            translation=translation,
            voice_type=3,
            sort_key=list(voice_title_mapping.keys()).index(voice_type)
        ))


@cache
def get_audio() -> dict[int, list[AudioLine]]:
    result = get_voice_archive_data()
    append_vo_directory_data(result)
    return result


def get_voice_archive_data() -> dict[int, list[AudioLine]]:
    result: dict[int, list[AudioLine]] = {}
    data = autoload("CharacterArchiveVoice")
    for k, v in data.items():
        char_id = v['CharacterId']
        if char_id not in result:
            result[char_id] = []
        voice_type = v['ArchVoiceType']
        source = determine_audio_source(v, char_id, voice_type)
        if source is None:
            continue
        tr_jp, tr_cn, translation = get_transcriptions(source)
        result[char_id].append(AudioLine(
            id=int(k),
            title=v['Title'],
            source=source,
            transcription_jp=tr_jp,
            transcription_cn=tr_cn,
            translation=translation,
            sort_key=v['Sort'],
            voice_type=voice_type,
        ))
    return result


def determine_audio_source(v: dict, char_id: int, voice_type: int) -> str | None:
    source = v['Source']
    sort_key = v['Sort']
    s1, s2 = source.split("_")
    s2 = int(s2)
    type_strings = ['combat', 'ui']
    if voice_type == 1:
        type_strings.reverse()
    type_strings.append('')
    # posterchat 7 corresponds to discuss 1, and so on
    if s1 == "posterchat" and s2 >= 7:
        s1 = "discuss"
        s2 = s2 - 6
    sources = [
        f"vo_{char_id}_{type_string}_{s1}_{s2:03d}"
        for type_string in type_strings
    ]
    if sort_key >= 76:
        s2 = sort_key - 75
        sources.append(
            f"vo_story_{char_id}_{s2:03d}_{s1}"
        )
    sources.extend([source.lower()
                    for source in sources
                    if source.lower() != source])
    for source in sources:
        if get_transcriptions(source) is not None:
            break
    else:
        print(f"Audio: {source} not found")
        return None
    return source


def wav_to_ogg(wav_path: Path, ogg_path: Path) -> Path:
    subprocess.run(["ffmpeg", "-i", wav_path, "-c:a", "libopus", "-b:a", "128k", "-y", ogg_path],
                   check=True,
                   stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL
                   )
    return ogg_path


def upload_audio_files(char_name: str, audio_lines: list[AudioLine]) -> None:
    upload_requests = []
    ogg_dir = audio_wav_root / 'ogg'
    ogg_dir.mkdir(parents=True, exist_ok=True)
    for audio_line in audio_lines:
        for lang in ["jp", "cn"]:
            filename = f"{audio_line.source}_{lang}"
            source = audio_wav_root / f"{filename}.wav"
            if not source.exists():
                continue
            ogg_file = ogg_dir / f"{filename}.ogg"
            wav_to_ogg(source, ogg_file)
            target_page = audio_line.file_page(lang)
            upload_requests.append(UploadRequest(
                source=ogg_file,
                target=target_page,
                text=f"[[Category:{char_name} voice lines]]",
                summary="upload voice lines"
            ))
    process_uploads(upload_requests, force=True)


def get_character_audio_pages() -> dict[Character, Page]:
    return get_character_pages(suffix="/audio", must_exist=False)


def lines_to_template(lines: list[AudioLine]) -> str:
    result = []
    for line in lines:
        t = Template("{{AudioRow}}")
        t.set_arg("title", line.title)
        t.set_arg("file_jp", line.file_page("jp"))
        t.set_arg("file_cn", line.file_page("cn"))
        t.set_arg("text_jp", line.transcription_jp)
        t.set_arg("text_cn", line.transcription_cn)
        t.set_arg("trans_en", line.translation)
        result.append(str(t))
    return "\n".join(result)


def generate_audio_page():
    audio = get_audio()
    for char, page in get_character_audio_pages().items():
        if not should_process_char_audio(char.name):
            continue
        if char.id not in audio:
            continue
        lines = audio[char.id]
        upload_audio_files(char.name, lines)
        lines_by_type = defaultdict(list)
        for line in lines:
            lines_by_type[line.voice_type].append(line)
        result = ["{{TrekkerAudioTop}}",
                  "",
                  "==Daily Voice Chat==",
                  lines_to_template(lines_by_type[1]),
                  "",
                  "==Combat Voice Chat==",
                  lines_to_template(lines_by_type[2]),
                  "",
                  "==Special Voice Lines==",
                  lines_to_template(lines_by_type[3]),
                  ""
                  "{{TrekkerAudioBottom}}"]
        save_page(page, "\n".join(result), summary="update voice lines page")


def should_process_char_audio(char: str | int) -> bool:
    # Change the allow list to permit only a subset of character audio pages to be updated
    # allow_list = [get_characters()['Shia']]
    allow_list = list(get_characters().values())
    allowed_names = set(c.name for c in allow_list)
    allowed_ids = set(c.id for c in allow_list)
    if char in allowed_names:
        return True
    if char in allowed_ids:
        return True
    return False


def main():
    generate_audio_page()


if __name__ == '__main__':
    main()
