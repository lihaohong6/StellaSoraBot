import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from functools import cache
from itertools import groupby
from pathlib import Path

from pywikibot import Page
from pywikibot.pagegenerators import PreloadingGenerator
from wikitextparser import Template

from character_info.characters import Character, get_characters, get_character_pages
from utils.data_utils import autoload, load_json_from_path, en_root, jp_root, audio_wav_root, temp_dir, cn_root, string_postprocessor
from utils.upload_utils import UploadRequest, process_uploads
from utils.wiki_utils import save_page, s


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

login_npc_event_title = {
    'Xmas25': "Christmas 2025",
    'NewYear26': "New Year 2026",
    'Valentine26': "Valentine's Day 2026",
    'ChineseNewYear26': "Chinese New Year 2026",
    'HalfAnniversary': "Half Anniversary",
}

npc_voice_title_mapping = {
    'greet_npc': "Greeting",
    'greetmorn_npc': "Morning",
    'greetnoon_npc': "Afternoon",
    'greetnight_npc': "Night",
    'posterchat_npc': "Conversation",
    'hfc_npc': "Favorability Cap",
    'hang_npc': "Hanging Out",
    'exhang_npc': "Farewell",
    'clear': "Area Clear",
    'twin_greet': "Twin Greeting",
    'thank_npc': "Thank You",
    'thankLvup': "Level Up",
    'thanksp': "Special Thank You",
    'limited': "Limited",
    'onsale': "On Sale",
    'Tower_typeA': "Tower_typeA",
    'Tower_typeB': "Tower_typeB",
    'Tower_typeC': "Tower_typeC",
    'final': "final",
    'leave': "leave",
    'TrekkerVersus_clear1': "TrekkerVersus_clear1",
    'TrekkerVersus_clear2': "TrekkerVersus_clear2",
    'TrekkerVersus_clear3': "TrekkerVersus_clear3",
    'TrekkerVersus_clear4': "TrekkerVersus_clear4",
    'TrekkerVersus_clear5': "TrekkerVersus_clear5",
    'TrekkerVersus_defeat': "TrekkerVersus_defeat",
    'TrekkerVersus_difficulty1': "TrekkerVersus_difficulty1",
    'TrekkerVersus_difficulty2': "TrekkerVersus_difficulty2",
    'TrekkerVersus_difficulty3': "TrekkerVersus_difficulty3",
    'TrekkerVersus_difficulty4': "TrekkerVersus_difficulty4",
    'TrekkerVersus_difficulty5': "TrekkerVersus_difficulty5",
    'TrekkerVersus_fail': "TrekkerVersus_fail",
    'TrekkerVersus_largeG': "TrekkerVersus_largeG",
    'TrekkerVersus_normalG': "TrekkerVersus_normalG",
    'TrekkerVersus_smallG': "TrekkerVersus_smallG",
    'TrekkerVersus_victory': "TrekkerVersus_victory",
}

star_tower_type_mapping = {
    'event_lv1': 'event_lv1',
    'event_lv2': 'event_lv2',
    'event_lv3': 'event_lv3',
    'chat_lv1': 'chat_lv1',
    'chat_lv2': 'chat_lv2',
    'chat_lv3': 'chat_lv3',
}


def append_vo_directory_data(result: dict[int, list[AudioLine]]):
    existing_sources: set[str] = set()
    for _, lst in result.items():
        for line in lst:
            existing_sources.add(line.source)
    data = autoload("VoDirectory")
    for k, v in data.items():
        voice_id = int(k)
        source = v['voResource']
        if source in existing_sources:
            continue
        voice_type = v['votype']

        if voice_type.startswith('login_npc_day'):
            # Event login voice lines
            m = re.match(r'vo_LoginNpc(\d+)_(.+)_day\d+', source)
            if m is None:
                continue
            char_id = int(m.group(1))
            event = m.group(2)
            if event not in login_npc_event_title:
                print(f"Audio: unknown login NPC event {event!r} in {source}")
                continue
            title = login_npc_event_title[event]
            sort_key = len(voice_title_mapping)
        else:
            char_id = v['characterId']
            if voice_type not in voice_title_mapping:
                continue
            title = voice_title_mapping[voice_type]
            sort_key = list(voice_title_mapping.keys()).index(voice_type)

        if char_id not in result:
            continue
        transcriptions = get_transcriptions(source)
        if transcriptions is None:
            continue
        transcription_jp, transcription_cn, translation = transcriptions
        result[char_id].append(AudioLine(
            id=voice_id,
            title=title,
            source=source,
            transcription_jp=transcription_jp,
            transcription_cn=transcription_cn,
            translation=translation,
            voice_type=3,
            sort_key=sort_key,
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
            if not ogg_file.exists():
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


@cache
def get_npc_id_to_name() -> dict[int, str]:
    data = autoload("NPCConfig")
    result = {}
    for v in data.values():
        npc_id = v['Id']
        if npc_id >= 9000:
            result[npc_id] = v['Name']
    return result


@cache
def get_star_tower_transcriptions() -> dict[str, tuple[str, str, str]]:
    jp_bin = load_json_from_path(jp_root / "bin/StarTowerTalk.json")
    jp_lang = load_json_from_path(jp_root / "language/ja_JP/StarTowerTalk.json")
    cn_bin = load_json_from_path(cn_root / "bin/StarTowerTalk.json")
    cn_lang = load_json_from_path(cn_root / "language/zh_CN/StarTowerTalk.json")
    en_data = autoload("StarTowerTalk")
    result = {}
    for k, v in en_data.items():
        source = v['Voice']
        jp_text = string_postprocessor(jp_lang.get(jp_bin[k]['Content'], jp_bin[k]['Content']).replace('\r', ''))
        cn_text = string_postprocessor(cn_lang.get(cn_bin[k]['Content'], cn_bin[k]['Content']).replace('\r', ''))
        result[source] = (jp_text, cn_text, v['Content'])
    return result


def append_star_tower_data(result: dict[str, list[AudioLine]]):
    npc_id_to_name = get_npc_id_to_name()
    transcriptions = get_star_tower_transcriptions()
    en_data = autoload("StarTowerTalk")
    for k, v in en_data.items():
        source = v['Voice']
        npc_id = v['NPCId']
        if npc_id not in npc_id_to_name:
            continue
        npc_name = npc_id_to_name[npc_id]
        if npc_name not in result:
            continue
        parts = source.split('_')
        type_key = f"{parts[2]}_{parts[3]}"
        if type_key not in star_tower_type_mapping:
            print(f"Audio: unknown StarTowerTalk type {type_key!r} in {source}")
            continue
        jp_text, cn_text, en_text = transcriptions[source]
        result[npc_name].append(AudioLine(
            id=v['Id'],
            title=star_tower_type_mapping[type_key],
            source=source,
            transcription_jp=jp_text,
            transcription_cn=cn_text,
            translation=en_text,
            voice_type=1,
            sort_key=v['Id'],
        ))


@cache
def get_npc_audio() -> dict[str, list[AudioLine]]:
    npc_id_to_name = get_npc_id_to_name()
    result: dict[str, list[AudioLine]] = {name: [] for name in npc_id_to_name.values()}
    data = autoload("VoDirectory")
    for k, v in data.items():
        char_id = v['characterId']
        votype = v['votype']
        source = v['voResource']
        if votype.startswith('login_npc'):
            continue
        base_id = char_id // 100 if char_id >= 100000 else char_id
        if base_id not in npc_id_to_name:
            continue
        if votype not in npc_voice_title_mapping:
            continue
        transcriptions = get_transcriptions(source)
        if transcriptions is None:
            continue
        tr_jp, tr_cn, translation = transcriptions
        npc_name = npc_id_to_name[base_id]
        sort_key = list(npc_voice_title_mapping.keys()).index(votype)
        result[npc_name].append(AudioLine(
            id=int(k),
            title=npc_voice_title_mapping[votype],
            # Fix missing vo_npc173_twin_greet_002_EX
            source=source.replace("_EX", ""),
            transcription_jp=tr_jp,
            transcription_cn=tr_cn,
            translation=translation,
            voice_type=1,
            sort_key=sort_key,
        ))
    append_star_tower_data(result)
    return {name: sorted(lines, key=lambda l: l.sort_key)
            for name, lines in result.items() if lines}


def get_npc_audio_pages() -> dict[str, Page]:
    npc_names = list(get_npc_id_to_name().values())
    gen = PreloadingGenerator(Page(s, name + "/audio") for name in npc_names)
    return {page.title().split("/")[0]: page for page in gen}


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


def generate_npc_audio_page():
    audio = get_npc_audio()
    pages = get_npc_audio_pages()
    for npc_name, page in pages.items():
        if npc_name not in audio:
            continue
        lines = audio[npc_name]
        upload_audio_files(npc_name, lines)
        result = ["{{TrekkerAudioTop}}",
                  "",
                  "==Voice Lines==",
                  lines_to_template(lines),
                  "",
                  "{{TrekkerAudioBottom}}"]
        save_page(page, "\n".join(result), summary="update NPC voice lines page")


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
    generate_npc_audio_page()


if __name__ == '__main__':
    main()
