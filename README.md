# StellaSoraBot

Parses game data and assets from Stella Sora and generates/uploads wiki content to
[stellasora.miraheze.org](https://stellasora.miraheze.org).

Special thanks to [StellaSoraData](https://github.com/Hiro420/StellaSoraData) and [StellaSoraParser](https://github.com/Hiro420/StellaSoraParser).

## Prerequisites

| Tool | Why | Windows install |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/) | dependency + venv manager; fetches Python itself | `winget install astral-sh.uv` |
| Python 3.13+ | | `uv python install 3.13` |
| Git | vendored repos under `vendor/` are cloned/pulled at runtime | `winget install Git.Git` |
| .NET 8 SDK | `dotnet build` of the fkStellaSora unpacker | `winget install Microsoft.DotNet.SDK.8` |
| ffmpeg (with ffprobe) | wav→ogg conversion, audio duration | `winget install Gyan.FFmpeg` |
| vgmstream-cli | wem/txtp→wav conversion | download [vgmstream-win64](https://vgmstream.org/), add to `PATH` |
| Chrome/Chromium | Playwright-driven Live2D screenshots | `uv run playwright install chromium` |

Everything except uv and Python must be on your `PATH`.

## Setup

```bash
git clone <this repo>
cd StellaSoraBot
uv sync
```

Everything under `vendor/` is fetched on first use — the
[StellaSoraData](https://github.com/Hiro420/StellaSoraData) game data repo, the
[fkStellaSora](https://github.com/shiikwi/fkStellaSora) unpacker, and
[wwiser](https://github.com/bnnm/wwiser). Nothing there needs to be set up by hand.

`uv sync` installs only the base dependencies. The optional GroundingDINO face-detection path
needs `uv sync --extra grounding` — and note that a later plain `uv sync` will uninstall those
extras again.

### Point the bot at your game install

Set `STELLA_SORA_DIR` to the folder containing `StellaSora_Data` and `Persistent_Store`.
It defaults to the maintainer's Linux Bottles/Wine prefix, so on any other machine you must
set it:

```powershell
# PowerShell — persistent, takes effect in new shells
setx STELLA_SORA_DIR "C:\YostarGames\StellaSora_EN"
```

```bash
# Linux/macOS
export STELLA_SORA_DIR="$HOME/path/to/StellaSora_EN"
```

### Wiki credentials

Create a bot password at `Special:BotPasswords` on the wiki, then create `user-passwords.py`
in the repo root (it is gitignored):

```python
('YourWikiUsername', BotPassword('Bot', 'the-generated-secret'))
```

Then edit `user-config.py` — it is tracked in git, so this edit is yours alone:

- line 6: `usernames['ss']['ss'] = 'YourWikiUsername'`
- line 15: `user_agent_format = "Test bot by User:YourWikiUsername"`

To keep that local edit out of `git status` and out of any accidental commit:

```bash
git update-index --skip-worktree user-config.py
```

(Undo with `--no-skip-worktree` if you ever need to change the file for real.)

`user-config.py` is read by pywikibot as a plain textual config file — it does not support
arbitrary Python, so don't try to make it read environment variables.

## Running

**Always run from the repository root.** Paths like `assets/` and `vendor/` are resolved
relative to the working directory.

There are two entry points:

```bash
uv run -m main2   # re-extract assets from the game install, then character gallery + CG upload
uv run -m main    # generate + upload character/disc wiki pages
```

Run `main2` after **the game** updates — it re-runs the asset extraction before uploading.
Run `main` after **both** the game and
[StellaSoraData](https://github.com/Hiro420/StellaSoraData) have updated; it pulls that repo
itself before generating pages.

### First run

On a fresh checkout the order is `unpack.unpack_main` → `main` → `main2`, because some data
has to be bootstrapped before the later steps can use it:

```bash
uv run -m unpack.unpack_main
uv run -m main
uv run -m main2
```

After that, order no longer matters — run whichever entry point matches what updated.

Individual modules can also be run on their own with `uv run -m <package>.<module>` (e.g.
`uv run -m story.parse_story`). Those are one-off jobs, not part of the routine update flow.

## Live2D viewer

`tools/live2d_viewer.html` renders the exported Live2D models in a browser.

```bash
# from the repository root
uv run python -m http.server 8000
```

Then open <http://localhost:8000/tools/live2d_viewer.html>.

The model dropdown is built by scraping the directory listings under
`assets/assetbundles/actor2d/character/`. Opening the HTML as a `file://` URL will not work.

If models are missing. Re-export them with
`uv run -m unpack.unpack_live2d --skin-id <id> --overwrite` (drop `--skin-id` to redo all of
them).

## Known gaps when running on a second machine

These are not fixed and will need attention:

- **`vendor/StellaSoraData-Private`** is a private repository and may not be cloneable.
- **GroundingDINO needs an NVIDIA GPU.** `character_info/char_sprite_face.py` hardcodes
  `cuda:0`, and `pyproject.toml` pins the `pytorch-cu128` wheel index. There is no CPU fallback.
  The model weights (`vendor/groundingdino/weights/groundingdino_swint_ogc.pth`) must be
  downloaded manually.
- **`unpack/unpack_event_images.py`** additionally reads an `OldAssets` folder next to the game
  install — a manually curated archive of `.unity3d` bundles for content the game no longer
  ships. It is optional: without it the export prints a warning and skips those event images.
