# core/race_integration.py
#
# Bridge tra:
# - calendari gare (RaceCalendarService / RaceEvent)
# - motore di tuning (get_tuning_recommendation)
#
# Per ogni gara → stima condizioni neve → parametri WC → output serializzabile.

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional, Tuple

from core.race_events import RaceEvent, RaceCalendarService, Federation
from core.race_tuning import (
    get_tuning_recommendation,
    TuningParamsInput,
    Discipline,
    SkierLevel,
    SnowType,
)


@dataclass
class SnowConditions:
    """
    Condizioni neve stimate per la gara.
    TODO: agganciare il tuo algoritmo meteo/NOAA per avere valori reali.
    """
    snow_temp_c: float
    air_temp_c: Optional[float]
    snow_type: SnowType
    injected: bool


def estimate_snow_conditions_for_event(
    event: RaceEvent,
) -> SnowConditions:
    """
    QUI si deve agganciare il tuo motore meteo (Open-Meteo/NOAA ecc.).
    Per ora: placeholder molto semplice, ma già pensato in ottica WC.

    - neve secca fredda
    - aria leggermente meno fredda
    - injected=True per WC/EC su SL/GS
    """
    snow_temp = -6.0
    air_temp = -4.0
    snow_type = SnowType.DRY
    injected = False

    # euristica: WC/EC tecniche spesso iniettate
    level = (event.level or "").upper() if event.level else ""
    disc_code = _normalize_discipline_code(event.discipline)

    if level in ("WC", "EC") and disc_code in (Discipline.SL.value if hasattr(Discipline.SL, "value") else "SL",
                                               Discipline.GS.value if hasattr(Discipline.GS, "value") else "GS"):
        injected = True

    return SnowConditions(
        snow_temp_c=snow_temp,
        air_temp_c=air_temp,
        snow_type=snow_type,
        injected=injected,
    )


def _normalize_discipline_code(disc) -> Optional[str]:
    """
    Converte discipline da:
    - Enum Discipline
    - stringa "SL"/"GS"/"SG"/"DH"
    a stringa codice 'SL','GS','SG','DH'.
    """
    if disc is None:
        return None
    # Enum?
    if hasattr(disc, "value"):
        return str(disc.value)
    # stringa
    return str(disc).upper()


def _discipline_enum_from_event(disc) -> Optional[Discipline]:
    """
    Ritorna un Discipline (Enum) partendo da stringa/Enum.
    Se non è mappabile → None.
    """
    if disc is None:
        return None
    if isinstance(disc, Discipline):
        return disc
    code = _normalize_discipline_code(disc)
    try:
        return Discipline[code]
    except Exception:
        return None


def get_wc_tuning_for_event(
    event: RaceEvent,
    skier_level: SkierLevel = SkierLevel.WC,
) -> Optional[Tuple[TuningParamsInput, dict]]:
    """
    Dato un RaceEvent, costruisce i parametri tuning WC e restituisce
    sia i parametri che un dict serializzabile col risultato.

    Ritorna None se non ha disciplina mappabile.
    """
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

    # valori "stringa" anche se federation/discipline sono Enum
    federation_val = getattr(event.federation, "value", event.federation)
    discipline_val = getattr(disc_enum, "value", str(disc_enum))
    snow_type_val = getattr(conditions.snow_type, "value", str(conditions.snow_type))

    result = {
        "event_code": event.code,
        "event_name": event.name,
        "federation": federation_val,
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


# ---------------------------------------------------------
# Funzione di alto livello per la UI
# ---------------------------------------------------------

def find_and_tune_event(
    calendar_service: RaceCalendarService,
    season: int,
    code: str,
    federation: Optional[str] = None,
) -> Optional[dict]:
    """
    Trova una gara per codice (es. codice sintetico NEVE-... o FIS code)
    e restituisce direttamente il tuning WC pronto per la UI.

    Se non trova nulla o la disciplina non è mappabile → None.
    """
    events = calendar_service.list_events(
        season=season,
        federation=federation,
        discipline=None,
        nation=None,
        region=None,
    )

    target: Optional[RaceEvent] = None
    for e in events:
        if e.code == code:
            target = e
            break

    if target is None:
        return None

    res = get_wc_tuning_for_event(target)
    if res is None:
        return None

    _, result = res
    return result
