# streamlit_app.py
# Telemark · Pro Wax & Tune — versione con:
# - Ricerca località (quota > 1000 m)
# - Mappa & piste (solo sci alpino/downhill)
# - DEM locale (pendenza + esposizione)
# - Calendario gare + selezione orario gara

from __future__ import annotations

import os
import sys
import importlib
from datetime import datetime, date, time as dtime
from typing import Optional, Dict, Any

import streamlit as st

# --- forza refresh moduli core.* per evitare vecchia cache ---
importlib.invalidate_caches()
for name in list(sys.modules.keys()):
    if name == "core" or name.startswith("core."):
        del sys.modules[name]

# --- import moduli core ---
from core.i18n import L
from core.search import (
    country_selectbox,
    location_searchbox,
    get_current_selection,
    VERSION as SEARCH_VERSION,
)
from core.maps import render_map
from core.dem_tools import render_dem
from core.race_events import (
    RaceCalendarService,
    FISCalendarProvider,
    FISICalendarProvider,
    Federation,
    RaceEvent,
)
from core.race_tuning import Discipline
from core.race_integration import get_wc_tuning_for_event, SkierLevel as WCSkierLevel


# ---------------------- PAGE CONFIG & THEME ----------------------
PRIMARY = "#06b6d4"
ACCENT = "#f97316"

st.set_page_config(
    page_title="Telemark · Pro Wax & Tune",
    page_icon="❄️",
    layout="wide",
)

# CSS dark minimale
st.markdown(
    f"""
<style>
:root {{
  --bg:#0b0f13;
  --panel:#121821;
  --muted:#9aa4af;
  --fg:#e5e7eb;
  --line:#1f2937;
}}
html, body, .stApp {{
  background:var(--bg);
  color:var(--fg);
}}
[data-testid="stHeader"] {{
  background:transparent;
}}
section.main > div {{
  padding-top: 0.6rem;
}}
h1,h2,h3,h4 {{
  color:#fff;
  letter-spacing: .2px;
}}
hr {{
  border:none;
  border-top:1px solid var(--line);
  margin:.75rem 0;
}}
.card {{
  background: var(--panel);
  border:1px solid var(--line);
  border-radius:12px;
  padding:.9rem .95rem;
}}
.badge {{
  display:inline-flex;
  align-items:center;
  gap:.35rem;
  background:#020617;
  border:1px solid #1e293b;
  border-radius:999px;
  padding:.15rem .55rem;
  font-size:.8rem;
  color:#e2e8f0;
}}
.small {{
  font-size:.85rem;
  color:#cbd5e1;
}}
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------- SINGLETON SERVIZI -----------------------
# li creiamo una sola volta per evitare overhead
_FIS_PROVIDER = FISCalendarProvider()
_FISI_PROVIDER = FISICalendarProvider()
_RACE_SERVICE = RaceCalendarService(_FIS_PROVIDER, _FISI_PROVIDER)


# ---------------------- SIDEBAR ----------------------
st.sidebar.markdown("### ⚙️")

# lingua
lang = st.sidebar.selectbox(
    "Lingua / Language",
    ["IT", "EN"],
    index=0,
)
T = L["it"] if lang == "IT" else L["en"]

# pannellino debug (utile per capire che search.py è quello giusto)
search_path = os.path.abspath(__import__("core.search").search.__file__)
st.sidebar.markdown("**Debug**")
st.sidebar.code(search_path, language="bash")
st.sidebar.text(f"Search.VERSION: {getattr(sys.modules.get('core.search'), 'VERSION', SEARCH_VERSION)}")

# ---------------------- MAIN TITLE ----------------------
st.title("Telemark · Pro Wax & Tune")

# CONTEXT condiviso fra moduli (lat, lon, label, lang, race_datetime, ...)
ctx: Dict[str, Any] = {"lang": lang}

# ---------------------- 1) LOCALITÀ ----------------------
st.markdown("## 🌍 Località")

iso2 = country_selectbox(T)
location_searchbox(T, iso2)

sel = get_current_selection()
if sel:
    ctx.update(sel)
    st.session_state["lat"] = sel["lat"]
    st.session_state["lon"] = sel["lon"]
    st.session_state["place_label"] = sel["label"]

    st.markdown(
        f'<div class="card">'
        f'<span class="small"><strong>Località selezionata:</strong> {sel["label"]}</span>'
        f"</div>",
        unsafe_allow_html=True,
    )
else:
    st.info("Seleziona una località per continuare.")
    st.stop()

# ---------------------- 4) MAPPA & PISTE ----------------------
st.markdown("## 4) Mappa & piste")

# render_map può aggiornare ctx (lat/lon/label) e session_state["selected_piste_id"]
ctx = render_map(T, ctx) or ctx

# ---------------------- 5) Esposizione & pendenza (DEM) -------
st.markdown("## 5) Esposizione & pendenza")

render_dem(T, ctx)

# ---------------------- 6) Gare & orario gara -----------------
st.markdown("## 6) Gare & orario gara")

# stagione di default: se siamo dopo luglio → anno corrente, altrimenti anno-1
today = datetime.utcnow().date()
default_season = today.year if today.month >= 7 else today.year - 1

col1, col2, col3 = st.columns(3)
with col1:
    season = st.number_input(
        "Stagione (anno iniziale)",
        min_value=2020,
        max_value=default_season + 1,
        value=default_season,
        step=1,
    )
with col2:
    fed_choice = st.selectbox(
        "Federazione",
        ["Tutte", "FIS", "FISI"],
        index=1,
    )
    if fed_choice == "FIS":
        federation: Optional[Federation] = Federation.FIS
    elif fed_choice == "FISI":
        federation = Federation.FISI
    else:
        federation = None
with col3:
    disc_choice = st.selectbox(
        "Disciplina",
        ["Tutte"] + [d.value for d in Discipline],
        index=0,
    )
    discipline_filter: Optional[str] = None if disc_choice == "Tutte" else disc_choice

# per ora nessun filtro nazione/region: li aggiungiamo più avanti
nation_filter: Optional[str] = None
region_filter: Optional[str] = None

with st.spinner("Scarico calendario gare (Neveitalia)…"):
    events = _RACE_SERVICE.list_events(
        season=season,
        federation=federation,
        discipline=discipline_filter,
        nation=nation_filter,
        region=region_filter,
    )

if not events:
    st.info("Nessuna gara trovata per i filtri selezionati.")
else:
    # mappiamo label → evento
    def _event_label(ev: RaceEvent) -> str:
        disc = ev.discipline or "?"
        d_txt = ev.start_date.strftime("%Y-%m-%d")
        nation = ev.nation or ""
        nation_txt = f" ({nation})" if nation else ""
        return f"{d_txt} · {disc} · {ev.place}{nation_txt} · {ev.name}"

    options_labels = [_event_label(ev) for ev in events]
    label_to_event = {lbl: ev for lbl, ev in zip(options_labels, events)}

    default_idx = 0
    prev_label = st.session_state.get("race_selected_label")
    if prev_label in label_to_event:
        default_idx = options_labels.index(prev_label)

    selected_label = st.selectbox(
        "Seleziona gara",
        options_labels,
        index=default_idx,
        key="race_select",
    )
    selected_event = label_to_event[selected_label]
    st.session_state["race_selected_label"] = selected_label

    # orario gara
    default_time = st.session_state.get("race_time", dtime(hour=10, minute=0))
    race_time = st.time_input(
        "Orario di partenza gara (ora locale comprensorio)",
        value=default_time,
        key="race_time_input",
    )
    st.session_state["race_time"] = race_time

    race_datetime = datetime.combine(selected_event.start_date, race_time)
    ctx["race_event"] = selected_event
    ctx["race_datetime"] = race_datetime

    # piccolo riepilogo
    st.markdown(
        f'<div class="card">'
        f'<div class="small"><strong>Gara selezionata:</strong> {_event_label(selected_event)}</div>'
        f'<div class="small">Partenza prevista: {race_datetime.strftime("%Y-%m-%d · %H:%M")}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )

    # tuning WC di base (facoltativo ma utile)
    wc = get_wc_tuning_for_event(selected_event, WCSkierLevel.WC)
    if wc is not None:
        params_dict, data_dict = wc
        st.markdown("### Tuning WC di base suggerito")

        c1, c2, c3 = st.columns(3)
        c1.metric("Base bevel", f"{params_dict['base_bevel_deg']:.1f}°")
        c2.metric("Side bevel", f"{params_dict['side_bevel_deg']:.1f}°")
        c3.metric("Rischio", str(params_dict["risk_level"]).title())

        st.markdown(
            f"- **Struttura**: {data_dict['structure_pattern']}\n"
            f"- **Wax group**: {data_dict['wax_group']}\n"
            f"- **Tipo neve**: {data_dict['snow_type']}\n"
            f"- **Neve**: {data_dict['snow_temp_c']} °C · **Aria**: {data_dict['air_temp_c']} °C\n"
            f"- **Injected / ghiaccio**: {data_dict['injected']}\n"
            f"- **Note**: {data_dict['notes']}"
        )

# fine file
