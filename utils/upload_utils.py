import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pywikibot import FilePage
from pywikibot.pagegenerators import PreloadingGenerator
from pywikibot.site._upload import Uploader

from utils.wiki_utils import s


def upload_file(text: str, target: FilePage, summary: str = "batch upload file",
                file: str | Path | Callable[[], Path] = None, url: str = None, force: bool = False,
                ignore_dup: bool = False, redirect_dup: bool = False, move_dup: bool = True):
    while True:
        try:
            if url is not None:
                Uploader(s, target, source_url=url, text=text, comment=summary, ignore_warnings=force).upload()
            if file is not None:
                if callable(file):
                    file = file()
                Uploader(s, target, source_filename=str(file), text=text, comment=summary,
                         ignore_warnings=force).upload()
            return
        except Exception as e:
            search = re.search(r"duplicate of \['([^']+)'", str(e))
            if 'already exists' in str(e):
                return
            if "http-timed-out" in str(e):
                continue
            if "was-deleted" in str(e):
                # print(f"Warning: {target.title(with_ns=True)} was deleted. Reuploading...")
                # force = True
                # continue
                print(f"INFO: {target.title(with_ns=True)} was deleted. Will not reupload.")
                return
            assert search is not None, str(e)
            existing_page = f"File:{search.group(1)}"
            if ignore_dup:
                return
            if redirect_dup:
                target.set_redirect_target(existing_page, create=True, summary="redirect to existing file")
                return
            if move_dup:
                FilePage(s, existing_page).move(
                    target.title(with_ns=True, underscore=True),
                    reason="rename file")
                return
            raise RuntimeError(f"{existing_page} already exists and so {target.title()} is a dup") from e


@dataclass
class UploadRequest:
    source: Path | str | FilePage | Callable[[], Path]
    target: FilePage | str
    text: str
    summary: str = "batch upload file"


def process_uploads(requests: list[UploadRequest], force: bool = False, **kwargs) -> None:
    for r in requests:
        if isinstance(r.target, str):
            if "File" not in r.target:
                r.target = "File:" + r.target
            r.target = FilePage(s, r.target)
    existing = set(p.title() for p in PreloadingGenerator((r.target for r in requests)) if p.exists())
    for r in requests:
        if r.target.title() in existing:
            continue
        upload_args = [r.text, r.target, r.summary]
        url = None
        file = None
        if isinstance(r.source, str):
            url = r.source
        elif isinstance(r.source, FilePage):
            url = r.source.get_file_url()
        elif isinstance(r.source, Path) or callable(r.source):
            file = r.source
        upload_file(*upload_args, url=url, file=file, force=force, **kwargs)
