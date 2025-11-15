# streamlit_app.py
# Telemark · Pro Wax & Tune — modalità standard + modalità gara (FIS ufficiale)

from __future__ import annotations

import sys
import os
import importlib
from typing import Any, Dict

import streamlit as st

# --- hard-reload pulito dei moduli core.* per evitare cache stale in dev ---
importlib.invalidate_caches()
for name in list(sys.modules.keys()):
    if name == "core" or name.startswith("core."):
        del sys.modules[name]

# --- import dal core (moduli esistenti) ---
from core.i18n import L
from core.search import location_searchbox

# nuovo modulo calendario FIS ufficiale
from core.fis_calendar import filter_fis_wc_races

# ============================================================
# CONFIG TEMA BASE
# ============================================================

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
html, body, .stApp { background:var(--bg); color:var(--fg); }
[data-testid="stHeader"] { background:transparent; }
section.main > div { padding-top:.6rem; }
h1,h2,h3,h4 { color:#fff; letter-spacing:.2px; }
hr { border:none; border-top:1px solid var(--line); margin:.75rem 0; }

.badge {
  display:inline-flex; align-items:center; gap:.5rem;
  background:#0b1220; border:1px solid #203045; color:#cce7f2;
  border-radius:12px; padding:.35rem .6rem; font-size:.85rem;
}
.small { color:#9aa4af; font-size:.9rem; }
.panel {
  background:var(--panel);
  border-radius:14px;
  padding:1rem 1.25rem;
  border:1px solid #111827;
}
</style>
""",
    unsafe_allow_html=True,
)

st.title("Telemark · Pro Wax & Tune")

# ============================================================
# LINGUA
# ============================================================

st.sidebar.markdown("### ⚙️")

lang = st.sidebar.selectbox(
    L["it"]["lang"] + " / " + L["en"]["lang"],
    ["IT", "EN"],
    index=0,
)

T = L["it"] if lang == "IT" else L["en"]
show_info = st.sidebar.toggle("Mostra info tecniche", value=False)


def tr(key: str, default: str) -> str:
    """
    Helper: legge una stringa dal dizionario T (chiavi annidate con 'a.b.c'),
    con fallback sicuro a 'default' se qualcosa manca.
    """
    if not isinstance(T, dict):
        return default
    cur: Any = T
    for part in key.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur if isinstance(cur, str) else default


# ============================================================
# TABS PRINCIPALI
# ============================================================

tab_wax, tab_race = st.tabs(["🧊 Wax & Tune", "🏁 Cup / FIS"])


# ============================================================
# TAB 1 — WAX & TUNE (STANDARD)
# ============================================================
with tab_wax:
    st.markdown(f"### 1) {T.get('search_ph', 'Cerca località / resort')}")

    # 1. ricerca località (usa già i tuoi provider / nominatim ecc.)
    lat, lon, place_label = location_searchbox(T)

    st.markdown(
        f"<div class='badge'>📍 <b>{place_label}</b> · "
        f"lat <b>{lat:.5f}</b>, lon <b>{lon:.5f}</b></div>",
        unsafe_allow_html=True,
    )

    # contesto base che passiamo ai moduli core.*
    ctx: Dict[str, Any] = {
        "lat": float(lat),
        "lon": float(lon),
        "place_label": place_label,
        "iso2": "",
        "lang": lang,
        "T": T,
    }
    st.session_state["_ctx"] = ctx

    st.markdown("### 2) Moduli")

    # loader dinamico dei moduli core.*
    def _load(modname: str):
        try:
            importlib.invalidate_caches()
            return importlib.import_module(modname)
        except Exception as e:  # noqa: BLE001
            st.error(f"Import fallito {modname}: {e}")
            return None

    def _call_first(mod, candidates, *args, **kwargs):
        if not mod:
            return False, "missing"
        for name in candidates:
            fn = getattr(mod, name, None)
            if callable(fn):
                try:
                    fn(*args, **kwargs)
                    return True, name
                except Exception as e:  # noqa: BLE001
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
        mod = _load(modname)
        _call_first(mod, candidates, T, ctx)

    if show_info:
        here = os.path.abspath(__file__)
        st.markdown(
            f"<div class='small'>Entrypoint: <code>{here}</code></div>",
            unsafe_allow_html=True,
        )


# ============================================================
# TAB 2 — CUP / FIS (CALENDARIO UFFICIALE)
# ============================================================
with tab_race:
    st.markdown("### Modalità gara · Calendario FIS (World Cup)")

    with st.container():
        col1, col2 = st.columns(2)
        with col1:
            season = st.number_input(
                "Stagione (anno di inizio)",
                min_value=2000,
                max_value=2100,
                value=2025,
                step=1,
            )

        with col2:
            gender_choice = st.radio(
                "Genere",
                ["Entrambi", "Uomini", "Donne"],
                horizontal=True,
            )

    disciplina_choice = st.selectbox(
        "Disciplina",
        ["Tutte", "SL", "GS", "SG", "DH", "AC"],
        index=2,  # default GS
    )

    # mapping UI → codice
    if gender_choice.startswith("Uom") or gender_choice.startswith("Men"):
        gender_code = "M"
    elif gender_choice.startswith("Don") or gender_choice.startswith("Women"):
        gender_code = "W"
    else:
        gender_code = None  # tutti

    disciplina_code = None if disciplina_choice == "Tutte" else disciplina_choice

    st.markdown("")

    if st.button("🔍 Carica gare FIS"):
        with st.spinner("Collego il calendario ufficiale FIS…"):
            try:
                races = filter_fis_wc_races(
                    season_start=int(season),
                    discipline=disciplina_code,
                    gender=gender_code,
                )
            except Exception as exc:  # noqa: BLE001
                st.error(
                    "Errore nel collegamento al calendario FIS.\n"
                    "Controlla la connessione oppure riprova tra qualche minuto."
                )
                if show_info:
                    st.exception(exc)
                races = []

        if not races:
            st.info(
                "Nessuna gara trovata con questi filtri.\n\n"
                "Prova a cambiare stagione / disciplina / genere. "
                "I dati sono presi in tempo reale dal sito FIS."
            )
        else:
            st.success(f"Trovate {len(races)} gare FIS di Coppa del Mondo.")

            # ordiniamo sulla stringa data (basta per avere un ordine coerente)
            races_sorted = sorted(races, key=lambda r: r.get("date", ""))

            # tabella compatta per l'overview
            table_data = {
                "Data": [r["date"] for r in races_sorted],
                "Località": [r["place"] for r in races_sorted],
                "Nazione": [r.get("nation", "") for r in races_sorted],
                "Evento": [r["event"] for r in races_sorted],
                "Genere": [r.get("gender", "") for r in races_sorted],
            }

            st.markdown("#### Calendario Coppa del Mondo (fonte: FIS)")
            st.dataframe(table_data, use_container_width=True)

            # selezione singola gara (per future integrazioni tuning WC)
            st.markdown("---")
            st.markdown("#### Dettaglio gara")

            labels = [
                f"{r['date']} · {r['place']} ({r.get('nation', '')}) · {r['event']}"
                for r in races_sorted
            ]
            selected_idx = st.selectbox(
                "Seleziona una gara per i dettagli (e in futuro per il tuning WC):",
                options=list(range(len(races_sorted))),
                format_func=lambda i: labels[i],
            )
            selected = races_sorted[selected_idx]

            with st.container():
                st.markdown("<div class='panel'>", unsafe_allow_html=True)
                st.markdown(f"**Data:** {selected['date']}")
                st.markdown(
                    f"**Località:** {selected['place']}  "
                    f"({selected.get('nation', '')})"
                )
                st.markdown(f"**Evento:** {selected['event']}")
                if selected.get("gender"):
                    st.markdown(f"**Genere:** {selected['gender']}")
                if show_info:
                    st.markdown("**Debug row FIS:**")
                    st.code(selected.get("row_raw", ""), language="text")
                st.markdown("</div>", unsafe_allow_html=True)

            st.caption(
                "Calendario ottenuto dal database ufficiale FIS "
                "(categoria **WC**, settore **AL**)."
            )
    else:
        st.info("Imposta filtri e premi **“Carica gare FIS”** per vedere il calendario.")
