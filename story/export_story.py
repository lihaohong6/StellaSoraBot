import re
from dataclasses import dataclass
from typing import Any, Optional, Dict, List

from story.parse_story import get_story_episodes, StoryEpisode, StoryRow


@dataclass
class StoryExport:
    episode_id: str
    title: str
    subtitle: str
    description: str
    branches: Dict[str, str]
    main_content: str


def get_character_sprite_path(
    char_name: str, variant: str = "a", expression: str = "00"
) -> str:
    # Convert expression to integer and format as 2 digits
    # This handles cases like "002" -> "02", "01" -> "01", "1" -> "01"
    try:
        expr_num = int(expression)
    except ValueError:
        # If expression is not a valid number, default to "00"
        expr_num = 0
    return f"{char_name}_{variant}_{expr_num:02d}.png"


def character_id_to_speaker_name(char_id: str) -> str:
    return char_id


def story_row_to_messenger(
    row: StoryRow, current_speaker: Optional[str] = None
) -> List[str]:
    result = []

    if row.name == "dialogue":
        speaker = row.attributes.get("speaker", "")
        text = row.attributes.get("text", "")
        variant = row.attributes.get("variant", "a")
        expression = row.attributes.get("expression", "00")

        speaker_name = character_id_to_speaker_name(speaker)
        image_path = get_character_sprite_path(speaker_name, variant, expression)

        if speaker_name != current_speaker:
            result.extend(
                [
                    "| message",
                    f"| name :: {speaker_name}",
                    f"| image :: {image_path}",
                    f"| text :: {text}",
                    "",
                ]
            )
        else:
            result.extend(["| message", f"| text :: {text}", ""])
        return result

    if row.name == "scene_heading":
        time = row.attributes.get("time", "")
        location = row.attributes.get("location", "")
        if location:
            scene_text = f"{location}"
            if time:
                scene_text = f"{time} - {location}"
            result.extend(["| info", f"| text :: {scene_text}", ""])
        return result

    if row.name == "background":
        bg_image = row.attributes.get("image", "")
        if bg_image and bg_image != "BG_Black":
            result.extend(
                ["| raw", f"| content :: {{{{Story/background | {bg_image}}}}}", ""]
            )
        return result

    if row.name == "bgm":
        bgm_file = row.attributes.get("file", "")
        action = row.attributes.get("action", "play")

        if bgm_file and action == "play":
            result.extend(["| raw", f"| content :: {{{{Audio|{bgm_file}}}}}", ""])
        return result

    if row.name == "sound_effect":
        se_file = row.attributes.get("file", "")
        if se_file:
            result.extend(["| raw", f"| content :: {{{{Audio|{se_file}}}}}", ""])
        return result

    if row.name == "clear":
        result.extend(["| info", "| text :: [Characters cleared]", ""])
        return result

    return result


def episode_to_messenger_template(episode: StoryEpisode) -> str:
    result = ["{{Messenger"]

    if episode.title or episode.subtitle:
        episode_info = f"{episode.title}"
        if episode.subtitle:
            episode_info += f" - {episode.subtitle}"
        result.extend(["| info", f"| text :: {episode_info}", ""])

    if episode.description:
        result.extend(["| info", f"| text :: {episode.description}", ""])

    current_speaker = None

    for row in episode.rows:
        messenger_rows = story_row_to_messenger(row, current_speaker)
        result.extend(messenger_rows)

        if row.name == "dialogue":
            speaker = row.attributes.get("speaker", "")
            speaker_name = character_id_to_speaker_name(speaker)
            current_speaker = speaker_name

    result.append("}}")
    return "\n".join(result)


def create_branch_tabs(branch_groups: Dict[str, str], base_episode_id: str) -> str:
    if not branch_groups:
        return ""

    tab_result = ["{{Tab"]

    for branch_id, branch_content in sorted(branch_groups.items()):
        tab_name = branch_id.split("_")[-1].upper()
        tab_result.extend([f"| {tab_name}", f"| {branch_content}", ""])

    tab_result.append("}}")
    return "\n".join(tab_result)


def process_story_branches(episodes: Dict[str, StoryEpisode]) -> Dict[str, StoryExport]:
    exports = {}
    processed_episodes = set()

    for episode_id, episode in episodes.items():
        branch_match = re.match(r"(.+)_[a-z]$", episode_id)
        if branch_match:
            base_id = branch_match.group(1)
            if base_id not in exports:
                exports[base_id] = StoryExport(
                    episode_id=base_id,
                    title=episode.title,
                    subtitle=episode.subtitle,
                    description=episode.description,
                    branches={},
                    main_content="",
                )

            branch_content = episode_to_messenger_template(episode)
            exports[base_id].branches[episode_id] = branch_content
            processed_episodes.add(episode_id)

    for episode_id, episode in episodes.items():
        if episode_id not in processed_episodes:
            content = episode_to_messenger_template(episode)
            exports[episode_id] = StoryExport(
                episode_id=episode_id,
                title=episode.title,
                subtitle=episode.subtitle,
                description=episode.description,
                branches={},
                main_content=content,
            )

    return exports


def main():
    print("Loading and parsing story episodes...")
    episodes = get_story_episodes()
    print(f"Loaded {len(episodes)} story episodes")

    exports = process_story_branches(episodes)
    print(f"Processed into {len(exports)} story exports")

    print("\n" + "=" * 50)
    print("STORY EXPORT RESULTS")
    print("=" * 50)

    for export_id, export_data in sorted(exports.items()):
        print(f"\n--- Story: {export_id} ---")
        print(f"Title: {export_data.title}")
        if export_data.subtitle:
            print(f"Subtitle: {export_data.subtitle}")

        if export_data.branches:
            print("Branches found:")
            for branch_id in sorted(export_data.branches.keys()):
                print(f"  - {branch_id}")

            print(f"\nTabbed content for {export_id}:")
            tabs_content = create_branch_tabs(export_data.branches, export_id)
            print(tabs_content)
        else:
            print(f"\nMessenger template for {export_id}:")
            print(export_data.main_content)

    print("\nExport complete!")


if __name__ == "__main__":
    main()
