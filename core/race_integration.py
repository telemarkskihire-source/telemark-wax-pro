# core/race_integration.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from core.race_events import RaceEvent
from core.race_tuning import (
    get_tuning_recommendation,
    TuningParamsInput,
    Discipline,
    SkierLevel,
    SnowType,
)


@dataclass
class SnowConditions:
    snow_temp_c: float
    air_temp_c: Optional[float]
    snow_type: SnowType
    injected: bool


def _normalize_discipline_code(disc) -> Optional[str]:
    if disc is None:
        return None
    if hasattr(disc, "value"):
        return str(disc.value)
    return str(disc).upper()


def _discipline_enum_from_event(disc) -> Optional[Discipline]:
    if disc is None:
        return None
    if isinstance(disc, Discipline):
        return disc
    code = _normalize_discipline_code(disc)
    try:
        return Discipline[code]
    except Exception:
        return None


def estimate_snow_conditions_for_event(event: RaceEvent) -> SnowConditions:
    snow_temp = -6.0
    air_temp = -4.0
    snow_type = SnowType.DRY
    injected = False

    level = (event.level or "").upper()
    disc_code = _normalize_discipline_code(event.discipline)

    if level in ("WC", "EC") and disc_code in ("SL", "GS"):
        injected = True

    return SnowConditions(
        snow_temp_c=snow_temp,
        air_temp_c=air_temp,
        snow_type=snow_type,
        injected=injected,
    )


def get_wc_tuning_for_event(
    event: RaceEvent,
    skier_level: SkierLevel = SkierLevel.WC,
) -> Optional[Tuple[TuningParamsInput, dict]]:
    disc_enum = _discipline_enum_from_event(event.discipline)
    if disc_enum is None:
        return None

    conditions = estimate_snow_conditions_for_event(event)

    params = TuningParamsInput(
        discipline=disc_enum,
        snow_temp_c=conditions.snow_temp_c,
        air_temp_c=conditions.air_temp_c,
        snow_type=conditions.snow_type,
        injected=conditions.injected,
        skier_level=skier_level,
    )

    rec = get_tuning_recommendation(params)

    discipline_val = getattr(disc_enum, "value", str(disc_enum))
    snow_type_val = getattr(conditions.snow_type, "value", str(conditions.snow_type))

    result = {
        "event_code": event.code,
        "event_name": event.name,
        "federation": event.federation,
        "place": event.place,
        "nation": event.nation,
        "region": event.region,
        "start_date": event.start_date.isoformat(),
        "end_date": event.end_date.isoformat(),
        "discipline": discipline_val,
        "category": event.category,
        "level": event.level,
        "snow_temp_c": conditions.snow_temp_c,
        "air_temp_c": conditions.air_temp_c,
        "snow_type": snow_type_val,
        "injected": conditions.injected,
        "base_bevel_deg": rec.base_bevel_deg,
        "side_bevel_deg": rec.side_bevel_deg,
        "structure_pattern": rec.structure_pattern,
        "wax_group": rec.wax_group,
        "risk_level": rec.risk_level,
        "notes": rec.notes,
    }

    return params, result
