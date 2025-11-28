# streamlit_app.py
# Telemark · Pro Wax & Tune
# Pagina 1: Località & Mappa
# Pagina 2: Racing / Calendari + Mappa, DEM, Meteo & Tuning dinamico

from __future__ import annotations

import os
import sys
import importlib
from datetime import datetime, time as dtime, timedelta
from typing import Optional, Dict, Any
import unicodedata

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
    SnowType,
    TuningParamsInput,
    get_tuning_recommendation,
)
from core.race_integration import get_wc_tuning_for_event, SkierLevel as WCSkierLevel
from core import meteo as meteo_mod

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
  color:#e5e7eb;
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
_ASIVA_PROVIDER = ASIVACalendarProvider()
_RACE_SERVICE = RaceCalendarService(_FIS_PROVIDER, _ASIVA_PROVIDER)


    
    
# ---------------------- GEOCODER GARE --------------------------
MIN_ELEVATION_M = 1000.0
UA = {"User-Agent": "telemark-wax-pro/2.0"}

# punti "partenza impianti" principali (affinabili a mano)
# NB: sono approssimativi, puoi correggere numeri lat/lon se hai i tuoi GPX
import unicodedata
import re


def _norm_place_key(s: str) -> str:
    """Normalizza una stringa di località in una chiave compatta."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    # uniforma separatori
    s = s.replace("'", " ").replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s.replace(" ", "")


LOCALITY_LIFT_POINTS = {
    # Monterosa / Ayas
    _norm_place_key("Champoluc"): (45.8292, 7.7337),        # partenza funivia Crest
    _norm_place_key("Frachey"): (45.8363, 7.7462),          # partenza funifor Frachey
    _norm_place_key("Antagnod - Ayas"): (45.8139, 7.7246),

    # Pila
    _norm_place_key("Pila - Gressan"): (45.7427, 7.3189),   # stazione a monte Pila (campo gare)
    _norm_place_key("Pila"): (45.7427, 7.3189),

    # Gressoney
    _norm_place_key("Gressoney - La - Trinité"): (45.8151, 7.8273),
    _norm_place_key("Gressoney - Saint - Jean"): (45.7765, 7.8240),

    # Cervino
    _norm_place_key("Breuil Cervinia"): (45.9365, 7.6297),
    _norm_place_key("Valtournenche"): (45.8853, 7.6226),

    # Altre VdA
    _norm_place_key("La Thuile"): (45.7187, 6.9475),
    _norm_place_key("Torgnon"): (45.8067, 7.5684),
    _norm_place_key("Champorcher"): (45.6122, 7.6332),
    _norm_place_key("Valgrisenche"): (45.6569, 7.0369),
}


@st.cache_data(ttl=3600, show_spinner=False)
def geocode_race_place(query: str) -> Optional[Dict[str, Any]]:
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
    best = None
    for it in results:
        elev = it.get("elevation")
        if elev is None:
            continue
        try:
            if float(elev) < MIN_ELEVATION_M:
                continue
        except Exception:
            continue
        best = it
        break

    if not best:
        return None

    cc = (best.get("country_code") or "").upper()
    name = best.get("name") or ""
    admin1 = best.get("admin1") or best.get("admin2") or ""
    base = f"{name}, {admin1}".strip().replace(" ,", ",")
    flag = "".join(
        chr(127397 + ord(c)) for c in cc
    ) if len(cc) == 2 else "🏳️"
    label = f"{flag}  {base} — {cc}"

    return {
        "lat": float(best.get("latitude", 0.0)),
        "lon": float(best.get("longitude", 0.0)),
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


def center_ctx_on_race_location(ctx: Dict[str, Any], event: RaceEvent) -> Dict[str, Any]:
    raw_place = (event.place or "").strip()

    # 1) prendi solo la parte "località" prima di "- Ayas", ecc.
    candidate = raw_place
    for sep in [" - ", "–", "/"]:
        if sep in candidate:
            candidate = candidate.split(sep)[0].strip()
            break

    # se è tipo "Champoluc - Ayas" → "Champoluc"
    # "Gressoney - La - Trinité" rimane intera (ci pensa la normalizzazione)
    norm = _norm_place_key(candidate)

    base = ensure_base_location()
    lat = base["lat"]
    lon = base["lon"]
    label = base["label"]

    # 2) se abbiamo un punto impianto noto, usiamo quello
    if norm in LOCALITY_LIFT_POINTS:
        lat, lon = LOCALITY_LIFT_POINTS[norm]
        label = f"{candidate} · partenza impianti (preset)"
    else:
        # 3) fallback: geocoding generico montano
        geo = geocode_race_place(candidate)
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


# ---------------------- SIDEBAR ----------------------
st.sidebar.markdown("### ⚙️")

lang = st.sidebar.selectbox(
    "Lingua / Language",
    ["IT", "EN"],
    index=0,
)
T = L["it"] if lang == "IT" else L["en"]

page = st.sidebar.radio(
    "Sezione",
    ["Località & Mappa", "Racing / Calendari"],
    index=0,
)

search_path = os.path.abspath(search_mod.__file__)
st.sidebar.markdown("**Debug search.py**")
st.sidebar.code(search_path, language="bash")
st.sidebar.text(f"Search.VERSION: {getattr(search_mod, 'VERSION', SEARCH_VERSION)}")

# ---------------------- MAIN -------------------------
st.title("Telemark · Pro Wax & Tune")

ctx: Dict[str, Any] = {"lang": lang}

# =============== PAGINA 1: LOCALITÀ & MAPPA ===============
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

    # mappa
    st.markdown("## 4) Mappa & piste")
    ctx["map_context"] = "local"
    ctx = render_map(T, ctx) or ctx

    # DEM
    st.markdown("## 5) Esposizione & pendenza")
    render_dem(T, ctx)

# =============== PAGINA 2: RACING / CALENDARI ===============
else:
    st.markdown("## 🏁 Racing / Calendari gare")

    base_loc = ensure_base_location()
    ctx.update(base_loc)
    st.session_state["lat"] = base_loc["lat"]
    st.session_state["lon"] = base_loc["lon"]
    st.session_state["place_label"] = base_loc["label"]

    st.markdown(
        f'<div class="card">'
        f'<span class="small"><strong>Località di partenza (attuale):</strong> '
        f'{base_loc["label"]}</span>'
        f"</div>",
        unsafe_allow_html=True,
    )

    # --- flag sviluppo per filtro 7 giorni ---
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

    # --- Filtro mese + categoria ASIVA (Partec.) -----------------------
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
            month_filter = months_labels.index(month_choice)  # 1–12

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

    # --- filtro: SOLO gare entro i prossimi 7 giorni (disattivabile in dev) ---
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

        # centra sempre sulla località gara
        ctx = center_ctx_on_race_location(ctx, selected_event)

        # mappa context specifico per forza-refresh
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

        # mappa & piste
        st.markdown("### Mappa & piste per la gara")
        ctx = render_map(T, ctx) or ctx

        # DEM con ombreggiatura (usa ctx['race_datetime'] internamente)
        st.markdown("### Esposizione & pendenza sulla pista selezionata")
        render_dem(T, ctx)

        # ---------- Tuning WC di base (preset statico) ----------
        wc = get_wc_tuning_for_event(selected_event, WCSkierLevel.WC)
        if wc is not None:
            params_dict, data_dict = wc
            st.markdown("### Tuning WC di base (preset)")

            c1m, c2m, c3m = st.columns(3)
            c1m.metric("Base bevel", f"{params_dict['base_bevel_deg']:.1f}°")
            c2m.metric("Side bevel", f"{params_dict['side_bevel_deg']:.1f}°")
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

        # ---------- METEO & GRAFICI GARA ----------
        st.markdown("### 📈 Meteo & profilo giornata gara")

        profile = meteo_mod.build_meteo_profile_for_race_day(ctx)
        if profile is None:
            st.warning("Impossibile costruire il profilo meteo per questa gara.")
        else:
            # DataFrame per grafici
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

            # ---- grafici statici Altair, SENZA tooltip ----
            df_reset = df.reset_index()

            # aria vs neve
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

            # umidità
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

            # ombreggiatura
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

            # glide
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

            # vento + nuvole
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

            # ---- Grafico icone meteo stile Meteoblue ----
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

            # ---------- TUNING DINAMICO BASATO SU METEO ----------
            st.markdown("### 🎯 Tuning dinamico basato su meteo reale")

            level_choice = st.selectbox(
                "Livello sciatore per questo tuning",
                [
                    ("WC / Coppa del Mondo", TuneSkierLevel.WC),
                    ("FIS / Continental", TuneSkierLevel.FIS),
                    ("Esperto", TuneSkierLevel.EXPERT),
                    ("Turistico evoluto", TuneSkierLevel.TOURIST),
                ],
                format_func=lambda x: x[0],
            )
            chosen_level = level_choice[1]

            injected_flag = st.checkbox(
                "Pista iniettata / ghiacciata",
                value=True if wc is not None else False,
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

                c1t, c2t, c3t = st.columns(3)
                c1t.metric("Base bevel (dinamico)", f"{rec.base_bevel_deg:.1f}°")
                c2t.metric("Side bevel (dinamico)", f"{rec.side_bevel_deg:.1f}°")
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
