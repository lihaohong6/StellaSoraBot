from dataclasses import dataclass

from character_info.char_skills import get_effect_by_type
from utils.data_utils import autoload


@dataclass
class StatBonus:
    hp: int = 0
    attack: int = 0
    attack_pct: float = 0
    defense: int = 0
    crit_dmg: float = 0

    def __add__(self, other):
        if isinstance(other, StatBonus):
            return StatBonus(
                self.hp + other.hp,
                self.attack + other.attack,
                self.attack_pct + other.attack_pct,
                self.defense + other.defense,
                self.crit_dmg + other.crit_dmg
            )
        raise NotImplementedError()


def parse_effect(effect_id: int) -> tuple[str, int | float]:
    data = autoload("EffectValue")
    v = data[str(effect_id)]
    effect = get_effect_by_type(v['EffectTypeFirstSubtype'], v['EffectTypeSecondSubtype'])
    return effect.desc, v['EffectTypeParam1']


def get_stat_bonus(effect_ids: list[int], strict: bool = True) -> StatBonus:
    b = StatBonus()
    for effect_id in effect_ids:
        desc, val = parse_effect(effect_id)
        match desc:
            case "Base HP":
                b.hp += int(val)
            case "Base ATK":
                b.attack += int(val)
            case "ATK":
                b.attack_pct += float(val)
            case "Base DEF":
                b.defense += int(val)
            case 'Crit DMG':
                b.crit_dmg = float(val)
            case _:
                if strict:
                    raise RuntimeError(f"Unknown effect type {effect_id}")
    return b
