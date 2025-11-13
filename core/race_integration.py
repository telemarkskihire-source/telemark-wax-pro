# core/race_integration.py

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

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
    Questi valori arrivano dal tuo motore meteo/NOAA.
    """
    snow_temp_c: float
    air_temp_c: Optional[float]
    snow_type: SnowType
    injected: bool


def estimate_snow_conditions_for_event(
    event: RaceEvent,
) -> SnowConditions:
    """
    QUI AGGANCI IL TUO ALGORITMO METEO/NOAA.

    Per ora metto una versione ultra semplificata, da sostituire
    collegando il tuo modulo che già calcola temperatura neve ecc.
    """
    # Placeholder molto semplice: neve fredda sopra 1500 m in inverno
    # Potresti usare: place/resort → altitudine → NOAA/ICON → temp neve.
    # Per ora ipotizziamo neve secca fredda:
    snow_temp = -6.0
    air_temp = -4.0
    snow_type = SnowType.DRY
    injected = False

    # euristica: se livello è WC/EC FIS, probabile neve iniettata su SL/GS
    if event.level and ("WC" in event.level or "EC" in event.level):
        if event.discipline in (Discipline.SL, Discipline.GS):
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
) -> Optional[tuple[TuningParamsInput, dict]]:
    """
    Dato un RaceEvent, costruisce i parametri tuning WC e restituisce
    sia i parametri che un dict serializzabile col risultato.

    Ritorna None se non ha disciplina.
    """
    if event.discipline is None:
        return None

    conditions = estimate_snow_conditions_for_event(event)

    params = TuningParamsInput(
        discipline=event.discipline,
        snow_temp_c=conditions.snow_temp_c,
        air_temp_c=conditions.air_temp_c,
        snow_type=conditions.snow_type,
        injected=conditions.injected,
        skier_level=skier_level,
    )

    rec = get_tuning_recommendation(params)

    result = {
        "event_code": event.code,
        "event_name": event.name,
        "federation": event.federation.value,
        "place": event.place,
        "nation": event.nation,
        "region": event.region,
        "start_date": event.start_date.isoformat(),
        "end_date": event.end_date.isoformat(),
        "discipline": event.discipline.value,
        "category": event.category,
        "level": event.level,
        "snow_temp_c": conditions.snow_temp_c,
        "air_temp_c": conditions.air_temp_c,
        "snow_type": conditions.snow_type.value,
        "injected": conditions.injected,
        "base_bevel_deg": rec.base_bevel_deg,
        "side_bevel_deg": rec.side_bevel_deg,
        "structure_pattern": rec.structure_pattern,
        "wax_group": rec.wax_group,
        "risk_level": rec.risk_level,
        "notes": rec.notes,
    }

    return params, result


# Esempio di funzione di alto livello che userai dalla UI

def find_and_tune_event(
    calendar_service: RaceCalendarService,
    season: int,
    code: str,
    federation: Optional[Federation] = None,
) -> Optional[dict]:
    """
    Trova una gara per codice (FIS code/FISI code) e restituisce
    direttamente il tuning WC pronto da mostrare in app.
    """
    events = calendar_service.list_events(
        season=season,
        federation=federation,
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
