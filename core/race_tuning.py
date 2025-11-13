from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Discipline(str, Enum):
    SL = "SL"
    GS = "GS"
    SG = "SG"
    DH = "DH"


class SkierLevel(str, Enum):
    TOURIST = "tourist"
    EXPERT = "expert"
    FIS = "fis"
    WC = "wc"


class SnowType(str, Enum):
    DRY = "dry"         # neve fredda / compatta
    PACKED = "packed"   # battuta standard
    ICE = "ice"         # lastra / neve iniettata
    WET = "wet"         # bagnata / primaverile


@dataclass
class TuningParamsInput:
    discipline: Discipline
    snow_temp_c: float           # temperatura neve stimata
    air_temp_c: Optional[float]  # opzionale
    snow_type: SnowType
    injected: bool               # pista iniettata acqua / ghiaccio
    skier_level: SkierLevel


@dataclass
class TuningRecommendation:
    base_bevel_deg: float        # gradi di base, es. 0.5
    side_bevel_deg: float        # gradi di side bevel, es. 3.0
    structure_pattern: str       # descrizione struttura soletta
    wax_group: str               # es. "cold -12/-8, hydrocarbon race"
    risk_level: str              # "low / medium / high"
    notes: str                   # testo descrittivo per app / skiman


def _classify_temp_band(snow_temp_c: float) -> str:
    """
    Restituisce una fascia di temperatura standardizzata.
    """
    if snow_temp_c <= -10:
        return "very_cold"
    elif -10 < snow_temp_c <= -6:
        return "cold"
    elif -6 < snow_temp_c <= -2:
        return "medium"
    elif -2 < snow_temp_c <= +2:
        return "near_zero"
    else:
        return "warm"


def _structure_for_conditions(temp_band: str, snow_type: SnowType, injected: bool) -> str:
    """
    Decide struttura base a livello 'WC-like'.
    """
    if injected or snow_type == SnowType.ICE:
        # neve iniettata / ghiaccio: struttura molto fine
        return "very fine linear (almost smooth), minimal rill"

    if temp_band in ("very_cold", "cold"):
        return "fine linear, rill spacing <= 0.5 mm"
    elif temp_band == "medium":
        return "medium linear / light diagonal"
    elif temp_band == "near_zero":
        return "medium-coarse linear or light cross to manage free water"
    else:  # warm
        return "coarse cross / chevron, rill spacing >= 0.75 mm, strong drainage"


def _wax_group_for_conditions(temp_band: str, snow_type: SnowType) -> str:
    """
    Non entriamo nei singoli marchi, ma in gruppi logici senza fluoro.
    """
    if temp_band == "very_cold":
        return "race wax cold -16/-10, hard paraffin, no fluoro"
    elif temp_band == "cold":
        return "race wax cold -10/-6, medium-hard paraffin, no fluoro"
    elif temp_band == "medium":
        return "race wax universal -8/-2, all-round paraffin, no fluoro"
    elif temp_band == "near_zero":
        if snow_type in (SnowType.WET, SnowType.PACKED):
            return "race wax warm -3/+2, high durability, no fluoro"
        else:
            return "race wax universal -5/0, no fluoro"
    else:  # warm
        return "race wax warm 0/+10, soft paraffin + anti-dirt, no fluoro"


def _wc_edge_setup(params: TuningParamsInput) -> tuple[float, float, str]:
    """
    Restituisce (base_bevel, side_bevel, risk_level) per WC/FIS.
    Valori in gradi di BEVEL, non l'angolo finale rispetto alla soletta.
    """
    d = params.discipline
    t_band = _classify_temp_band(params.snow_temp_c)
    injected = params.injected or (params.snow_type == SnowType.ICE)

    # default di sicurezza WC generico
    base = 0.7
    side = 3.0
    risk = "medium"

    if d == Discipline.SL:
        # SL molto aggressivo, soprattutto su ghiaccio
        if injected:
            base = 0.3
            side = 3.5
            risk = "high"
        else:
            base = 0.5
            side = 3.0
            risk = "medium-high"

    elif d == Discipline.GS:
        if injected:
            base = 0.5
            side = 3.0
            risk = "medium-high"
        else:
            base = 0.5 if t_band in ("very_cold", "cold") else 0.7
            side = 3.0
            risk = "medium"

    elif d == Discipline.SG:
        # più velocità, meno aggressività ingresso
        if injected:
            base = 0.7
            side = 3.0
            risk = "medium-high"
        else:
            base = 0.7 if t_band in ("cold", "medium") else 0.9
            side = 2.5 if t_band == "warm" else 3.0
            risk = "medium"

    elif d == Discipline.DH:
        # massima stabilità, più base
        if injected:
            base = 0.9
            side = 3.0
            risk = "medium-high"
        else:
            base = 1.0
            side = 2.5  # un filo meno aggressivo sul side
            risk = "medium"

    return base, side, risk


def _tourist_edge_setup(params: TuningParamsInput) -> tuple[float, float, str]:
    """
    Versione molto più permissiva per utenti turistici/esperti non gara.
    """
    t_band = _classify_temp_band(params.snow_temp_c)

    # base più alta, side meno estremo
    if params.skier_level == SkierLevel.TOURIST:
        base = 1.0 if t_band in ("near_zero", "warm") else 0.8
        side = 1.5 if params.discipline in (Discipline.SG, Discipline.DH) else 2.0
        risk = "low"
    else:  # EXPERT
        base = 0.8
        side = 2.0 if params.discipline in (Discipline.SL, Discipline.GS) else 2.5
        risk = "low-medium"

    return base, side, risk


def get_tuning_recommendation(params: TuningParamsInput) -> TuningRecommendation:
    """
    Entry point generico.

    - Se livello FIS / WC → usa logica World Cup.
    - Se livello tourist / expert → usa logica turistica avanzata.
    """
    temp_band = _classify_temp_band(params.snow_temp_c)
    structure = _structure_for_conditions(temp_band, params.snow_type, params.injected)
    wax_group = _wax_group_for_conditions(temp_band, params.snow_type)

    if params.skier_level in (SkierLevel.FIS, SkierLevel.WC):
        base, side, risk = _wc_edge_setup(params)
    else:
        base, side, risk = _tourist_edge_setup(params)

    notes = []

    # Note sulla neve
    if params.injected or params.snow_type == SnowType.ICE:
        notes.append("Injected/ice surface: expect very high edge grip and rapid dulling.")

    if params.discipline == Discipline.SL and params.skier_level in (SkierLevel.FIS, SkierLevel.WC):
        notes.append("SL race tune: extremely reactive, only for strong technical skiers.")

    if params.discipline == Discipline.DH:
        notes.append("DH tune: prioritizes stability and glide at high speed.")

    # Nota su manutenzione
    if params.skier_level in (SkierLevel.FIS, SkierLevel.WC):
        notes.append("Daily diamond stone maintenance recommended during race blocks.")

    notes.append(f"Temperature band classified as: {temp_band}.")

    return TuningRecommendation(
        base_bevel_deg=base,
        side_bevel_deg=side,
        structure_pattern=structure,
        wax_group=wax_group,
        risk_level=risk,
        notes=" ".join(notes),
    )
