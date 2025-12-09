from character_info.characters import get_characters
from utils.data_utils import autoload


def print_tower_defense():
    skill_data = autoload("Skill")
    potential_data = autoload("TowerDefensePotential")
    result: list[str] = []
    for char_name, char in get_characters().items():
        skill_key = f"80{char.id}01"
        if skill_key not in skill_data:
            continue
        result.append(f"==={char.name}===")
        result.append(";Skills")
        for i in range(1, 3):
            skill_key = f"80{char.id}{i:02d}"
            value = skill_data[skill_key]
            title = value['Title']
            desc = value['Desc']
            result.append(f"*'''{title}''': {desc}")
        result.append(";Potentials")
        for i in range(1, 5):
            potential_key = f"{char.id}01{i:02d}"
            value = potential_data[potential_key]
            title = value['Name']
            desc = value['PotentialDes']
            result.append(f"*'''{title}''': {desc}")
    print("\n".join(result))


def main():
    print_tower_defense()


if __name__ == "__main__":
    main()