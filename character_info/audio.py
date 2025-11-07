import subprocess
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from pywikibot import Page
from wikitextparser import Template

from character_info.characters import Character, get_characters, get_character_pages, get_id_to_char
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
    sort_key: int
    voice_type: int

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
def get_audio() -> dict[int, list[AudioLine]]:
    bubble_data_jp = load_json_from_path(jp_root / "bubble/_jp/BubbleData.json")
    bubble_data_cn = load_json_from_path(cn_root / "bubble/_cn/BubbleData.json")
    bubble_data_en = load_json_from_path(en_root / "bubble/_en/BubbleData.json")
    data = autoload("CharacterArchiveVoice")
    result: dict[int, list[AudioLine]] = {}
    for k, v in data.items():
        char_id = v['CharacterId']
        if char_id not in result:
            result[char_id] = []
        voice_type = v['ArchVoiceType']
        source = v['Source']
        s1, s2 = source.split("_")
        s2 = int(s2)
        source = f"vo_{char_id}_{'combat' if voice_type == 2 else 'ui'}_{s1}_{s2:03d}"
        if source not in bubble_data_en:
            continue
        result[char_id].append(AudioLine(
            id=int(k),
            title=v['Title'],
            source=source,
            transcription_jp=process_transcription(bubble_data_jp[source]['text']['female_jp']),
            transcription_cn=process_transcription(bubble_data_cn[source]['text']['female_cn']),
            translation=process_transcription(bubble_data_en[source]['text']['female_jp']),
            sort_key=v['Sort'],
            voice_type=voice_type,
        ))
    return result


def wav_to_ogg(wav_path: Path, ogg_path: Path) -> Path:
    subprocess.run(["ffmpeg", "-i", wav_path, "-c:a", "libopus", "-y", ogg_path],
                   check=True,
                   stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL
                   )
    return ogg_path


def upload_audio_files(char_name: str, audio_lines: list[AudioLine]) -> None:
    upload_requests = []
    for audio_line in audio_lines:
        for lang in ["jp", "cn"]:
            filename = f"{audio_line.source}_{lang}"
            source = audio_wav_root / f"{filename}.wav"
            if not source.exists():
                continue
            temp = temp_dir / f"{filename}.ogg"
            wav_to_ogg(source, temp)
            target_page = audio_line.file_page(lang)
            upload_requests.append(UploadRequest(
                source=temp,
                target=target_page,
                text=f"[[Category:{char_name} voice lines]]",
                summary="upload voice lines"
            ))
    process_uploads(upload_requests, force=True)


def get_character_audio_pages() -> dict[str, Page]:
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
    chars = get_characters()
    audio = get_audio()
    for char_name, page in get_character_audio_pages().items():
        if not should_process_char_audio(char_name):
            continue
        char = chars[char_name]
        if char.id not in audio:
            continue
        lines = audio[char.id]
        upload_audio_files(char_name, lines)
        result = ["{{TrekkerAudioTop}}",
                  "",
                  "==Daily Voice Chat==",
                  lines_to_template([l for l in lines if l.voice_type == 1]),
                  "",
                  "==Combat Voice Chat==",
                  lines_to_template([l for l in lines if l.voice_type == 2]),
                  "",
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
