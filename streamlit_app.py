# streamlit_app.py
# Telemark · Pro Wax & Tune — orchestratore minimale e in ordine (no banner debug)

import sys, os, importlib
import streamlit as st

# --- hard-reload silenzioso del pacchetto core.* per evitare cache stale ---
importlib.invalidate_caches()
for name in list(sys.modules.keys()):
    if name == "core" or name.startswith("core."):
        del sys.modules[name]

# --- import puliti dal core ---
from core.i18n import L
from core.search import location_searchbox

# ---------- THEME ----------
st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown("""
<style>
:root { --bg:#0b0f13; --panel:#121821; --muted:#9aa4af; --fg:#e5e7eb; --line:#1f2937; }
html, body, .stApp { background:var(--bg); color:var(--fg); }
[data-testid="stHeader"] { background:transparent; }
section.main > div { padding-top:.6rem; }
h1,h2,h3,h4 { color:#fff; letter-spacing:.2px }
hr { border:none; border-top:1px solid var(--line); margin:.75rem 0 }
.badge { display:inline-flex; align-items:center; gap:.5rem; background:#0b1220; border:1px solid #203045; color:#cce7f2;
         border-radius:12px; padding:.35rem .6rem; font-size:.85rem; }
.small { color:#9aa4af; font-size:.9rem; }
</style>
""", unsafe_allow_html=True)

st.title("Telemark · Pro Wax & Tune")

# ---------- LINGUA ----------
st.sidebar.markdown("### ⚙️")
lang = st.sidebar.selectbox(L["it"]["lang"]+" / "+L["en"]["lang"], ["IT","EN"], index=0)
T = L["it"] if lang == "IT" else L["en"]
show_info = st.sidebar.toggle("Mostra info tecniche", value=False)

# ---------- 1) RICERCA LOCALITÀ ----------
st.markdown(f"### 1) {T['search_ph']}")

# nuova API: niente paese, solo searchbox globale
lat, lon, place_label = location_searchbox(T)

# Badge posizione
st.markdown(
    f"<div class='badge'>📍 <b>{place_label}</b> · lat <b>{lat:.5f}</b>, lon <b>{lon:.5f}</b></div>",
    unsafe_allow_html=True
)

# ---------- CONTEXT condiviso per i moduli ----------
# iso2 non c'è più → lo mettiamo vuoto per compatibilità con moduli già scritti
ctx = {"lat": lat, "lon": lon, "place_label": place_label, "iso2": "", "lang": lang, "T": T}
st.session_state["_ctx"] = ctx

# ---------- 2) MODULI ----------
st.markdown("### 2) Moduli")

def _load(modname: str):
    try:
        importlib.invalidate_caches()
        return importlib.import_module(modname)
    except Exception as e:
        st.error(f"Import fallito {modname}: {e}")
        return None

def _call_first(mod, candidates, *args, **kwargs):
    if not mod:
        return False, "missing"
    for n in candidates:
        fn = getattr(mod, n, None)
        if callable(fn):
            try:
                fn(*args, **kwargs)
                return True, n
            except Exception as e:
                st.error(f"{mod.__name__}.{n} → errore: {e}")
                return False, f"error:{n}"
    return False, "no-render-fn"

MODULES = [
    ("core.site_meta", ["render_site_meta","render"]),            # Altitudine/TZ/DEM
    ("core.maps",      ["render_map","map_panel","show_map","main","app","render"]),
    ("core.dem_tools", ["render_dem","dem_panel","show_dem","main","app","render"]),
    ("core.meteo",     ["render_meteo","panel_meteo","run_meteo","show_meteo","main","app","render"]),
    ("core.wax_logic", ["render_wax","wax_panel","show_wax","main","app","render"]),
]

for modname, candidates in MODULES:
    mod = _load(modname)
    ok, used = _call_first(mod, candidates, T, ctx)
    # nessun banner: se tutto ok, silenzio; errori mostrati riga rossa

# ---------- nota tecnica opzionale ----------
if show_info:
    here = os.path.abspath(__file__)
    st.markdown(f"<div class='small'>Entrypoint: <code>{here}</code></div>", unsafe_allow_html=True)
