# streamlit_app.py
# Telemark · Pro Wax & Tune
# - Ricerca località (quota > 1000 m + alias Telemark)
# - Mappa & piste sci alpino
# - Pendenza, esposizione, ombreggiatura + altitudine modificabile

import sys
import importlib
import inspect

import streamlit as st

# --- hard-reload moduli core.* per evitare cache vecchie ---
importlib.invalidate_caches()
for name in list(sys.modules.keys()):
    if name == "core" or name.startswith("core."):
        del sys.modules[name]

# --- import dai moduli core ---
from core.i18n import L
from core.search import (
    country_selectbox,
    location_searchbox,
    get_current_selection,
    VERSION as SEARCH_VERSION,
)
from core.maps import render_map

# modulo DEM / pendenza & ombreggiatura
try:
    from core.dem_tools import render_slope_shade_panel
    HAS_DEM_TOOLS = True
except Exception:
    HAS_DEM_TOOLS = False

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
  --bg:#05070b;
  --panel:#111827;
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
  padding-top: 0.5rem;
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
  border-radius:14px;
  padding: .9rem .95rem;
}}
.small {{
  font-size:.85rem;
  color:#cbd5e1;
}}
.badge {{
  display:inline-flex;
  align-items:center;
  gap:.4rem;
  background:#020617;
  border:1px solid #1f2937;
  border-radius:999px;
  padding:.18rem .55rem;
  font-size:.78rem;
  color:#e5e7eb;
}}
.section-title {{
  display:flex;
  align-items:center;
  justify-content:space-between;
}}
.section-title span {{
  font-size:.8rem;
  color:#9ca3af;
}}
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------- SIDEBAR ----------------------
st.sidebar.markdown("### ⚙️ Impostazioni")

lang = st.sidebar.selectbox(
    "Lingua / Language",
    ["IT", "EN"],
    index=0,
)
T = L["it"] if lang == "IT" else L["en"]

# debug
import core.search as search_mod

search_path = inspect.getfile(search_mod)
st.sidebar.markdown("---")
st.sidebar.markdown("### 🧪 Debug")
st.sidebar.text(f"Modulo search path:\n{search_path}")
st.sidebar.text(f"Search.VERSION:\n{getattr(search_mod, 'VERSION', 'NO VERSION')}")
st.sidebar.text(f"DEM tools:\n{'OK' if HAS_DEM_TOOLS else 'NOT INSTALLED'}")

# ---------------------- HEADER ----------------------
st.title("Telemark · Pro Wax & Tune")

# context condiviso
ctx = {"lang": lang}

# ---------------------- 1) LOCALITÀ ----------------------
st.markdown("## 🌍 Località")

with st.container():
    col1, col2 = st.columns([1, 2])

    with col1:
        iso2 = country_selectbox(T)

    with col2:
        location_searchbox(T, iso2)

    sel = get_current_selection()
    if sel:
        ctx["lat"] = float(sel["lat"])
        ctx["lon"] = float(sel["lon"])
        ctx["place_label"] = sel["label"]

        # Nessuna lat/lon in UI
        st.markdown(f"**Località selezionata:** {sel['label']}")
    else:
        st.warning("Seleziona una località per continuare.")
        st.stop()

st.markdown("---")

# ---------------------- 4) MAPPA & PISTE ----------------------
st.markdown(
    f'<div class="section-title"><h2>4) Mappa & piste</h2>'
    f'<span>{ctx["place_label"]}</span></div>',
    unsafe_allow_html=True,
)

render_map(T, ctx)

st.markdown("---")

# ---------------------- 5) Pendenza & ombreggiatura ----------------------
st.markdown("## 5) Pendenza & ombreggiatura")

if HAS_DEM_TOOLS:
    try:
        render_slope_shade_panel(T, ctx)
    except Exception as e:
        st.error(f"Errore modulo DEM/pendenza: {e}")
else:
    st.info(
        "Modulo pendenza / ombreggiatura non attivo in questo ambiente.\n"
        "Verrà abilitato quando core.dem_tools sarà disponibile."
    )
