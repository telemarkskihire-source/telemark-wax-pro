# streamlit_app.py
# Telemark · Pro Wax & Tune — Wax page + Racing page

import sys
import importlib
from datetime import datetime, time as dtime

import requests
import streamlit as st

# --- hard-reload moduli core.* per evitare cache stale ---
importlib.invalidate_caches()
for name in list(sys.modules.keys()):
    if name == "core" or name.startswith("core."):
        del sys.modules[name]

# --- import dal core ---
from core.i18n import L
import core.search as search_mod
from core.search import country_selectbox, location_searchbox, get_current_selection
from core.maps import render_map as render_map_with_pistes
from core.dem_tools import render_dem
from core.meteo import build_meteo_profile_for_race_day, build_dynamic_tuning_for_race
from core.race_events import (
    RaceCalendarService,
    FISCalendarProvider,
    Federation,
    RaceEvent,
)
from core.race_tuning import Discipline, SkierLevel

# ---------------------- THEME ----------------------
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
  --bg:#050813;
  --panel:#101624;
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
  padding-top: 0.4rem;
}}
h1,h2,h3,h4 {{
  color:#ffffff;
  letter-spacing:.2px;
}}
hr {{
  border:none;
  border-top:1px solid var(--line);
  margin:.75rem 0;
}}
.card {{
  background: var(--panel);
  border:1px solid var(--line);
  border-radius:14px;
  padding:.9rem 1.0rem;
}}
.badge {{
  display:inline-flex;
  align-items:center;
  gap:.5rem;
  background:#020617;
  border:1px solid #1e293b;
  color:#cbd5f5;
  border-radius:999px;
  padding:.28rem .7rem;
  font-size:.80rem;
}}
.small {{
  font-size:.85rem;
  color:#9ca3af;
}}
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------- GEO per località gara ----------------------


def geocode_event_place(place: str):
    """
    Geocoding veloce della località gara (Open-Meteo).
    """
    try:
        r = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={
                "name": place,
                "count": 1,
                "language": "it",
                "format": "json",
            },
            timeout=8,
        )
        r.raise_for_status()
        js = r.json() or {}
        results = js.get("results") or []
        if not results:
            return None
        it = results[0]
        lat = float(it.get("latitude", 0.0))
        lon = float(it.get("longitude", 0.0))
        name = it.get("name") or place
        admin1 = it.get("admin1") or ""
        cc = (it.get("country_code") or "").upper()
        label = f"{name}, {admin1} — {cc}" if admin1 else f"{name} — {cc}"
        return {"lat": lat, "lon": lon, "label": label}
    except Exception:
        return None


# ---------------------- SIDEBAR ----------------------

st.sidebar.markdown("### ⚙️")

lang = st.sidebar.selectbox(
    L["it"]["lang"] + " / " + L["en"]["lang"],
    ["IT", "EN"],
    index=0,
)
T = L["it"] if lang == "IT" else L["en"]

# Debug search
st.sidebar.markdown("---")
st.sidebar.markdown("#### Debug")

search_path = getattr(search_mod, "__file__", "??")
st.sidebar.text("Modulo search path:")
st.sidebar.code(search_path, language="text")

search_version = getattr(search_mod, "VERSION", "NO VERSION")
st.sidebar.text("Search.VERSION:")
st.sidebar.code(str(search_version), language="text")

st.sidebar.markdown("---")
st.sidebar.markdown("Lingua / Language")
st.sidebar.write(lang)

# ---------------------- WAX PAGE ----------------------


def render_wax_page():
    st.title("Telemark · Pro Wax & Tune")

    st.markdown("## 🌍 Località")

    col_c, col_s = st.columns([1, 2])
    with col_c:
        iso2 = country_selectbox(T)
    with col_s:
        location_searchbox(T, iso2)

    sel = get_current_selection() or {
        "lat": 45.83333,
        "lon": 7.73333,
        "label": "🇮🇹  Champoluc-Champlan, Valle d’Aosta — IT",
        "source": "default",
    }

    ctx = {
        "lat": float(sel["lat"]),
        "lon": float(sel["lon"]),
        "place_label": sel["label"],
        "place_source": sel["source"],
        "lang": lang,
    }

    # card località (senza lat/lon in chiaro)
    st.markdown(
        f"""
<div class="card">
  <div class="badge">{T.get('selected_place', 'Località selezionata')}:</div>
  <div style="margin-top:.35rem;font-size:1.05rem;font-weight:600;">
    {ctx['place_label']}
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    # mappa + piste + DEM
    render_map_with_pistes(T, ctx, map_key="wax_map", auto_select_nearest=False)
    render_dem(T, ctx)


# ---------------------- RACING PAGE ----------------------


def _format_event_label(ev: RaceEvent) -> str:
    d = ev.start_date.strftime("%d/%m/%Y")
    disc = ev.discipline or "?"
    fed = ev.federation.value
    return f"{d} · {disc} · {ev.place} ({fed})"


def render_racing_page():
    st.title("🏁 Racing · Calendari & tuning")

    base_sel = get_current_selection() or {
        "lat": 45.83333,
        "lon": 7.73333,
        "label": "🇮🇹  Champoluc-Champlan, Valle d’Aosta — IT",
        "source": "default",
    }

    # ----------------- Filtri calendario -----------------
    st.markdown("### Calendario gare")

    col_f1, col_f2 = st.columns(2)
    this_year = datetime.utcnow().year

    season = col_f1.number_input(
        T.get("race_season", "Stagione"),
        min_value=this_year - 1,
        max_value=this_year + 1,
        value=this_year,
        step=1,
        key="race_season",
    )

    # per ora solo FIS (FISI è ancora stub)
    fed_label = col_f2.selectbox(
        T.get("race_federation", "Federazione"),
        ["FIS (World Cup)"],
        index=0,
        key="race_federation",
    )
    federation = Federation.FIS

    disc_label = st.selectbox(
        T.get("race_disc", "Disciplina"),
        ["Tutte", "SL", "GS", "SG", "DH"],
        index=1,
        key="race_disc",
    )
    disc_filter = None if disc_label == "Tutte" else disc_label

    fis_provider = FISCalendarProvider()
    cal_service = RaceCalendarService(fis_provider=fis_provider)

    with st.spinner("Carico calendario gare da Neveitalia…"):
        events = cal_service.list_events(
            season=season,
            federation=federation,
            discipline=disc_filter,
            nation=None,
            region=None,
        )

    if not events:
        st.info("Nessuna gara trovata per i filtri attuali.")
        return

    # ----------------- selezione gara -----------------
    idx_default = st.session_state.get("race_event_index", 0)
    idx_default = min(idx_default, len(events) - 1)

    selected_idx = st.selectbox(
        T.get("race_select", "Seleziona gara"),
        options=list(range(len(events))),
        format_func=lambda i: _format_event_label(events[i]),
        index=idx_default,
        key="race_event_select",
    )
    selected_event = events[selected_idx]
    st.session_state["race_event_index"] = selected_idx

    # ----------------- orario gara -----------------
    col_t1, col_t2 = st.columns(2)
    default_hour = st.session_state.get("race_hour", 10)
    default_min = st.session_state.get("race_min", 0)

    race_hour = col_t1.slider("Ora gara", 7, 16, default_hour, key="race_hour")
    race_min = col_t2.slider("Minuti gara", 0, 59, default_min, step=5, key="race_min")

    race_time = dtime(hour=race_hour, minute=race_min)
    race_dt = datetime.combine(selected_event.start_date, race_time)

    # ----------------- geocoding SEMPRE (così mappa si aggiorna a ogni cambio) -----------------
    geo = geocode_event_place(selected_event.place)
    if geo:
        race_lat = geo["lat"]
        race_lon = geo["lon"]
        race_label = f"{geo['label']} · {selected_event.discipline or ''}".strip()
    else:
        race_lat = float(base_sel["lat"])
        race_lon = float(base_sel["lon"])
        race_label = f"{base_sel['label']} · {selected_event.place}"

    st.session_state["race_lat"] = race_lat
    st.session_state["race_lon"] = race_lon
    st.session_state["race_place_label"] = race_label

    ctx = {
        "lat": race_lat,
        "lon": race_lon,
        "place_label": race_label,
        "lang": lang,
        "race_datetime": race_dt,
    }

    st.markdown(
        f"""
<div class="card">
  <div class="badge">Gara selezionata</div>
  <div style="margin-top:.3rem;font-size:.98rem;">
    {_format_event_label(selected_event)}
  </div>
  <div class="small" style="margin-top:.35rem;">
    Località gara: {ctx['place_label']} · {race_dt.strftime('%d/%m/%Y · %H:%M')}
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    # ----------------- mappa racing (auto-select pista più vicina) -----------------
    st.markdown("### Mappa & piste (vista gara)")

    map_ctx = {
        "lat": ctx["lat"],
        "lon": ctx["lon"],
        "place_label": ctx["place_label"],
        "lang": lang,
    }

    map_key = f"race_map_{selected_idx}"
    render_map_with_pistes(
        T,
        map_ctx,
        map_key=map_key,
        auto_select_nearest=True,
    )

    # ----------------- METEO + TUNING DINAMICO -----------------
    st.markdown("### Meteo, visibilità & tuning dinamico")

    profile = build_meteo_profile_for_race_day(ctx)
    if profile is None:
        st.warning("Meteo non disponibile per questa località/data.")
        return

    # disciplina & livello per tuning
    if disc_filter and disc_filter in Discipline.__members__:
        race_disc_enum = Discipline[disc_filter]
    elif selected_event.discipline and selected_event.discipline in Discipline.__members__:
        race_disc_enum = Discipline[selected_event.discipline]
    else:
        race_disc_enum = Discipline.GS

    skier_level_enum = SkierLevel.WC  # modalità World Cup

    dyn = build_dynamic_tuning_for_race(
        profile=profile,
        ctx=ctx,
        discipline=race_disc_enum,
        skier_level=skier_level_enum,
        injected=False,
    )

    if dyn is None:
        st.info("Impossibile costruire raccomandazioni di tuning per questa gara.")
        return

    col_m1, col_m2 = st.columns(2)

    with col_m1:
        st.markdown("#### Condizioni neve & visibilità")
        st.metric("Temperatura neve (stimata)", f"{dyn.snow_temp_c:.1f} °C")
        st.metric("Temperatura aria", f"{dyn.air_temp_c:.1f} °C")
        st.metric("Pendenza media locale", f"{dyn.slope_deg:.1f} °")
        st.metric("Esposizione (bussola)", f"{dyn.aspect_txt} ({dyn.aspect_deg:.0f}°)")
        st.metric("Indice visibilità", f"{dyn.visibility_index:.0f}/100 · {dyn.visibility_txt}")

    with col_m2:
        st.markdown("#### Tuning consigliato")
        st.metric("Base bevel", f"{dyn.base_bevel_deg:.1f}°")
        st.metric("Side bevel", f"{dyn.side_bevel_deg:.1f}°")
        st.metric("Struttura soletta", dyn.structure_pattern)
        st.metric("Gruppo sciolina", dyn.wax_group)

    st.markdown(f"**Profilo / aggressività setup:** {dyn.risk_level.upper()}")
    st.markdown(f"**Note:** {dyn.notes}")


# ---------------------- LAYOUT Tabs ----------------------

tab1, tab2 = st.tabs(["🎿 Wax & Tune", "🏁 Racing"])

with tab1:
    render_wax_page()

with tab2:
    render_racing_page()
