# streamlit_app.py
# Telemark · Pro Wax & Tune — modalità standard + calendario FIS (World Cup)

import os
import sys
import importlib

import streamlit as st

# --- import core ---
from core.i18n import L
from core.search import location_searchbox
from core.fis_calendar import get_fis_calendar


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

# ============================================================
# LINGUA & OPZIONI
# ============================================================

st.sidebar.markdown("### ⚙️")

lang = st.sidebar.selectbox(
    L["it"]["lang"] + " / " + L["en"]["lang"],
    ["IT", "EN"],
    index=0,
)

T = L["it"] if lang == "IT" else L["en"]
show_info = st.sidebar.toggle("Mostra info tecniche", value=False)

# ============================================================
# TABS PRINCIPALI
# ============================================================

tab_wax, tab_fis = st.tabs(
    [
        "🧊 Wax & Tune",
        "🏁 Cup / FIS",
    ]
)

# ============================================================
# TAB 1 — WAX & TUNE
# ============================================================

with tab_wax:
    st.markdown(f"### 1) {T['search_ph']}")

    # Ricerca località (OpenStreetMap / Nominatim)
    lat, lon, place_label = location_searchbox(T)

    st.markdown(
        f"<div class='badge'>📍 <b>{place_label}</b> · "
        f"lat <b>{lat:.5f}</b>, lon <b>{lon:.5f}</b></div>",
        unsafe_allow_html=True,
    )

    # Contesto condiviso per i moduli core.*
    ctx = {
        "lat": float(lat),
        "lon": float(lon),
        "place_label": place_label,
        "iso2": "",
        "lang": lang,
        "T": T,
    }
    st.session_state["_ctx"] = ctx

    st.markdown("### 2) Moduli")

    def _load_module(modname: str):
        """Import semplice (senza giochetti di cache) per la versione deploy."""
        try:
            return importlib.import_module(modname)
        except Exception as e:
            st.error(f"Import fallito: `{modname}` → {e}")
            return None

    def _call_first_render(mod, candidates, *args, **kwargs):
        """Cerca la prima funzione 'render' tra i nomi candidati e la esegue."""
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
        ("core.meteo", ["render_meteo", "panel_meteo", "run_meteo", "show_meteo", "main", "app", "render"]),
        ("core.wax_logic", ["render_wax", "wax_panel", "show_wax", "main", "app", "render"]),
        ("core.maps", ["render_map", "map_panel", "show_map", "main", "app", "render"]),
        ("core.dem_tools", ["render_dem", "dem_panel", "show_dem", "main", "app", "render"]),
        ("core.pov_video", ["render_pov_video", "render", "main", "app"]),
    ]

    for modname, candidates in MODULES:
        mod = _load_module(modname)
        _ok, _used = _call_first_render(mod, candidates, T, ctx)

    if show_info:
        here = os.path.abspath(__file__)
        st.markdown(
            f"<div class='small'>Entrypoint: <code>{here}</code></div>",
            unsafe_allow_html=True,
        )

# ============================================================
# TAB 2 — CUP / FIS (WORLD CUP)
# ============================================================

with tab_fis:
    st.markdown("### Modalità gara · Calendario FIS (World Cup)")

    col1, col2 = st.columns(2)

    with col1:
        season = st.number_input(
            "Stagione (anno di inizio)",
            min_value=2023,
            max_value=2030,
            value=2025,
            step=1,
        )

    with col2:
        gender_label = st.radio(
            "Genere",
            ["Entrambi", "Uomini", "Donne"],
            index=0,
            horizontal=True,
        )

    if gender_label.startswith("Uom"):
        gender_code = "M"
    elif gender_label.startswith("Don"):
        gender_code = "W"
    else:
        gender_code = None

    disc_label = st.selectbox(
        "Disciplina",
        ["Tutte", "SL", "GS", "SG", "DH", "AC"],
        index=0,
    )
    discipline_code = None if disc_label == "Tutte" else disc_label

    st.markdown("---")

    if st.button("🔍 Carica gare FIS"):
        with st.spinner("Scarico calendario FIS dal proxy Telemark..."):
            try:
                events = get_fis_calendar(
                    season=int(season),
                    discipline=discipline_code,
                    gender=gender_code,
                )
            except Exception as e:
                st.error(f"Errore nel caricamento del calendario FIS: {e}")
                events = []

        if not events:
            st.info(
                "Nessuna gara trovata con questi filtri.\n\n"
                "I dati sono presi **in tempo reale** dal sito FIS tramite proxy "
                "`telemarkskihire.com`.\n"
                "Prova a cambiare stagione / disciplina / genere."
            )
        else:
            st.success(f"Trovate **{len(events)}** gare in calendario.")

            # Tabella riassuntiva
            import pandas as pd

            df = pd.DataFrame(events)
            df = df[["date", "place", "nation", "event", "gender"]]

            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
            )

            # Selezione singola gara (per future integrazioni tuning WC)
            st.markdown("#### Seleziona una gara")

            def _fmt_row(row):
                return f"{row['date']} · {row['place']} · {row['event']}"

            options = list(range(len(events)))
            labels = [_fmt_row(ev) for ev in events]

            idx = st.selectbox(
                "Gara",
                options=options,
                format_func=lambda i: labels[i],
            )

            selected = events[idx]
            st.markdown(
                f"**Gara scelta:** {selected['date']} · {selected['place']} "
                f"· {selected['event']} ({selected['gender'] or 'M/W'})"
            )

            if show_info:
                st.markdown("##### Debug evento selezionato")
                st.json(selected)
    else:
        st.info("Imposta i parametri e premi **“Carica gare FIS”** per vedere il calendario.")
