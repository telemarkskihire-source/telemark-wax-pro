# core/race_tuning.py
# Modello di tuning per Telemark · Pro Wax & Tune
#
# - Enum Discipline / SkierLevel / SnowType
# - TuningParamsInput: input “grezzo” dal modulo meteo
# - get_tuning_recommendation: converte l’input in parametri pratici
#   (angoli lamine, struttura, gruppo sciolina, note)

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------
# Enum di base
# ---------------------------------------------------------------------
class Discipline(str, Enum):
    SL = "SL"
    GS = "GS"
    SG = "SG"
    DH = "DH"
    PAR = "PAR"
    AC = "AC"
    TRAINING = "TRAINING"


class SkierLevel(str, Enum):
    WC = "wc"
    FIS = "fis"
    EXPERT = "expert"
    TOURIST = "tourist"


class SnowType(str, Enum):
    VERY_COLD_DRY = "very_cold_dry"
    COLD_DRY = "cold_dry"
    COLD_MID = "cold_mid"
    NEAR_ZERO = "near_zero"
    WET = "wet"
    ICE_INJECTED = "ice_injected"


# ---------------------------------------------------------------------
# Input per il modello di tuning dinamico
# ---------------------------------------------------------------------
@dataclass
class TuningParamsInput:
    # METEO & NEVE
    snow_temp_c: float
    air_temp_c: float
    rh_pct: float

    snow_type: SnowType
    discipline: Discipline
    skier_level: SkierLevel
    injected: bool = False

    shade_index: float = 0.5
    moisture_index: float = 0.5
    glide_index: float = 0.5

    wind_speed_kmh: float = 0.0
    cloudcover_pct: float = 0.0
    precip_mm: float = 0.0
    snowfall_mm: float = 0.0


# ---------------------------------------------------------------------
# Output raccomandazione tuning
# ---------------------------------------------------------------------
@dataclass
class TuningRecommendation:
    side_bevel_deg: float   # es. 2° => 88° reali
    base_bevel_deg: float   # es. 0.7°
    risk_level: str         # "low / medium / high"
    structure_pattern: str  # descrizione struttura soletta
    wax_group: str          # gruppo sciolina (es. "cold -8/-3")
    notes: str              # note extra


# ---------------------------------------------------------------------
# Logica di tuning – versione compatta ma robusta
# ---------------------------------------------------------------------
def _base_side_angle(params: TuningParamsInput) -> float:
    """
    Ritorna il side bevel (es. 2.0 = 88°) in funzione di livello + disciplina.
    """
    level = params.skier_level
    disc = params.discipline

    # default “turistico”
    side = 1.0

    if level == SkierLevel.TOURIST:
        if disc in (Discipline.SL, Discipline.GS):
            side = 1.0
        else:
            side = 1.0
    elif level == SkierLevel.EXPERT:
        if disc == Discipline.SL:
            side = 3.0
        elif disc == Discipline.GS:
            side = 2.0
        else:
            side = 2.0
    elif level == SkierLevel.FIS:
        if disc == Discipline.SL:
            side = 3.0
        elif disc == Discipline.GS:
            side = 2.0
        else:
            side = 2.0
    elif level == SkierLevel.WC:
        if disc == Discipline.SL:
            side = 3.0
        elif disc == Discipline.GS:
            side = 2.0
        else:
            side = 2.0

    # ghiaccio / injected -> leggero boost
    if params.injected and side < 3.0:
        side += 0.2

    return max(0.5, min(side, 4.0))


def _base_base_bevel(params: TuningParamsInput) -> float:
    """
    Base bevel in funzione del livello + neve.
    """
    snow_t = params.snow_temp_c
    level = params.skier_level

    # default
    base = 0.8

    if level == SkierLevel.TOURIST:
        base = 1.0
    elif level == SkierLevel.EXPERT:
        base = 0.8
    else:  # FIS / WC
        base = 0.7

    # neve molto fredda e secca -> un filo meno base
    if snow_t <= -10:
        base = max(0.5, base - 0.1)

    # neve molto bagnata -> leggermente più base
    if params.moisture_index > 0.8 or params.snow_type == SnowType.WET:
        base = min(1.1, base + 0.1)

    return max(0.5, min(base, 1.2))


def _structure_from_snow(params: TuningParamsInput) -> str:
    t = params.snow_temp_c
    m = params.moisture_index

    if t <= -10:
        return "struttura fine, lineare, poca profondità"
    if t <= -6:
        return "struttura medio-fine, lineare o lieve cross"
    if t <= -2:
        return "struttura media, leggera cross"
    if t <= -0.5 and m <= 0.7:
        return "struttura medio-grossa, cross marcata"
    return "struttura grossa, drenante per neve bagnata"


def _wax_group_from_snow(params: TuningParamsInput) -> str:
    t = params.snow_temp_c
    wet = params.moisture_index > 0.7 or params.snow_type == SnowType.WET

    if wet:
        return "wet / primaverile 0/-2°C"

    if t <= -14:
        return "ultra cold ≤ -14°C"
    if t <= -8:
        return "cold -14/-8°C"
    if t <= -3:
        return "cold -8/-3°C"
    if t <= -0.5:
        return "universal -4/0°C"
    return "wet / zero 0/-2°C"


def _risk_level(params: TuningParamsInput) -> str:
    """
    Stima qualitativa: quanto è “aggressivo” il set-up.
    """
    side = _base_side_angle(params)
    base = _base_base_bevel(params)

    # molto aggressivo: side ≥ 3, base ≤ 0.7, ghiaccio
    if side >= 3.0 and base <= 0.7 and params.injected:
        return "high"

    # medio: assetto gara ma non estremo
    if side >= 2.0:
        return "medium"

    return "low"


def get_tuning_recommendation(params: TuningParamsInput) -> TuningRecommendation:
    """
    Entry point usato dalla app.
    Converte TuningParamsInput in una raccomandazione completa.
    """
    side_bevel_deg = _base_side_angle(params)
    base_bevel_deg = _base_base_bevel(params)
    structure_pattern = _structure_from_snow(params)
    wax_group = _wax_group_from_snow(params)
    risk = _risk_level(params)

    notes_parts = []

    # neve / iniettata
    if params.injected or params.snow_type == SnowType.ICE_INJECTED:
        notes_parts.append("Pista iniettata / ghiacciata: preparare lamine molto precise.")
    elif params.snow_type in (SnowType.VERY_COLD_DRY, SnowType.COLD_DRY):
        notes_parts.append("Neve fredda e secca: mantenere struttura fine e sci ben affilato.")
    elif params.snow_type in (SnowType.NEAR_ZERO, SnowType.WET):
        notes_parts.append("Neve vicina allo zero / umida: attenzione al controllo, evitare strutture troppo fini.")

    # ombra / luce piatta
    if params.shade_index > 0.7 or params.cloudcover_pct > 80:
        notes_parts.append("Luce piatta: valutare lente chiara (VLT alta) e sci con set-up stabile.")

    # vento forte
    if params.wind_speed_kmh > 40:
        notes_parts.append("Vento forte: considerare protezioni termiche extra per la sciolina.")

    notes = " ".join(notes_parts) if notes_parts else "Set-up standard in base a livello, disciplina e condizione neve."

    return TuningRecommendation(
        side_bevel_deg=side_bevel_deg,
        base_bevel_deg=base_bevel_deg,
        risk_level=risk,
        structure_pattern=structure_pattern,
        wax_group=wax_group,
        notes=notes,
    )
