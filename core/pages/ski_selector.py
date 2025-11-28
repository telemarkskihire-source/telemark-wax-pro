# core/pages/ski_selector.py
# Modulo: suggerimento modelli di sci in base a livello, uso e condizione neve

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class SkiModel:
    brand: str
    model: str
    level_min: int  # 1=principiante, 2=intermedio, 3=avanzato, 4=race
    level_max: int
    snow_focus: str  # "hard", "mixed", "soft"
    usage: str       # "pista", "sl", "gs", "allmountain", "freeride", "touring"
    notes: str = ""


# Piccolo database interno di modelli
SKI_DATABASE: List[SkiModel] = [
    SkiModel("Atomic", "Redster Q7 Revoshock C", 2, 3, "mixed", "pista", "Allround pista stabile ma facile."),
    SkiModel("Atomic", "Redster G9 RS", 3, 4, "hard", "gs", "GS race-oriented, raggio lungo."),
    SkiModel("Head", "Supershape e-Magnum", 2, 4, "mixed", "pista", "Carving stretto, molto reattivo."),
    SkiModel("Head", "Worldcup Rebels e-SL", 3, 4, "hard", "sl", "SL agonistico, cambi rapidissimi."),
    SkiModel("Rossignol", "Hero Elite ST Ti", 2, 4, "mixed", "sl", "Slalom da pista, tollerante."),
    SkiModel("Rossignol", "Hero Elite MT Ti", 2, 3, "mixed", "pista", "Multi-turn, raggio medio."),
    SkiModel("Salomon", "S/Max 10", 2, 3, "mixed", "pista", "Per sciatori in crescita, facile ma preciso."),
    SkiModel("Salomon", "S/Race GS 12", 3, 4, "hard", "gs", "GS solido per agonisti Master/FIS."),
    SkiModel("Nordica", "Enforcer 88", 2, 4, "soft", "allmountain", "All-mountain solido, tanta stabilità."),
    SkiModel("Blizzard", "Rustler 9", 2, 4, "soft", "freeride", "Per neve fresca e mista."),
    SkiModel("Volkl", "Deacon 84", 2, 4, "mixed", "allmountain", "Pista larga + fuori traccia leggero."),
    SkiModel("Fischer", "Ranger 96", 2, 4, "soft", "freeride", "Freeride versatile."),
    SkiModel("Dynafit", "Blacklight 88", 3, 4, "mixed", "touring", "Skialp leggero, per salite lunghe."),
    SkiModel("K2", "Wayback 88", 2, 4, "mixed", "touring", "Touring equilibrato, molto usato."),
]


def _cond_code_from_snow_label(label: str) -> str:
    """
    Converte l’etichetta neve (es. 'primaverile bagnata', 'ghiacciata')
    in uno dei tre codici interni: 'soft' / 'hard' / 'mixed'.
    """
    label_low = (label or "").lower()
    if any(k in label_low for k in ["bagnata", "primaverile", "pioggia", "umida"]):
        return "soft"
    if any(k in label_low for k in ["ghiacciata", "rigelata", "iniettata"]):
        return "hard"
    return "mixed"


def recommend_skis_for_day(
    level_tag: str,
    usage_pref: str,
    snow_label: str,
) -> List[SkiModel]:
    """
    Ritorna una lista (max 6) di SkiModel consigliati per:
      - livello sciatore (level_tag)
      - uso principale (usage_pref)
      - condizione neve (snow_label)
    """

    # mappa livello string -> valore numerico 1-4
    level_map = {
        "beginner": 1,
        "intermediate": 2,
        "advanced": 3,
        "race": 4,
    }
    lvl = level_map.get(level_tag, 2)  # default intermedio

    cond_code = _cond_code_from_snow_label(snow_label)

    # mappa label UI -> insiemi di usage ammessi
    usage_map = {
        "Pista allround": {"pista"},
        "SL / raggi stretti": {"sl"},
        "GS / raggi medi": {"gs", "pista"},
        "All-mountain": {"allmountain", "pista"},
        "Freeride": {"freeride"},
        "Skialp / touring": {"touring"},
    }
    allowed_usages = usage_map.get(usage_pref, {"pista"})

    out: List[SkiModel] = []
    for ski in SKI_DATABASE:
        # filtro livello
        if not (ski.level_min <= lvl <= ski.level_max):
            continue
        # filtro tipo di utilizzo
        if ski.usage not in allowed_usages:
            continue
        # filtro condizione neve: mixed accetta tutto, altrimenti deve combaciare
        if ski.snow_focus != cond_code and ski.snow_focus != "mixed":
            continue
        out.append(ski)

    # fallback: se non c'è nulla, ignora il focus neve
    if not out:
        for ski in SKI_DATABASE:
            if ski.usage in allowed_usages and ski.level_min <= lvl <= ski.level_max:
                out.append(ski)

    return out[:6]
