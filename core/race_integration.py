# core/race_integration.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict

from core.race_tuning import (
    TuningParamsInput,
    get_tuning_recommendation,
    SnowType,
    Discipline,
    SkierLevel,
)


@dataclass
class SnowConditions:
    snow_temp_c: float
    air_temp_c: float
    snow_type: SnowType
    injected: bool


def estimate_snow(event: dict) -> SnowConditions:
    """
    Placeholder reale: la tua app userà NOAA/ICON qui.
    Ora metto un default valido.
    """
    disc = event["discipline"]

    injected = disc in ("SL", "GS")
    return SnowConditions(
        snow_temp_c=-6,
        air_temp_c=-4,
        snow_type=SnowType.DRY,
        injected=injected,
    )


def convert_disc_to_enum(disc: str) -> Optional[Discipline]:
    try:
        return Discipline[disc]
    except:
        return None


def get_wc_tuning(event: dict) -> Dict:
    """
    Riceve un evento Neveitalia (dict) e restituisce il tuning WC.
    """
    disc_enum = convert_disc_to_enum(event["discipline"])
    if disc_enum is None:
        return {"error": "Disciplina non supportata"}

    snow = estimate_snow(event)

    params = TuningParamsInput(
        discipline=disc_enum,
        snow_temp_c=snow.snow_temp_c,
        air_temp_c=snow.air_temp_c,
        snow_type=snow.snow_type,
        injected=snow.injected,
        skier_level=SkierLevel.WC,
    )

    rec = get_tuning_recommendation(params)

    return {
        "event": event,
        "base_bevel": rec.base_bevel_deg,
        "side_bevel": rec.side_bevel_deg,
        "structure": rec.structure_pattern,
        "wax": rec.wax_group,
        "risk": rec.risk_level,
        "notes": rec.notes,
        "snow": {
            "snow_temp_c": snow.snow_temp_c,
            "air_temp_c": snow.air_temp_c,
            "snow_type": snow.snow_type.value,
            "injected": snow.injected,
        }
    }
