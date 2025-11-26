# streamlit_app.py
# Telemark · Pro Wax & Tune
# Pagina 1: Località & Mappa
# Pagina 2: Racing / Calendari + Mappa & DEM

from __future__ import annotations

import os
import sys
import importlib
from datetime import datetime, date, time as dtime
from typing import Optional, Dict, Any

import streamlit as st

# --- hard-reload moduli core.* per evitare cache vecchie ---
importlib.invalidate_caches()
for name in list(sys.modules.keys()):
    if name == "core" or name.startswith("core."):
        del sys.modules[name]

# --- import core ---
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

import core.search as search_mod  # per debug path/version

# ---------------------- PAGE CONFIG & THEME ----------------------
PRIMARY = "#06b6d4"
ACCENT = "#f97316"

st.set_page_config(
    page_title="Telemark · Pro Wax & Tune",
    page_icon="❄️",
    layout="wide",
)

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
.small {{
  font-size:.85rem;
  color:#cbd5e1;
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
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------- SERVIZI CALENDARIO ----------------------
_FIS_PROVIDER = FISCalendarProvider()
_FISI_PROVIDER = FISICalendarProvider()
_RACE_SERVICE = RaceCalendarService(_FIS_PROVIDER, _FISI_PROVIDER)


# ---------------------- FUNZIONI DI SUPPORTO --------------------
def ensure_base_location() -> Dict[str, Any]:
    """
    Restituisce la selezione corrente (se esiste) oppure Champoluc di default.
    """
    sel = get_current_selection()
    if sel:
        return sel

    # fallback Champoluc
    return {
        "lat": 45.83333,
        "lon": 7.73333,
        "label": "🇮🇹  Champoluc-Champlan, Valle d’Aosta — IT",
        "source": "default",
    }


def race_event_label(ev: RaceEvent) -> str:
    disc = ev.discipline or "?"
    d_txt = ev.start_date.strftime("%Y-%m-%d")
    nation = ev.nation or ""
    nat_txt = f" ({nation})" if nation else ""
    return f"{d_txt} · {disc} · {ev.place}{nat_txt} · {ev.name}"


# ---------------------- SIDEBAR ----------------------
st.sidebar.markdown("### ⚙️")

# lingua
lang = st.sidebar.selectbox(
    "Lingua / Language",
    ["IT", "EN"],
    index=0,
)
T = L["it"] if lang == "IT" else L["en"]

# scelta pagina
page = st.sidebar.radio(
    "Sezione",
    ["Località & Mappa", "Racing / Calendari"],
    index=0,
)

# debug search.py effettivo
search_path = os.path.abspath(search_mod.__file__)
st.sidebar.markdown("**Debug search.py**")
st.sidebar.code(search_path, language="bash")
st.sidebar.text(f"Search.VERSION: {getattr(search_mod, 'VERSION', SEARCH_VERSION)}")

# ---------------------- TITOLO GLOBALE -------------------------
st.title("Telemark · Pro Wax & Tune")

# ctx condiviso fra moduli
ctx: Dict[str, Any] = {"lang": lang}


# ====================== PAGINA 1: LOCALITÀ & MAPPA ======================
if page == "Località & Mappa":
    st.markdown("## 🌍 Località")

    iso2 = country_selectbox(T)
    location_searchbox(T, iso2)

    sel = ensure_base_location()
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

    # ---- Mappa & piste ----
    st.markdown("## 4) Mappa & piste")
    ctx = render_map(T, ctx) or ctx

    # ---- DEM (pendenza & esposizione) ----
    st.markdown("## 5) Esposizione & pendenza")
    render_dem(T, ctx)


# ====================== PAGINA 2: RACING / CALENDARI ====================
else:
    st.markdown("## 🏁 Racing / Calendari gare")

    # località di riferimento corrente (senza possibilità di cambiarla qui)
    base_loc = ensure_base_location()
    ctx.update(base_loc)
    st.session_state["lat"] = base_loc["lat"]
    st.session_state["lon"] = base_loc["lon"]
    st.session_state["place_label"] = base_loc["label"]

    st.markdown(
        f'<div class="card">'
        f'<span class="small"><strong>Località attuale per la mappa:</strong> '
        f'{base_loc["label"]}</span>'
        f"</div>",
        unsafe_allow_html=True,
    )

    # ------ Filtri calendario ------
    today = datetime.utcnow().date()
    default_season = today.year if today.month >= 7 else today.year - 1

    c1, c2, c3 = st.columns(3)
    with c1:
        season = st.number_input(
            "Stagione (anno iniziale)",
            min_value=2020,
            max_value=default_season + 1,
            value=default_season,
            step=1,
        )
    with c2:
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
    with c3:
        disc_choice = st.selectbox(
            "Disciplina",
            ["Tutte"] + [d.value for d in Discipline],
            index=0,
        )
        discipline_filter: Optional[str] = None if disc_choice == "Tutte" else disc_choice

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
        labels = [race_event_label(ev) for ev in events]
        label_to_event = {lbl: ev for lbl, ev in zip(labels, events)}

        default_idx = 0
        prev_label = st.session_state.get("race_selected_label")
        if prev_label in label_to_event:
            default_idx = labels.index(prev_label)

        selected_label = st.selectbox(
            "Seleziona gara",
            labels,
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

        # riepilogo
        st.markdown(
            f'<div class="card">'
            f'<div class="small"><strong>Gara selezionata:</strong> {race_event_label(selected_event)}</div>'
            f'<div class="small">Partenza prevista: {race_datetime.strftime("%Y-%m-%d · %H:%M")}</div>'
            f"</div>",
            unsafe_allow_html=True,
        )

        # ------ Mappa & piste anche in pagina Racing ------
        st.markdown("### Mappa & piste per la gara")

        # usiamo la stessa mappa della pagina Località & Mappa
        ctx = render_map(T, ctx) or ctx

        # DEM sulla posizione/pista scelta qui
        st.markdown("### Esposizione & pendenza sulla pista selezionata")
        render_dem(T, ctx)

        # ------ Tuning WC di base ------
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
                f"- **Neve**: {data_dict['snow_temp_c']} °C · "
                f"**Aria**: {data_dict['air_temp_c']} °C\n"
                f"- **Injected / ghiaccio**: {data_dict['injected']}\n"
                f"- **Note**: {data_dict['notes']}"
            )

# fine file
