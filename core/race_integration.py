# core/race_integration.py
# Bridge fra calendario gare e logica di tuning World Cup

from __future__ import annotations

import datetime as dt
from typing import Dict, Optional, Tuple

from .race_events import RaceEvent
from .race_tuning import SkierLevel


def _estimate_temps_for_event(ev: RaceEvent) -> tuple[float, float]:
    """
    Stima molto semplice di temperatura aria/neve in base al mese.
    È volutamente robusta (nessun accesso a servizi esterni) per non rompere l'app.
    """
    month = ev.start_date.month

    # valori indicativi in °C
    if month in (10, 11):
        air = -3.0
    elif month in (12, 1, 2):
        air = -7.0
    elif month in (3,):
        air = -2.0
    else:
        air = 0.0

    # neve leggermente più fredda dell'aria
    snow = air - 1.5
    return air, snow


def _wax_group_from_temp(snow_temp_c: float) -> str:
    """
    Gruppo sciolina sintetico in funzione della T neve.
    """
    if snow_temp_c <= -12:
        return "COLD (-12 / -20°C) · fluoro-free race"
    if snow_temp_c <= -6:
        return "MID-COLD (-6 / -12°C) · fluoro-free race"
    if snow_temp_c <= -2:
        return "UNIVERSAL (-2 / -8°C) · fluoro-free race"
    if snow_temp_c <= +2:
        return "WARM (-2 / +2°C) · fluoro-free race"
    return "VERY WARM (+2°C↑) · dirty snow / spring"


def _wc_edge_setup(discipline: Optional[str], level: SkierLevel) -> tuple[float, float, str]:
    """
    Impostazioni standard da WC, leggere differenze per disciplina.
    """
    # defaults
    base = 0.7
    side = 3.0
    risk = "MEDIUM"

    if discipline == "SL":
        base = 0.5
        side = 3.0
        risk = "HIGH"
    elif discipline == "GS":
        base = 0.7
        side = 3.0
        risk = "MEDIUM-HIGH"
    elif discipline == "SG":
        base = 0.8
        side = 3.0
        risk = "MEDIUM"
    elif discipline == "DH":
        base = 1.0
        side = 3.0
        risk = "MEDIUM-LOW"

    # per livelli inferiori ammorbidiamo un filo i settaggi estremi
    if level != SkierLevel.WC:
        base += 0.1
        risk = risk.replace("HIGH", "MEDIUM").replace("MEDIUM-LOW", "LOW")

    return base, side, risk


def get_wc_tuning_for_event(
    event: RaceEvent,
    skier_level: SkierLevel,
) -> Optional[Tuple[Dict, Dict]]:
    """
    Ritorna una tupla (params, data) dove:
      - params: parametri grezzi usati dal calcolo (per debug)
      - data:   struttura pronta per l'UI di Streamlit
    Se la disciplina non è riconosciuta, ritorna None.
    """

    if not event.discipline:
        return None

    air_temp_c, snow_temp_c = _estimate_temps_for_event(event)
    base_bevel_deg, side_bevel_deg, risk_level = _wc_edge_setup(
        event.discipline, skier_level
    )
    wax_group = _wax_group_from_temp(snow_temp_c)

    # classificazione neve molto semplice in base a T neve
    if snow_temp_c <= -8:
        snow_type = "WINTER · very cold / dry"
        structure_pattern = "Fine lineare / cross fine"
        injected = False
    elif snow_temp_c <= -3:
        snow_type = "WINTER · compact / aggressive"
        structure_pattern = "Medio-fine · broken / cross"
        injected = True
    elif snow_temp_c <= 0:
        snow_type = "TRANSITION · moist / compact"
        structure_pattern = "Medio · broken / wave"
        injected = True
    else:
        snow_type = "SPRING · wet / dirty"
        structure_pattern = "Grossa · a V / wave"
        injected = False

    notes = (
        f"Gara: {event.name} a {event.place} ({event
