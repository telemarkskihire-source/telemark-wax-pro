# core/race_integration.py
# Bridge fra calendario gare e logica di tuning World Cup

from __future__ import annotations

from typing import Dict, Optional, Tuple

from .race_events import RaceEvent
from .race_tuning import SkierLevel


def _estimate_temps_for_event(ev: RaceEvent) -> tuple[float, float]:
    """
    Stima semplice di temperatura aria/neve in base al mese.
    Nessuna chiamata esterna: deve essere super-robusto.
    """
    month = ev.start_date.month

    # valori indicativi in °C
    if month in (10, 11):
        air = -3.0
    elif month in (12, 1, 2):
        air = -7.0
    elif month == 3:
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


def _wc_edge_setup(
    discipline: Optional[str],
    level: SkierLevel,
) -> tuple[float, float, str]:
    """
    Settaggi standard in stile World Cup per base/fianco,
    con piccole variazioni per disciplina e livello.
    """
    # default
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

    # livelli non WC: ammorbidiamo un filo
    if level != SkierLevel.WC:
        base += 0.1
        risk = risk.replace("HIGH", "MEDIUM").replace("MEDIUM-LOW", "LOW")

    return base, side, risk


def get_wc_tuning_for_event(
    event: RaceEvent,
    skier_level: SkierLevel,
) -> Optional[Tuple[Dict, Dict]]:
    """
    Ritorna (params, data) per il pannello WC:

    - params: parametri grezzi usati dal calcolo (per debug)
    - data:   struttura pronta per l'UI di Streamlit

    Se la disciplina non è riconosciuta → None.
    """

    if not event.discipline:
        return None

    air_temp_c, snow_temp_c = _estimate_temps_for_event(event)
    base_bevel_deg, side_bevel_deg, risk_level = _wc_edge_setup(
        event.discipline,
        skier_level,
    )
    wax_group = _wax_group_from_temp(snow_temp_c)

    # classificazione neve in base alla T neve
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
        f"Gara: {event.name} a {event.place} ({event.start_date.isoformat()}). "
        f"Settaggio di base in stile Coppa del Mondo per disciplina {event.discipline}. "
        "Adatta leggermente il tuning in base allo stile personale e allo stato reale "
        "della neve il giorno della gara."
    )

    params: Dict = {
        "discipline": event.discipline,
        "skier_level": skier_level.name,
        "event_date": event.start_date.isoformat(),
        "nation": event.nation,
    }

    data: Dict = {
        "base_bevel_deg": float(base_bevel_deg),
        "side_bevel_deg": float(side_bevel_deg),
        "risk_level": risk_level,
        "structure_pattern": structure_pattern,
        "wax_group": wax_group,
        "snow_type": snow_type,
        "snow_temp_c": round(snow_temp_c, 1),
        "air_temp_c": round(air_temp_c, 1),
        "injected": injected,
        "notes": notes,
    }

    return params, data
