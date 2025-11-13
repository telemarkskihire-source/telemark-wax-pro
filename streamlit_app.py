# streamlit_app.py
# Telemark · Pro Wax & Tune — modalità standard + modalità gara FIS/FISI

import sys
import os
import importlib

import streamlit as st
import requests

# --- hard-reload silenzioso del pacchetto core.* per evitare cache stale ---
importlib.invalidate_caches()
for name in list(sys.modules.keys()):
    if name == "core" or name.startswith("core."):
        del sys.modules[name]

# --- import dal core (moduli esistenti) ---
from core.i18n import L
from core.search import location_searchbox

# --- import moduli gara/tuning ---
from core.race_events import (
    RaceCalendarService,
    FISCalendarProvider,
    FISICalendarProvider,
    Federation,
)
from core.race_tuning import Discipline, SkierLevel
from core.race_integration import get_wc_tuning_for_event

# ---------- THEME ----------
st.set_page_config(
    page_title="Telemark · Pro Wax & Tune",
    page_icon="❄️",
    layout="wide",
)
st.markdown(
    """
<style>
:root { --bg:#0b0f13; --panel:#121821; --muted:#9aa4af; --fg:#e5e7eb; --line:#1f2937; }
html, body, .stApp { background:var(--bg); color:var(--fg); }
[data-testid="stHeader"] { background:transparent; }
section.main > div { padding-top:.6rem; }
h1,h2,h3,h4 { color:#fff; letter-spacing:.2px }
hr { border:none; border-top:1px solid var(--line); margin:.75rem 0 }
.badge {
  display:inline-flex; align-items:center; gap:.5rem;
  background:#0b1220; border:1px solid #203045; color:#cce7f2;
  border-radius:12px; padding:.35rem .6rem; font-size:.85rem;
}
.small { color:#9aa4af; font-size:.9rem; }
</style>
""",
    unsafe_allow_html=True,
)

st.title("Telemark · Pro Wax & Tune")

# ---------- LINGUA ----------
st.sidebar.markdown("### ⚙️")
lang = st.sidebar.selectbox(
    L["it"]["lang"] + " / " + L["en"]["lang"],
    ["IT", "EN"],
    index=0,
)
T = L["it"] if lang == "IT" else L["en"]
show_info = st.sidebar.toggle("Mostra info tecniche", value=False)

# ============================================================
# TABS: 1) Wax & Tune   2) Race / Gare
# ============================================================

tab_wax, tab_race = st.tabs(["🧊 Wax & Tune", "🏁 Race / Gare"])

# ============================================================
# TAB 1 — WAX & TUNE (quello che avevi, solo incapsulato)
# ============================================================
with tab_wax:
    # 1) RICERCA LOCALITÀ — SOLO SEARCHBOX (Open-Meteo + Photon)
    st.markdown(f"### 1) {T['search_ph']}")

    # location_searchbox gestisce internamente persistenza di lat/lon/label
    lat, lon, place_label = location_searchbox(T)

    # Badge posizione
    st.markdown(
        f"<div class='badge'>📍 <b>{place_label}</b> · "
        f"lat <b>{lat:.5f}</b>, lon <b>{lon:.5f}</b></div>",
        unsafe_allow_html=True,
    )

    # ---------- CONTEXT condiviso per i moduli ----------
    ctx = {
        "lat": float(lat),
        "lon": float(lon),
        "place_label": place_label,
        "iso2": "",
        "lang": lang,
        "T": T,
    }
    st.session_state["_ctx"] = ctx

    # ---------- MODULI ESISTENTI ----------
    st.markdown("### 2) Moduli")

    def _load(modname: str):
        """Import semplice con messaggio di errore in UI."""
        try:
            importlib.invalidate_caches()
            return importlib.import_module(modname)
        except Exception as e:
            st.error(f"Import fallito {modname}: {e}")
            return None

    def _call_first(mod, candidates, *args, **kwargs):
        """
        Cerca nel modulo la prima funzione disponibile tra 'candidates'
        e la chiama con (*args, **kwargs).
        """
        if not mod:
            return False, "missing"
        for name in candidates:
            fn = getattr(mod, name, None)
            if callable(fn):
                try:
                    fn(*args, **kwargs)
                    return True, name
                except Exception as e:
                    st.error(f"{mod.__name__}.{name} → errore: {e}")
                    return False, f"error:{name}"
        return False, "no-render-fn"


    MODULES = [
        ("core.site_meta", ["render_site_meta", "render"]),
        ("core.maps", ["render_map", "map_panel", "show_map", "main", "app", "render"]),
        ("core.dem_tools", ["render_dem", "dem_panel", "show_dem", "main", "app", "render"]),
        ("core.meteo", ["render_meteo", "panel_meteo", "run_meteo", "show_meteo", "main", "app", "render"]),
        ("core.wax_logic", ["render_wax", "wax_panel", "show_wax", "main", "app", "render"]),
    ]

    for modname, candidates in MODULES:
        mod = _load(modname)
        _ok, _used = _call_first(mod, candidates, T, ctx)

    if show_info:
        here = os.path.abspath(__file__)
        st.markdown(
            f"<div class='small'>Entrypoint: <code>{here}</code></div>",
            unsafe_allow_html=True,
        )

# ============================================================
# TAB 2 — RACE / GARE (FIS / FISI → tuning WC)
# ============================================================
with tab_race:
    st.markdown("### Modalità Gara · FIS / FISI → Tuning World Cup")

    # ---------- servizio calendari con cache ----------
    @st.cache_resource
    def get_calendar_service() -> RaceCalendarService:
        # client HTTP base (puoi personalizzare headers se FIS/FISI lo richiedono)
        def http_client_fis(url: str, params: dict) -> str:
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            return r.text

        def http_client_fisi(url: str, params_or_none) -> str:
            if params_or_none is None:
                r = requests.get(url, timeout=10)
            else:
                r = requests.get(url, params=params_or_none, timeout=10)
            r.raise_for_status()
            return r.text

        # DA COMPLETARE: slug reali dei comitati FISI.
        fisi_committee_slugs = {
            # "VALLE_D_AOSTA": "valdostano",   # <--- verifica lo slug corretto sul sito FISI
            # "PIEMONTE": "piemonte",
            # "ALPI_CENTRALI": "alpi-centrali",
            # "TRENTINO": "trentino",
            # "VENETO": "veneto",
            # ...
        }

        return RaceCalendarService(
            fis_provider=FISCalendarProvider(http_client=http_client_fis),
            fisi_provider=FISICalendarProvider(
                http_client=http_client_fisi,
                committee_slugs=fisi_committee_slugs,
            ),
        )

    calendar_service = get_calendar_service()

    # ---------- filtri base ----------
    col1, col2 = st.columns(2)
    with col1:
        season = st.number_input(
            "Stagione (anno di inizio)",
            min_value=2024,
            max_value=2035,
            value=2025,
            step=1,
        )

    with col2:
        fed_label = st.radio(
            "Federazione",
            ["FISI (Italia)", "FIS (World)", "Entrambe"],
            horizontal=True,
        )

    if fed_label.startswith("FISI"):
        federation = Federation.FISI
    elif fed_label.startswith("FIS (World)"):
        federation = Federation.FIS
    else:
        federation = None  # entrambe

    col3, col4 = st.columns(2)
    with col3:
        disc_label = st.selectbox(
            "Disciplina",
            ["Tutte", "SL", "GS", "SG", "DH"],
            index=1,
        )
    if disc_label == "Tutte":
        discipline = None
    else:
        discipline = Discipline[disc_label]

    with col4:
        region = st.text_input(
            "Regione FISI (opzionale, es. VALLE_D_AOSTA)",
            value="",
            help="Usata solo per FISI / comitati. Lascia vuoto per tutte.",
        )

    st.markdown("---")

    # ---------- carica gare ----------
    if st.button("🔍 Carica gare"):
        with st.spinner("Carico calendari gare..."):
            try:
                events = calendar_service.list_events(
                    season=season,
                    federation=federation,
                    discipline=discipline,
                    nation="ITA" if federation in (None, Federation.FISI) else None,
                    region=region or None,
                )
            except Exception as e:
                st.error(f"Errore nel caricamento delle gare: {e}")
                events = []

        if not events:
            st.info(
                "Nessuna gara trovata con questi filtri.\n\n"
                "Possibili cause: parser FISI/FIS da adattare alla struttura HTML reale "
                "oppure comitati/slug non ancora configurati."
            )
        else:
            st.success(f"Trovate {len(events)} gare.")

            # select gara
            selected_event = st.selectbox(
                "Seleziona una gara",
                options=events,
                format_func=lambda ev: f"[{ev.code}] {ev.name} · {ev.place} · {ev.start_date.isoformat()}",
            )

            if selected_event:
                if st.button("🎯 Calcola tuning WC per questa gara"):
                    res = get_wc_tuning_for_event(
                        selected_event,
                        skier_level=SkierLevel.WC,
                    )
                    if res is None:
                        st.warning("Questa gara non ha una disciplina riconosciuta (SL/GS/SG/DH).")
                    else:
                        params, data = res
                        st.subheader("Tuning World Cup suggerito")

                        c1, c2, c3 = st.columns(3)
                        c1.metric("Base bevel", f"{data['base_bevel_deg']:.2f}°")
                        c2.metric("Side bevel", f"{data['side_bevel_deg']:.2f}°")
                        c3.metric("Rischio", data["risk_level"])

                        st.markdown("#### Struttura & Sciolina")
                        st.write(f"**Struttura soletta:** {data['structure_pattern']}")
                        st.write(f"**Wax consigliato:** {data['wax_group']}")

                        st.markdown("#### Dettagli neve")
                        st.write(
                            f"Neve: **{data['snow_type']}**, "
                            f"T neve ≈ **{data['snow_temp_c']}°C**, "
                            f"T aria ≈ **{data['air_temp_c']}°C**, "
                            f"Injected: **{data['injected']}**"
                        )

                        st.markdown("#### Note tecniche")
                        st.write(data["notes"])

                        if show_info:
                            st.markdown("#### Debug evento")
                            st.json(data)
    else:
        st.info("Imposta i filtri e premi **“Carica gare”** per vedere il calendario.")
