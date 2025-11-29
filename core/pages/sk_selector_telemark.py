# core/pages/ski_selector.py
# Selettore sci basato sull'inventario Telemark Ski Hire (Champoluc)
#
# Viene usato da streamlit_app.py:
#   from core.pages.ski_selector import recommend_skis_for_day
#
# La funzione principale:
#   recommend_skis_for_day(level_tag, usage_pref, snow_label)
# ritorna una lista di SkiModel filtrati in base a:
#   - livello sciatore (beginner/intermediate/advanced/race)
#   - uso principale (pista allround, SL, GS, allmountain, freeride, touring)
#   - condizione neve stimata ("hard", "mixed", "soft" derivato da snow_label)
#
# >>> IMPORTANTISSIMO <<<
# Qui sotto trovi una INVENTORY di esempio.
# Vai sul sito telemarkskihire.com, prendi i tuoi modelli reali, e
# sostituisci / aggiungi righe in TELEMARK_INVENTORY mantenendo
# la stessa struttura.

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class SkiModel:
    """
    Modello di sci del noleggio Telemark.

    Campi principali usati dalla app:
      - brand: marca (es. "Head")
      - model: modello (es. "Supershape e-Magnum")
      - level_min / level_max:
            1 = principiante
            2 = intermedio
            3 = avanzato
            4 = race / agonista
      - snow_focus:
            "hard"  = neve dura/ghiacciata
            "mixed" = condizioni miste / standard
            "soft"  = fresca, primaverile, morbida
      - usage:
            "pista", "sl", "gs", "allmountain", "freeride", "touring"
      - notes:
            testo libero che appare nella card (es. lunghezze, raggio, ecc.)
    """
    brand: str
    model: str
    level_min: int
    level_max: int
    snow_focus: str
    usage: str
    notes: str = ""


# --------------------------------------------------------------------
# INVENTARIO TELEMARK (ESEMPIO)
#
# 🔧 DA PERSONALIZZARE:
# - Sostituisci i modelli di esempio con quelli reali presenti sul noleggio
# - Mantieni i valori level_min/level_max e usage coerenti
# --------------------------------------------------------------------
TELEMARK_INVENTORY: List[SkiModel] = [
    # ===== ESEMPIO PISTA ALLROUND / INTERMEDI =====
    SkiModel(
        brand="Head",
        model="Shape e.V5 Rental",
        level_min=1,
        level_max=2,
        snow_focus="mixed",
        usage="pista",
        notes="Pista allround facile; lunghezze tipiche 149–170 cm.",
    ),
    SkiModel(
        brand="Head",
        model="Supershape e-Magnum",
        level_min=2,
        level_max=4,
        snow_focus="mixed",
        usage="pista",
        notes="Carving avanzato; 163–177 cm; raggio medio-corto.",
    ),
    SkiModel(
        brand="Rossignol",
        model="React 8 / React 10 Rental",
        level_min=2,
        level_max=3,
        snow_focus="mixed",
        usage="pista",
        notes="Pista performance; ideale per sciatori in crescita.",
    ),
    SkiModel(
        brand="Atomic",
        model="Redster Q7 Revoshock C",
        level_min=2,
        level_max=3,
        snow_focus="mixed",
        usage="pista",
        notes="Allround pista stabile ma gestibile; 152–169 cm.",
    ),

    # ===== SL / GS RACE / MASTER =====
    SkiModel(
        brand="Head",
        model="Worldcup Rebels e-SL",
        level_min=3,
        level_max=4,
        snow_focus="hard",
        usage="sl",
        notes="Slalom race; raggio stretto; per agonisti o esperti aggressivi.",
    ),
    SkiModel(
        brand="Head",
        model="Worldcup Rebels e-GS RD",
        level_min=3,
        level_max=4,
        snow_focus="hard",
        usage="gs",
        notes="GS gara; misura master/giovani; richiede buona tecnica.",
    ),
    SkiModel(
        brand="Rossignol",
        model="Hero Elite ST / ST TI",
        level_min=2,
        level_max=4,
        snow_focus="mixed",
        usage="sl",
        notes="Slalom pista; reattivo ma ancora gestibile per avanzati.",
    ),
    SkiModel(
        brand="Atomic",
        model="Redster G9 RS",
        level_min=3,
        level_max=4,
        snow_focus="hard",
        usage="gs",
        notes="GS race; ideale per neve compatta e tracciato.",
    ),

    # ===== ALL-MOUNTAIN / FREERIDE =====
    SkiModel(
        brand="Nordica",
        model="Enforcer 88",
        level_min=2,
        level_max=4,
        snow_focus="soft",
        usage="allmountain",
        notes="All-mountain solido; buono su pista e bordi pista.",
    ),
    SkiModel(
        brand="Blizzard",
        model="Rustler 9",
        level_min=2,
        level_max=4,
        snow_focus="soft",
        usage="freeride",
        notes="Per neve fresca e mista; molto giocoso.",
    ),
    SkiModel(
        brand="Volkl",
        model="Deacon 84 / Deacon XTD",
        level_min=2,
        level_max=4,
        snow_focus="mixed",
        usage="allmountain",
        notes="Pista larga + fuori traccia leggero; versatile.",
    ),

    # ===== SKIALP / TOURING =====
    SkiModel(
        brand="Dynafit",
        model="Blacklight 88 Rental",
        level_min=3,
        level_max=4,
        snow_focus="mixed",
        usage="touring",
        notes="Skialp leggero; per chi fa gite lunghe.",
    ),
    SkiModel(
        brand="K2",
        model="Wayback 88",
        level_min=2,
        level_max=4,
        snow_focus="mixed",
        usage="touring",
        notes="Touring equilibrato; molto diffuso.",
    ),
]


# --------------------------------------------------------------------
# Traduzione condizioni neve da snow_label della app
# --------------------------------------------------------------------
def _cond_code_from_snow_label(label: str) -> str:
    """
    Converte la descrizione della neve (es. 'primaverile bagnata')
    in un codice sintetico:
      - 'soft'  (primaverile, bagnata, umida, fresca profonda)
      - 'hard'  (ghiacciata, rigelata, iniettata)
      - 'mixed' (default / condizioni intermedie)
    """
    label_low = (label or "").lower()
    if any(k in label_low for k in ["bagnata", "primaverile", "pioggia", "umida", "pesante"]):
        return "soft"
    if any(k in label_low for k in ["ghiacciata", "rigelata", "iniettata", "vetro", "dura"]):
        return "hard"
    return "mixed"


# --------------------------------------------------------------------
# Mappa uso principale → categorie usage
# --------------------------------------------------------------------
_USAGE_MAP = {
    "Pista allround": {"pista"},
    "SL / raggi stretti": {"sl"},
    "GS / raggi medi": {"gs", "pista"},
    "All-mountain": {"allmountain", "pista"},
    "Freeride": {"freeride"},
    "Skialp / touring": {"touring"},
}


_LEVEL_MAP = {
    "beginner": 1,
    "intermediate": 2,
    "advanced": 3,
    "race": 4,
}


# --------------------------------------------------------------------
# Funzione principale usata da streamlit_app.py
# --------------------------------------------------------------------
def recommend_skis_for_day(
    level_tag: str,
    usage_pref: str,
    snow_label: str,
) -> List[SkiModel]:
    """
    Filtra l'inventario Telemark in base a:
      - livello sciatore (level_tag)
      - uso principale (usage_pref)
      - condizione neve (snow_label -> hard/mixed/soft)

    Restituisce massimo 12 modelli, già ordinati
    in modo "ragionevole" per presentazione.
    """
    lvl = _LEVEL_MAP.get(level_tag, 2)  # fallback intermedio
    cond_code = _cond_code_from_snow_label(snow_label)
    allowed_usages = _USAGE_MAP.get(usage_pref, {"pista"})

    candidates: List[SkiModel] = []

    for ski in TELEMARK_INVENTORY:
        # livello compatibile
        if not (ski.level_min <= lvl <= ski.level_max):
            continue

        # uso compatibile
        if ski.usage not in allowed_usages:
            continue

        # focus neve: accetta:
        # - esattamente la condizione
        # - "mixed" come jolly per un po' tutto
        if ski.snow_focus != "mixed" and ski.snow_focus != cond_code:
            continue

        candidates.append(ski)

    # Se nessun risultato, rilassiamo il vincolo sulla neve
    if not candidates:
        for ski in TELEMARK_INVENTORY:
            if ski.usage in allowed_usages and ski.level_min <= lvl <= ski.level_max:
                candidates.append(ski)

    # Ordiniamo:
    #   - prima quelli più vicini come livello
    #   - poi preferendo focus neve che matcha esattamente cond_code
    def _score(s: SkiModel) -> float:
        # distanza media dal range livello
        if lvl < s.level_min:
            level_delta = s.level_min - lvl
        elif lvl > s.level_max:
            level_delta = lvl - s.level_max
        else:
            level_delta = 0

        # penalità se il focus neve è solo "mixed"
        cond_penalty = 0 if s.snow_focus == cond_code else 0.5
        if s.snow_focus == "mixed":
            cond_penalty += 0.25

        return level_delta + cond_penalty

    candidates.sort(key=_score)

    # Limitiamo il numero di modelli mostrati
    return candidates[:12]
