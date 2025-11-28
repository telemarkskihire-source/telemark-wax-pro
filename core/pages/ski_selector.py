# core/pages/ski_selector.py
# Selettore sci ideale per Telemark · Pro Wax & Tune
#
# - Database interno multi-marca
# - Filtri per livello sciatore, uso e condizioni neve
# - Nessuna UI Streamlit qui dentro (solo logica)

from __future__ import annotations

from dataclasses import dataclass
from typing import List


# -----------------------------------------------------------
# 1) Modello dati sci
# -----------------------------------------------------------
@dataclass
class SkiModel:
    brand: str
    model: str
    level_min: int  # 1=principiante, 2=intermedio, 3=avanzato, 4=race
    level_max: int
    snow_focus: str  # "hard", "mixed", "soft"
    usage: str       # "pista", "sl", "gs", "allmountain", "freeride", "touring"
    notes: str = ""


# -----------------------------------------------------------
# 2) Mini-database multi-marca
# -----------------------------------------------------------
SKI_DATABASE: List[SkiModel] = [
    # --- Pista allround / carving ---
    SkiModel(
        "Atomic",
        "Redster Q7 Revoshock C",
        2, 3,
        "mixed",
        "pista",
        "Allround pista stabile ma facile, ideale per progressione tecnica."
    ),
    SkiModel(
        "Head",
        "Supershape e-Magnum",
        2, 4,
        "mixed",
        "pista",
        "Carving stretto, molto reattivo ma ancora gestibile per sciatori in forma."
    ),
    SkiModel(
        "Rossignol",
        "Hero Elite MT Ti",
        2, 3,
        "mixed",
        "pista",
        "Multi-turn da pista, raggio medio, uso quotidiano ad alte prestazioni."
    ),
    SkiModel(
        "Salomon",
        "S/Max 10",
        2, 3,
        "mixed",
        "pista",
        "Per sciatori in crescita: facile ingresso curva, buona tenuta sul duro."
    ),

    # --- SL oriented ---
    SkiModel(
        "Head",
        "Worldcup Rebels e-SL",
        3, 4,
        "hard",
        "sl",
        "Slalom agonistico, cambi rapidissimi; richiede buona tecnica."
    ),
    SkiModel(
        "Rossignol",
        "Hero Elite ST Ti",
        2, 4,
        "mixed",
        "sl",
        "Slalom da pista con un po’ di tolleranza, ideale per amatori veloci."
    ),

    # --- GS oriented ---
    SkiModel(
        "Atomic",
        "Redster G9 RS",
        3, 4,
        "hard",
        "gs",
        "GS race-oriented, raggio lungo; pensato per Master e FIS.”
    ),
    SkiModel(
        "Salomon",
        "S/Race GS 12",
        3, 4,
        "hard",
        "gs",
        "GS solido per agonisti Master/FIS, molto stabile sul ghiaccio."
    ),

    # --- All-mountain / 80-90 mm ---
    SkiModel(
        "Nordica",
        "Enforcer 88",
        2, 4,
        "soft",
        "allmountain",
        "All-mountain solido, ottimo in misto pista/fuori e neve trasformata."
    ),
    SkiModel(
        "Volkl",
        "Deacon 84",
        2, 4,
        "mixed",
        "allmountain",
        "Pista larga con possibilità di uscire dal tracciato senza problemi."
    ),

    # --- Freeride ---
    SkiModel(
        "Blizzard",
        "Rustler 9",
        2, 4,
        "soft",
        "freeride",
        "Per neve fresca e mista; facile da girare, buona galleggiabilità."
    ),
    SkiModel(
        "Fischer",
        "Ranger 96",
        2, 4,
        "soft",
        "freeride",
        "Freeride versatile, buono anche nei trasferimenti su pista."
    ),

    # --- Touring / skialp ---
    SkiModel(
        "Dynafit",
        "Blacklight 88",
        3, 4,
        "mixed",
        "touring",
        "Skialp leggero per salite lunghe, più esigente in discesa.”
    ),
    SkiModel(
        "K2",
        "Wayback 88",
        2, 4,
        "mixed",
        "touring",
        "Touring equilibrato, molto diffuso e facile da gestire."
    ),
]


# -----------------------------------------------------------
# 3) Mapping condizioni neve
# -----------------------------------------------------------
def _cond_code_from_snow_label(label: str) -> str:
    """
    Converte la descrizione neve (es. da wax_logic.classify_snow)
    in un codice compatto: "hard" / "mixed" / "soft".
    """
    label_low = (label or "").lower()

    # caldo / bagnato / primaverile
    if any(k in label_low for k in ["bagnata", "primaverile", "pioggia", "umida"]):
        return "soft"

    # ghiaccio / rigelata / iniettata
    if any(k in label_low for k in ["ghiacciata", "rigelata", "iniettata"]):
        return "hard"

    # compatta/trasformata secca o generico → mixed
    return "mixed"


# -----------------------------------------------------------
# 4) Funzione principale di raccomandazione
# -----------------------------------------------------------
def recommend_skis_for_day(
    level_tag: str,
    usage_pref: str,
    snow_label: str,
) -> List[SkiModel]:
    """
    Ritorna una lista (max 6) di SkiModel consigliati per:
      - livello sciatore
      - uso principale
      - condizioni neve (testo descrittivo)

    level_tag atteso:
        "beginner" | "intermediate" | "advanced" | "race"

    usage_pref atteso:
        "Pista allround"
        "SL / raggi stretti"
        "GS / raggi medi"
        "All-mountain"
        "Freeride"
        "Skialp / touring"
    """
    level_map = {
        "beginner": 1,
        "intermediate": 2,
        "advanced": 3,
        "race": 4,
    }
    lvl = level_map.get(level_tag, 2)

    cond_code = _cond_code_from_snow_label(snow_label)

    usage_map = {
        "Pista allround": {"pista"},
        "SL / raggi stretti": {"sl"},
        "GS / raggi medi": {"gs", "pista"},
        "All-mountain": {"allmountain", "pista"},
        "Freeride": {"freeride"},
        "Skialp / touring": {"touring"},
    }
    allowed_usages = usage_map.get(usage_pref, {"pista"})

    # prima passata: filtro rigoroso (uso + neve)
    out: List[SkiModel] = []
    for ski in SKI_DATABASE:
        if not (ski.level_min <= lvl <= ski.level_max):
            continue
        if ski.usage not in allowed_usages:
            continue
        # snow_focus deve matchare le condizioni oppure essere "mixed" (universale)
        if ski.snow_focus != cond_code and ski.snow_focus != "mixed":
            continue
        out.append(ski)

    # fallback: se non troviamo nulla, allentiamo il filtro sulla neve
    if not out:
        for ski in SKI_DATABASE:
            if ski.usage in allowed_usages and ski.level_min <= lvl <= ski.level_max:
                out.append(ski)

    # limitiamo per non allungare la UI
    return out[:6]
