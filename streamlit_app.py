# streamlit_app.py
# Telemark · Pro Wax & Tune

from __future__ import annotations

import os
import sys
import importlib
from datetime import datetime, date as Date, time as dtime, timedelta
from typing import Optional, Dict, Any

import requests
import pandas as pd
import streamlit as st
import altair as alt

# --- hard-reload moduli core.* ---
importlib.invalidate_caches()
for name in list(sys.modules.keys()):
    if name == "core" or name.startswith("core."):
        del sys.modules[name]

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
    ASIVACalendarProvider,
    Federation,
    RaceEvent,
    ASIVA_PARTEC_CODES,
)
from core.race_tuning import (
    Discipline,
    SkierLevel as TuneSkierLevel,
    get_tuning_recommendation,
)
from core.race_integration import get_wc_tuning_for_event, SkierLevel as WCSkierLevel
from core import meteo as meteo_mod
from core import wax_logic as wax_mod
from core.pages.ski_selector import recommend_skis_for_day

import core.search as search_mod  # debug

# ---------------------- THEME ----------------------
PRIMARY = "#06b6d4"
ACCENT = "#f97316"

st.set_page_config(
    page_title="Telemark · Pro Wax & Tune",
    page_icon="❄️",
    layout="wide",
)

st.markdown(
    """
<style>
:root {
  --bg:#0b0f13;
  --panel:#121821;
  --muted:#9aa4af;
  --fg:#e5e7eb;
  --line:#1f2937;
}
html, body, .stApp {
  background:var(--bg);
  color:#e5e7eb;
}
[data-testid="stHeader"] {
  background:transparent;
}
section.main > div {
  padding-top: 0.6rem;
}
h1,h2,h3,h4 {
  color:#fff;
  letter-spacing: .2px;
}
hr {
  border:none;
  border-top:1px solid var(--line);
  margin:.75rem 0;
}
.card {
  background: var(--panel);
  border:1px solid var(--line);
  border-radius:12px;
  padding:.9rem .95rem;
}
.small {
  font-size:.85rem;
  color:#cbd5e1;
}
.badge {
  display:inline-flex;
  align-items:center;
  gap:.35rem;
  background:#020617;
  border:1px solid #1e293b;
  border-radius:999px;
  padding:.15rem .55rem;
  font-size:.8rem;
  color:#e2e8f0;
}
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------- SERVIZI CALENDARIO ----------------------
_FIS_PROVIDER = FISCalendarProvider()
_ASIVA_PROVIDER = ASIVACalendarProvider()
_RACE_SERVICE = RaceCalendarService(_FIS_PROVIDER, _ASIVA_PROVIDER)

# ---------------------- GEOCODER GARE --------------------------
MIN_ELEVATION_M = 1000.0
UA = {"User-Agent": "telemark-wax-pro/2.0"}


@st.cache_data(ttl=3600, show_spinner=False)
def geocode_race_place(query: str) -> Optional[Dict[str, Any]]:
    """
    Geocoding per le località di gara / comprensori.
    """
    q = (query or "").strip()
    if not q:
        return None

    params = {
        "name": q,
        "language": "it",
        "count": 10,
        "format": "json",
    }
    try:
        r = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params=params,
            headers=UA,
            timeout=8,
        )
        r.raise_for_status()
        js = r.json() or {}
    except Exception:
        return None

    results = js.get("results") or []
    if not results:
        return None

    best_high = None
    best_any = None
    best_any_elev = -9999.0

    for it in results:
        elev_val = it.get("elevation")
        try:
            elev = float(elev_val) if elev_val is not None else None
        except Exception:
            elev = None

        if elev is not None and elev > best_any_elev:
            best_any_elev = elev
            best_any = it
        elif best_any is None:
            best_any = it

        if elev is not None and elev >= MIN_ELEVATION_M and best_high is None:
            best_high = it

    chosen = best_high or best_any
    if not chosen:
        return None

    cc = (chosen.get("country_code") or "").upper()
    name = chosen.get("name") or ""
    admin1 = chosen.get("admin1") or chosen.get("admin2") or ""
    base = f"{name}, {admin1}".strip().replace(" ,", ",")
    flag = "".join(chr(127397 + ord(c)) for c in cc) if len(cc) == 2 else "🏳️"
    label = f"{flag}  {base} — {cc}"

    return {
        "lat": float(chosen.get("latitude", 0.0)),
        "lon": float(chosen.get("longitude", 0.0)),
        "label": label,
    }


# ---------------------- SUPPORTO -------------------------------
def ensure_base_location() -> Dict[str, Any]:
    sel = get_current_selection()
    if sel:
        return sel
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


def _clean_place_for_geocoder(raw_place: str) -> str:
    """
    Località "bella" per il geocoder:
    - "Soelden (AUT)" -> "Soelden"
    - "Pila - Gressan" -> "Pila"
    """
    txt = raw_place or ""
    txt = txt.split("(")[0].strip()
    if " - " in txt:
        txt = txt.split(" - ")[0].strip()
    if not txt:
        txt = raw_place.strip()
    return txt


def center_ctx_on_race_location(ctx: Dict[str, Any], event: RaceEvent) -> Dict[str, Any]:
    """
    Centra la mappa sulla località di gara usando il nome pulito.
    """
    query_name = _clean_place_for_geocoder(event.place or "")

    base = ensure_base_location()
    lat = base["lat"]
    lon = base["lon"]
    label = base["label"]

    geo = geocode_race_place(query_name)
    if geo:
        lat = geo["lat"]
        lon = geo["lon"]
        label = geo["label"]

    ctx["lat"] = lat
    ctx["lon"] = lon
    ctx["place_label"] = label

    st.session_state["lat"] = lat
    st.session_state["lon"] = lon
    st.session_state["place_label"] = label

    return ctx


# ---------------------- SIDEBAR (solo lingua + debug) ----------------------
st.sidebar.markdown("### ⚙️")

lang = st.sidebar.selectbox(
    "Lingua / Language",
    ["IT", "EN"],
    index=0,
)
T = L["it"] if lang == "IT" else L["en"]

search_path = os.path.abspath(search_mod.__file__)
st.sidebar.markdown("**Debug search.py**")
st.sidebar.code(search_path, language="bash")
st.sidebar.text(f"Search.VERSION: {getattr(search_mod, 'VERSION', SEARCH_VERSION)}")

# ---------------------- MAIN -------------------------
st.title("Telemark · Pro Wax & Tune")

# Selezione pagina in alto (non più in sidebar)
page = st.radio(
    "Sezione",
    ["Località & Mappa", "Racing / Calendari"],
    index=0,
    horizontal=True,
    key="main_page_selector",
)

ctx: Dict[str, Any] = {"lang": lang}
today_utc = datetime.utcnow().date()

# =====================================================
# PAGINA 1: LOCALITÀ & MAPPA
# =====================================================
if page == "Località & Mappa":
    st.markdown("## 🌍 Località")

    iso2 = country_selectbox(T)
    location_searchbox(T, iso2)

    base_sel = ensure_base_location()

    # Se ho già cliccato sulla mappa, uso quel lat/lon
    lat = st.session_state.get("lat", base_sel["lat"])
    lon = st.session_state.get("lon", base_sel["lon"])

    ctx.update(base_sel)
    ctx["lat"] = lat
    ctx["lon"] = lon

    display_label = st.session_state.get("place_label", base_sel["label"])
    ctx["place_label"] = display_label
    st.session_state["place_label"] = display_label

    st.markdown(
        f"<div class='card small'><b>Località selezionata:</b> {display_label}</div>",
        unsafe_allow_html=True,
    )

    # ---------------- Mappa & DEM ----------------
    st.markdown("## 2) Mappa & piste")
    ctx["map_context"] = "local"
    ctx = render_map(T, ctx) or ctx

    # aggiorno in sessione questo centro (incluso click)
    st.session_state["lat"] = ctx.get("lat", lat)
    st.session_state["lon"] = ctx.get("lon", lon)

    st.markdown("## 3) Esposizione & pendenza")
    render_dem(T, ctx)

    # ---------------- METEO LOCALITÀ ----------------
    st.markdown("## 4) Meteo località & profilo giornata")

    col_d, col_t = st.columns(2)
    with col_d:
        ref_date_free = st.date_input(
            "Giorno di riferimento",
            value=today_utc,
            key="free_ref_date",
        )
    with col_t:
        ref_time_free = st.time_input(
            "Orario di riferimento (inizio sciata)",
            value=st.session_state.get("free_ref_time", dtime(hour=10, minute=0)),
            key="free_ref_time",
        )

    dummy_event = RaceEvent(
        federation=Federation.ASIVA,
        codex=None,
        name="Free ski",
        place=ctx["place_label"],
        discipline=Discipline.GS,
        start_date=ref_date_free,
        end_date=ref_date_free,
        nation=None,
        region=None,
        category=None,
        raw_type="FREE",
        level="LOCAL",
    )
    ctx["race_event"] = dummy_event
    race_dt_free = datetime.combine(ref_date_free, ref_time_free)
    ctx["race_datetime"] = race_dt_free

    profile_local = meteo_mod.build_meteo_profile_for_race_day(ctx)
    if profile_local is None:
        st.warning("Impossibile costruire il profilo meteo per questa località.")
    else:
        df = pd.DataFrame(
            {
                "time": profile_local.times,
                "temp_air": profile_local.temp_air,
                "snow_temp": profile_local.snow_temp,
                "rh": profile_local.rh,
                "cloudcover": profile_local.cloudcover,
                "windspeed": profile_local.windspeed,
                "precipitation": profile_local.precip,
                "snowfall": profile_local.snowfall,
                "shade_index": profile_local.shade_index,
                "snow_moisture_index": profile_local.snow_moisture_index,
                "glide_index": profile_local.glide_index,
            }
        ).set_index("time")

        st.caption("Grafici riferiti all'intera giornata (00–24) per la località selezionata.")
        df_reset = df.reset_index()

        # ---- prepara dati per modulo wax ----
        wax_df = df_reset.copy()
        wax_df["time_local"] = wax_df["time"]
        wax_df["T_surf"] = wax_df["snow_temp"]
        wax_df["RH"] = wax_df["rh"]
        wax_df["wind"] = wax_df["windspeed"]
        wax_df["cloud"] = wax_df["cloudcover"] / 100.0

        if "snow_moisture_index" in wax_df.columns:
            wax_df["liq_water_pct"] = wax_df["snow_moisture_index"] * 5.0
        else:
            wax_df["liq_water_pct"] = 0.0

        def _ptyp(row):
            pr = float(row.get("precipitation", 0.0))
            sf = float(row.get("snowfall", 0.0))
            if sf > 0.1 and pr - sf > 0.1:
                return "mixed"
            if sf > 0.1:
                return "snow"
            if pr > 0.1:
                return "rain"
            return None

        wax_df["ptyp"] = wax_df.apply(_ptyp, axis=1)

        st.session_state["_meteo_res"] = wax_df[
            ["time_local", "T_surf", "RH", "wind", "liq_water_pct", "cloud", "ptyp"]
        ]
        st.session_state["ref_day"] = ref_date_free

        # ---- grafici principali ----
        temp_long = df_reset.melt(
            id_vars="time",
            value_vars=["temp_air", "snow_temp"],
            var_name="series",
            value_name="value",
        )
        chart_temp = (
            alt.Chart(temp_long)
            .mark_line()
            .encode(
                x=alt.X("time:T", title=None),
                y=alt.Y("value:Q", title=None),
                color=alt.Color("series:N", title=None),
                tooltip=[],
            )
            .properties(height=180)
        )

        chart_rh = (
            alt.Chart(df_reset)
            .mark_line()
            .encode(
                x=alt.X("time:T", title=None),
                y=alt.Y("rh:Q", title=None),
                tooltip=[],
            )
            .properties(height=180)
        )

        chart_shade = (
            alt.Chart(df_reset)
            .mark_line()
            .encode(
                x=alt.X("time:T", title=None),
                y=alt.Y("shade_index:Q", title=None),
                tooltip=[],
            )
            .properties(height=180)
        )

        chart_glide = (
            alt.Chart(df_reset)
            .mark_line()
            .encode(
                x=alt.X("time:T", title=None),
                y=alt.Y("glide_index:Q", title=None),
                tooltip=[],
            )
            .properties(height=180)
        )

        wind_long = df_reset.melt(
            id_vars="time",
            value_vars=["windspeed", "cloudcover"],
            var_name="series",
            value_name="value",
        )
        chart_wind_cloud = (
            alt.Chart(wind_long)
            .mark_line()
            .encode(
                x=alt.X("time:T", title=None),
                y=alt.Y("value:Q", title=None),
                color=alt.Color("series:N", title=None),
                tooltip=[],
            )
            .properties(height=200)
        )

        c_a, c_b = st.columns(2)
        with c_a:
            st.markdown("**Temperatura aria vs neve**")
            st.altair_chart(chart_temp, use_container_width=True)

            st.markdown("**Umidità relativa (%)**")
            st.altair_chart(chart_rh, use_container_width=True)
        with c_b:
            st.markdown("**Indice ombreggiatura** (0 sole, 1 ombra/luce piatta)")
            st.altair_chart(chart_shade, use_container_width=True)

            st.markdown("**Indice scorrevolezza teorica** (0–1)")
            st.altair_chart(chart_glide, use_container_width=True)

        st.markdown("**Vento (km/h) e copertura nuvolosa (%)**")
        st.altair_chart(chart_wind_cloud, use_container_width=True)

        # icone meteo
        icon_df = df_reset.copy()
        icons = []
        for _, row in icon_df.iterrows():
            cc = float(row["cloudcover"])
            pr = float(row.get("precipitation", 0.0))
            sf = float(row.get("snowfall", 0.0))
            if sf > 0.2:
                icon = "❄️"
            elif pr > 0.2:
                icon = "🌧️"
            else:
                if cc < 20:
                    icon = "☀️"
                elif cc < 60:
                    icon = "🌤️"
                else:
                    icon = "☁️"
            icons.append(icon)

        icon_df["icon"] = icons
        icon_df["y"] = 0
        chart_icons = (
            alt.Chart(icon_df)
            .mark_text(size=18)
            .encode(
                x=alt.X("time:T", title=None),
                y=alt.Y("y:Q", axis=None),
                text="icon:N",
                tooltip=[],
            )
            .properties(height=60)
        )

        st.markdown("**Sintesi meteo giornata (icone)**")
        st.altair_chart(chart_icons, use_container_width=True)

        # ----- condizione neve al momento di riferimento -----
        ts_ref = datetime.combine(ref_date_free, ref_time_free)
        idx = (wax_df["time_local"] - ts_ref).abs().idxmin()
        row_ref = wax_df.loc[idx]
        snow_label = wax_mod.classify_snow(row_ref)

        st.markdown(
            f"<div class='card small'>"
            f"<b>Condizione neve stimata alle {ref_time_free.strftime('%H:%M')}</b>: "
            f"{snow_label} · T neve ~ {row_ref['T_surf']:.1f} °C · "
            f"UR ~ {row_ref['RH']:.0f}%</div>",
            unsafe_allow_html=True,
        )

        # ---------------- SCI IDEALE PER LA GIORNATA ----------------
        st.markdown("## 5) Sci ideale per la giornata")

        col_l, col_u = st.columns(2)
        with col_l:
            ski_level_label = st.selectbox(
                "Livello sciatore (sci ideale)",
                [
                    ("Principiante", "beginner"),
                    ("Intermedio", "intermediate"),
                    ("Avanzato", "advanced"),
                    ("Race / agonista", "race"),
                ],
                index=1,
                format_func=lambda x: x[0],
                key="ski_level_loc",
            )
        with col_u:
            usage_pref = st.selectbox(
                "Uso principale",
                [
                    "Pista allround",
                    "SL / raggi stretti",
                    "GS / raggi medi",
                    "All-mountain",
                    "Freeride",
                    "Skialp / touring",
                ],
                index=0,
                key="ski_usage_loc",
            )

        chosen_level_tag = ski_level_label[1]
        skis = recommend_skis_for_day(
            level_tag=chosen_level_tag,
            usage_pref=usage_pref,
            snow_label=snow_label,
        )

        if skis:
            st.markdown("**Suggerimenti modelli (multi-marca):**")
            for ski in skis:
                st.markdown(
                    f"<div class='card small'>"
                    f"<b>{ski.brand} · {ski.model}</b><br>"
                    f"Categoria: {ski.usage} · Focus neve: {ski.snow_focus}<br>"
                    f"{ski.notes}"
                    f"</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.info("Nessun modello suggerito per questi filtri (lista interna vuota).")

        # ---------------- TUNING DINAMICO LOCALITÀ ----------------
        st.markdown("## 6) 🎯 Tuning dinamico (località)")

        level_choice = st.selectbox(
            "Livello sciatore per il tuning",
            [
                ("WC / Coppa del Mondo", TuneSkierLevel.WC),
                ("FIS / Continental", TuneSkierLevel.FIS),
                ("Esperto", TuneSkierLevel.EXPERT),
                ("Turistico evoluto", TuneSkierLevel.TOURIST),
            ],
            format_func=lambda x: x[0],
            key="dyn_level_loc",
        )
        chosen_dyn_level = level_choice[1]
        st.session_state["dyn_level_tag"] = chosen_dyn_level.value

        disc_loc = st.selectbox(
            "Disciplina principale",
            [d for d in Discipline],
            index=1,  # GS
            key="dyn_disc_loc",
        )

        injected_loc = st.checkbox(
            "Pista iniettata / ghiacciata",
            value=False,
            key="dyn_injected_loc",
        )

        dyn_loc = meteo_mod.build_dynamic_tuning_for_race(
            profile=profile_local,
            ctx=ctx,
            discipline=disc_loc,
            skier_level=chosen_dyn_level,
            injected=injected_loc,
        )

        if dyn_loc is None:
            st.info("Non è stato possibile calcolare il tuning dinamico per questa località.")
        else:
            rec_loc = get_tuning_recommendation(dyn_loc.input_params)
            side_angle = 90.0 - rec_loc.side_bevel_deg  # 87/88 ecc.

            c1t, c2t, c3t = st.columns(3)
            c1t.metric("Angolo lamina (side)", f"{side_angle:.1f}°")
            c2t.metric("Base bevel", f"{rec_loc.base_bevel_deg:.1f}°")
            c3t.metric("Profilo", rec_loc.risk_level.capitalize())

            st.markdown(
                f"- **Neve stimata**: {dyn_loc.input_params.snow_temp_c:.1f} °C "
                f"({dyn_loc.snow_type.value})\n"
                f"- **Aria all'ora scelta**: {dyn_loc.input_params.air_temp_c:.1f} °C\n"
                f"- **Struttura soletta suggerita**: {rec_loc.structure_pattern}\n"
                f"- **Wax group suggerito**: {rec_loc.wax_group}\n"
                f"- **VLT consigliata maschera/occhiale**: "
                f"{dyn_loc.vlt_pct:.0f}% ({dyn_loc.vlt_label})\n"
                f"- **Note edges**: {rec_loc.notes}\n"
            )
            st.caption(dyn_loc.summary)

        # ---------------- SCIOLINE & TUNING DETTAGLIATO (LOCALITÀ) ----------------
        st.markdown("## 7) ❄️ Scioline & tuning dettagliato (località)")
        wax_mod.render_wax(T, ctx)

# =====================================================
# PAGINA 2: RACING / CALENDARI
# =====================================================
else:
    st.markdown("## 🏁 Racing / Calendari gare")

    base_loc = ensure_base_location()
    ctx.update(base_loc)
    st.session_state["place_label"] = base_loc["label"]

    st.markdown(
        f'<div class="card">'
        f'<span class="small"><strong>Località di partenza (default):</strong> '
        f'{base_loc["label"]}</span>'
        f"</div>",
        unsafe_allow_html=True,
    )

    dev_mode = st.checkbox(
        "Modalità sviluppo: mostra tutte le gare (ignora limite 7 giorni)",
        value=True,
    )

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
            ["Tutte", "FIS", "ASIVA (FISI VdA)"],
            index=1,
        )
        if fed_choice == "FIS":
            federation: Optional[Federation] = Federation.FIS
        elif fed_choice.startswith("ASIVA"):
            federation = Federation.ASIVA
        else:
            federation = None
    with c3:
        disc_choice = st.selectbox(
            "Disciplina",
            ["Tutte"] + [d.value for d in Discipline],
            index=0,
        )
        discipline_filter: Optional[str] = None if disc_choice == "Tutte" else disc_choice

    c4, c5 = st.columns(2)
    with c4:
        months_labels = [
            "Tutti i mesi",
            "Gennaio", "Febbraio", "Marzo", "Aprile",
            "Maggio", "Giugno", "Luglio", "Agosto",
            "Settembre", "Ottobre", "Novembre", "Dicembre",
        ]
        month_choice = st.selectbox(
            "Mese (FIS + ASIVA)",
            months_labels,
            index=0,
        )
        month_filter: Optional[int] = None
        if month_choice != "Tutti i mesi":
            month_filter = months_labels.index(month_choice)

    with c5:
        if federation == Federation.ASIVA or federation is None:
            cat_label = st.selectbox(
                "Categoria ASIVA (Partec.)",
                ["Tutte"] + ASIVA_PARTEC_CODES,
                index=0,
            )
            category_filter: Optional[str] = (
                None if cat_label == "Tutte" else cat_label
            )
        else:
            category_filter = None

    nation_filter: Optional[str] = None
    region_filter: Optional[str] = None

    with st.spinner("Scarico calendari gare…"):
        events = _RACE_SERVICE.list_events(
            season=season,
            federation=federation,
            discipline=discipline_filter,
            nation=nation_filter,
            region=region_filter,
            month=month_filter,
            category=category_filter,
        )

    if events and not dev_mode:
        max_delta = timedelta(days=7)
        events = [
            ev
            for ev in events
            if ev.start_date >= today and (ev.start_date - today) <= max_delta
        ]

    if not events:
        msg = "Nessuna gara trovata per i filtri selezionati."
        if not dev_mode:
            msg += " (nei prossimi 7 giorni)"
        st.info(msg)
    else:
        labels = [race_event_label(ev) for ev in events]
        label_to_event = {lbl: ev for lbl, ev in zip(labels, events)}

        prev_label = st.session_state.get("race_selected_label")
        default_idx = labels.index(prev_label) if prev_label in label_to_event else 0

        selected_label = st.selectbox(
            "Seleziona gara",
            labels,
            index=default_idx,
            key="race_select",
        )
        selected_event = label_to_event[selected_label]
        st.session_state["race_selected_label"] = selected_label

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

        # --- LOGICA NUOVA: centro SOLO se la gara è cambiata ---
        last_centered = st.session_state.get("race_last_centered_label")
        if last_centered != selected_label:
            ctx = center_ctx_on_race_location(ctx, selected_event)
            st.session_state["race_last_centered_label"] = selected_label
        else:
            # usa eventuale click precedente (puntatore sulla pista)
            lat = st.session_state.get("lat", base_loc["lat"])
            lon = st.session_state.get("lon", base_loc["lon"])
            ctx["lat"] = lat
            ctx["lon"] = lon

        ctx["map_context"] = (
            f"race_{selected_event.start_date.isoformat()}_{selected_event.place}"
        )

        st.markdown(
            f'<div class="card">'
            f'<div class="small"><strong>Gara selezionata:</strong> '
            f'{race_event_label(selected_event)}</div>'
            f'<div class="small">Partenza prevista: '
            f'{race_datetime.strftime("%Y-%m-%d · %H:%M")}</div>'
            f'<div class="small"><strong>Località mappa per questa gara:</strong> '
            f'{ctx.get("place_label","")}</div>'
            f"</div>",
            unsafe_allow_html=True,
        )

        # Mappa & DEM gara
        st.markdown("### Mappa & piste per la gara")
        ctx = render_map(T, ctx) or ctx

        # aggiorno lat/lon con eventuale click su pista
        st.session_state["lat"] = ctx.get("lat", st.session_state.get("lat", base_loc["lat"]))
        st.session_state["lon"] = ctx.get("lon", st.session_state.get("lon", base_loc["lon"]))

        st.markdown("### Esposizione & pendenza sulla pista selezionata")
        render_dem(T, ctx)

        # ---------- Tuning WC di base (preset statico) ----------
        wc = get_wc_tuning_for_event(selected_event, WCSkierLevel.WC)
        if wc is not None:
            params_dict, data_dict = wc
            st.markdown("### Tuning WC di base (preset)")

            side_wc_angle = 90.0 - params_dict["side_bevel_deg"]
            c1m, c2m, c3m = st.columns(3)
            c1m.metric("Angolo lamina WC (side)", f"{side_wc_angle:.1f}°")
            c2m.metric("Base bevel", f"{params_dict['base_bevel_deg']:.1f}°")
            c3m.metric("Profilo", str(params_dict["risk_level"]).title())

            st.markdown(
                f"- **Struttura**: {data_dict['structure_pattern']}\n"
                f"- **Wax group**: {data_dict['wax_group']}\n"
                f"- **Tipo neve**: {data_dict['snow_type']}\n"
                f"- **Neve (preset)**: {data_dict['snow_temp_c']} °C · "
                f"**Aria (preset)**: {data_dict['air_temp_c']} °C\n"
                f"- **Injected / ghiaccio**: {data_dict['injected']}\n"
                f"- **Note**: {data_dict['notes']}"
            )

        # ---------- METEO & PROFILO GARA ----------
        st.markdown("### 📈 Meteo & profilo giornata gara")

        profile = meteo_mod.build_meteo_profile_for_race_day(ctx)
        if profile is None:
            st.warning("Impossibile costruire il profilo meteo per questa gara.")
        else:
            df = pd.DataFrame(
                {
                    "time": profile.times,
                    "temp_air": profile.temp_air,
                    "snow_temp": profile.snow_temp,
                    "rh": profile.rh,
                    "cloudcover": profile.cloudcover,
                    "windspeed": profile.windspeed,
                    "precipitation": profile.precip,
                    "snowfall": profile.snowfall,
                    "shade_index": profile.shade_index,
                    "snow_moisture_index": profile.snow_moisture_index,
                    "glide_index": profile.glide_index,
                }
            ).set_index("time")

            st.caption("Grafici riferiti all'intera giornata di gara (00–24).")

            df_reset = df.reset_index()

            temp_long = df_reset.melt(
                id_vars="time",
                value_vars=["temp_air", "snow_temp"],
                var_name="series",
                value_name="value",
            )
            chart_temp = (
                alt.Chart(temp_long)
                .mark_line()
                .encode(
                    x=alt.X("time:T", title=None),
                    y=alt.Y("value:Q", title=None),
                    color=alt.Color("series:N", title=None),
                    tooltip=[],
                )
                .properties(height=180)
            )

            chart_rh = (
                alt.Chart(df_reset)
                .mark_line()
                .encode(
                    x=alt.X("time:T", title=None),
                    y=alt.Y("rh:Q", title=None),
                    tooltip=[],
                )
                .properties(height=180)
            )

            chart_shade = (
                alt.Chart(df_reset)
                .mark_line()
                .encode(
                    x=alt.X("time:T", title=None),
                    y=alt.Y("shade_index:Q", title=None),
                    tooltip=[],
                )
                .properties(height=180)
            )

            chart_glide = (
                alt.Chart(df_reset)
                .mark_line()
                .encode(
                    x=alt.X("time:T", title=None),
                    y=alt.Y("glide_index:Q", title=None),
                    tooltip=[],
                )
                .properties(height=180)
            )

            wind_long = df_reset.melt(
                id_vars="time",
                value_vars=["windspeed", "cloudcover"],
                var_name="series",
                value_name="value",
            )
            chart_wind_cloud = (
                alt.Chart(wind_long)
                .mark_line()
                .encode(
                    x=alt.X("time:T", title=None),
                    y=alt.Y("value:Q", title=None),
                    color=alt.Color("series:N", title=None),
                    tooltip=[],
                )
                .properties(height=200)
            )

            c_a, c_b = st.columns(2)
            with c_a:
                st.markdown("**Temperatura aria vs neve**")
                st.altair_chart(chart_temp, use_container_width=True)

                st.markdown("**Umidità relativa (%)**")
                st.altair_chart(chart_rh, use_container_width=True)
            with c_b:
                st.markdown("**Indice ombreggiatura** (0 sole, 1 ombra/luce piatta)")
                st.altair_chart(chart_shade, use_container_width=True)

                st.markdown("**Indice scorrevolezza teorica** (0–1)")
                st.altair_chart(chart_glide, use_container_width=True)

            st.markdown("**Vento (km/h) e copertura nuvolosa (%)**")
            st.altair_chart(chart_wind_cloud, use_container_width=True)

            icon_df = df_reset.copy()
            icons = []
            for _, row in icon_df.iterrows():
                cc = float(row["cloudcover"])
                pr = float(row.get("precipitation", 0.0))
                sf = float(row.get("snowfall", 0.0))
                if sf > 0.2:
                    icon = "❄️"
                elif pr > 0.2:
                    icon = "🌧️"
                else:
                    if cc < 20:
                        icon = "☀️"
                    elif cc < 60:
                        icon = "🌤️"
                    else:
                        icon = "☁️"
                icons.append(icon)

            icon_df["icon"] = icons
            icon_df["y"] = 0
            chart_icons = (
                alt.Chart(icon_df)
                .mark_text(size=18)
                .encode(
                    x=alt.X("time:T", title=None),
                    y=alt.Y("y:Q", axis=None),
                    text="icon:N",
                    tooltip=[],
                )
                .properties(height=60)
            )

            st.markdown("**Sintesi meteo giornata (icone)**")
            st.altair_chart(chart_icons, use_container_width=True)

            # ---------- TUNING DINAMICO GARA ----------
            st.markdown("### 🎯 Tuning dinamico basato su meteo reale (gara)")

            level_choice = st.selectbox(
                "Livello sciatore per questo tuning",
                [
                    ("WC / Coppa del Mondo", TuneSkierLevel.WC),
                    ("FIS / Continental", TuneSkierLevel.FIS),
                    ("Esperto", TuneSkierLevel.EXPERT),
                    ("Turistico evoluto", TuneSkierLevel.TOURIST),
                ],
                format_func=lambda x: x[0],
                key="dyn_level_race",
            )
            chosen_level = level_choice[1]
            st.session_state["dyn_level_tag"] = chosen_level.value

            injected_flag = st.checkbox(
                "Pista iniettata / ghiacciata",
                value=True if wc is not None else False,
                key="dyn_injected_race",
            )

            dyn = meteo_mod.build_dynamic_tuning_for_race(
                profile=profile,
                ctx=ctx,
                discipline=selected_event.discipline or Discipline.GS,
                skier_level=chosen_level,
                injected=injected_flag,
            )

            if dyn is None:
                st.info("Non è stato possibile calcolare il tuning dinamico per questa gara.")
            else:
                rec = get_tuning_recommendation(dyn.input_params)
                side_angle = 90.0 - rec.side_bevel_deg  # 87/88 ecc.

                c1t, c2t, c3t = st.columns(3)
                c1t.metric("Angolo lamina (side)", f"{side_angle:.1f}°")
                c2t.metric("Base bevel", f"{rec.base_bevel_deg:.1f}°")
                c3t.metric("Profilo", rec.risk_level.capitalize())

                st.markdown(
                    f"- **Neve stimata gara**: {dyn.input_params.snow_temp_c:.1f} °C "
                    f"({dyn.snow_type.value})\n"
                    f"- **Aria all'ora di gara**: {dyn.input_params.air_temp_c:.1f} °C\n"
                    f"- **Struttura soletta suggerita**: {rec.structure_pattern}\n"
                    f"- **Wax group suggerito**: {rec.wax_group}\n"
                    f"- **VLT consigliata maschera/occhiale**: "
                    f"{dyn.vlt_pct:.0f}% ({dyn.vlt_label})\n"
                    f"- **Note edges**: {rec.notes}\n"
                )
                st.caption(dyn.summary)
