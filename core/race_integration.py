# core/race_integration.py
# Collega RaceEvent (calendario) con parametri di tuning WC per l'app Telemark

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Tuple, Optional

from .race_events import RaceEvent


class SkierLevel(Enum):
    CLUB = "club"
    FIS = "fis"
    WC = "wc"


@dataclass
class WCTuningParams:
    base_bevel_deg: float
    side_bevel_deg: float
    risk_level: str          # "LOW" / "MEDIUM" / "HIGH"
    structure_pattern: str   # descrizione struttura
    wax_group: str           # es. "LF -7/-12"
    snow_type: str
    snow_temp_c: float
    air_temp_c: float
    injected: bool
    notes: str


# Preset veloci — da rifinire con i tuoi valori preferiti
WC_PRESETS: Dict[str, WCTuningParams] = {
    "SL": WCTuningParams(
        base_bevel_deg=0.5,
        side_bevel_deg=3.0,
        risk_level="HIGH",
        structure_pattern="fine / poco profonda",
        wax_group="WC SL · -6/-12 °C (neve dura)",
        snow_type="Neve compatta / ghiacciata",
        snow_temp_c=-8.0,
        air_temp_c=-6.0,
        injected=True,
        notes="Edge super vivi, tuning molto aggressivo. Ideale last run pre-gara.",
    ),
    "GS": WCTuningParams(
        base_bevel_deg=0.7,
        side_bevel_deg=3.0,
        risk_level="MEDIUM",
        structure_pattern="medio-fine direzionale",
        wax_group="WC GS · -6/-10 °C",
        snow_type="Neve compatta",
        snow_temp_c=-7.0,
        air_temp_c=-5.0,
        injected=True,
        notes="Setup standard WC GS per piste compatte, margine ok anche per 2ª manche.",
    ),
    "SG": WCTuningParams(
        base_bevel_deg=0.8,
        side_bevel_deg=3.0,
        risk_level="MEDIUM",
        structure_pattern="medio / lineare",
        wax_group="WC SG · -8/-14 °C (veloce)",
        snow_type="Neve compatta e fredda",
        snow_temp_c=-10.0,
        air_temp_c=-8.0,
        injected=True,
        notes="Compromesso velocità/controllo, ideale WC SG classico.",
    ),
    "DH": WCTuningParams(
        base_bevel_deg=1.0,
        side_bevel_deg=3.0,
        risk_level="HIGH",
        structure_pattern="medio-grossa / veloce",
        wax_group="WC DH · -10/-20 °C (massima scorrevolezza)",
        snow_type="Neve molto compatta / ghiacciata",
        snow_temp_c=-12.0,
        air_temp_c=-10.0,
        injected=True,
        notes="Priorità massima alla stabilità e scorrevolezza; richiede buon bagaglio tecnico.",
    ),
}


def get_wc_tuning_for_event(
    event: RaceEvent,
    skier_level: SkierLevel = SkierLevel.WC,
) -> Optional[Tuple[Dict[str, float | str | bool], Dict[str, float | str | bool]]]:
    """
    Restituisce (params_dict, data_dict) per la UI Streamlit.
    Se disciplina non è mappata → None.
    """
    disc = event.discipline
    if disc is None or disc not in WC_PRESETS:
        return None

    preset = WC_PRESETS[disc]

    params = {
        "base_bevel_deg": preset.base_bevel_deg,
        "side_bevel_deg": preset.side_bevel_deg,
        "risk_level": preset.risk_level,
    }

    data = {
        "base_bevel_deg": preset.base_bevel_deg,
        "side_bevel_deg": preset.side_bevel_deg,
        "risk_level": preset.risk_level,
        "structure_pattern": preset.structure_pattern,
        "wax_group": preset.wax_group,
        "snow_type": preset.snow_type,
        "snow_temp_c": preset.snow_temp_c,
        "air_temp_c": preset.air_temp_c,
        "injected": "Sì" if preset.injected else "No",
        "notes": preset.notes,
        "event_place": event.place,
        "event_name": event.name,
        "event_date": event.start_date.isoformat(),
    }

    return params, data
