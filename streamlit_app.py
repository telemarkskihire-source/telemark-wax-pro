# streamlit_app.py
# Telemark · Pro Wax & Tune — orchestratore modulare per i moduli esistenti in core/

import importlib
import streamlit as st
from core.i18n import L
from core.search import COUNTRIES, country_selectbox, location_searchbox

# ---------- THEME ----------
st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown("""
<style>
:root { --bg:#0b0f13; --panel:#121821; --muted:#9aa4af; --fg:#e5e7eb; --line:#1f2937; }
html, body, .stApp { background:var(--bg); color:var(--fg); }
[data-testid="stHeader"] { background:transparent; }
section.main > div { padding-top: .6rem; }
h1,h2,h3,h4 { color:#fff; letter-spacing:.2px }
hr { border:none; border-top:1px solid var(--line); margin:.75rem 0 }
.badge { display:inline-flex; align-items:center; gap:.5rem; background:#0b1220;
  border:1px solid #203045; color:#cce7f2; border-radius:12px; padding:.35rem .6rem; font-size:.85rem; }
.note { color:#9aa4af; font-size:.9rem; }
</style>
""", unsafe_allow_html=True)

st.title("Telemark · Pro Wax & Tune")

# ---------- LINGUA ----------
st.sidebar.markdown("### ⚙️")
lang = st.sidebar.selectbox(L["it"]["lang"]+" / "+L["en"]["lang"], ["IT","EN"], index=0)
T = L["it"] if lang == "IT" else L["en"]

# ---------- 1) RICERCA LOCALITÀ ----------
st.markdown(f"### 1) {T['search_ph']}")
iso2 = country_selectbox(T)

# Normalizza qualunque output di location_searchbox in (lat, lon, label)
_res = location_searchbox(T, iso2)

lat = float(st.session_state.get("lat", 45.831))
lon = float(st.session_state.get("lon", 7.730))
place_label = st.session_state.get("place_label", "🇮🇹  Champoluc, Valle d’Aosta — IT")

if isinstance(_res, tuple) and len(_res) == 3:
    try:
        lat, lon, place_label = float(_res[0]), float(_res[1]), str(_res[2])
        st.session_state["lat"], st.session_state["lon"], st.session_state["place_label"] = lat, lon, place_label
    except Exception:
        pass
elif isinstance(_res, str) and "|||" in _res and "_options" in st.session_state:
    info = (getattr(st.session_state, "_options", {}) or {}).get(_res, {})
    lat = float(info.get("lat", lat))
    lon = float(info.get("lon", lon))
    place_label = str(info.get("label", place_label))
    st.session_state["lat"], st.session_state["lon"], st.session_state["place_label"] = lat, lon, place_label

st.markdown(
    f"<div class='badge'>📍 <b>{place_label}</b> · "
    f"lat <b>{lat:.5f}</b>, lon <b>{lon:.5f}</b></div>",
    unsafe_allow_html=True
)

# ---------- CONTEXT condiviso per i moduli ----------
ctx = {
    "lat": lat,
    "lon": lon,
    "place_label": place_label,
    "iso2": iso2,
    "lang": lang,
    "T": T,
}
st.session_state["_ctx"] = ctx  # i moduli possono leggerlo/aggiornarlo

# ---------- LOADER MODULI ----------
def _load(modname: str):
    try:
        return importlib.import_module(modname)
    except Exception:
        return None

def _call_first(mod, names, *args, **kwargs):
    """Chiama la prima funzione disponibile tra 'names' nel modulo, senza crash."""
    if not mod:
        return False, "missing"
    for n in names:
        fn = getattr(mod, n, None)
        if callable(fn):
            try:
                fn(*args, **kwargs)
                return True, n
            except Exception as e:
                st.error(f"{mod.__name__}.{n} → errore: {e}")
                return False, f"error:{n}"
    return False, "no-render-fn"

# ---------- 2) ORCHESTRAZIONE: chiama i moduli esistenti ----------
st.markdown("### 2) Moduli")

MODULES = [
    # (modulo, candidati funzione di rendering)
    ("core.meteo",     ["render_meteo", "panel_meteo", "run_meteo", "render"]),
    ("core.wax_logic", ["render_wax", "wax_panel", "render"]),
    ("core.maps",      ["render_map", "map_panel", "show_map", "render"]),
    ("core.dem_tools", ["render_dem", "dem_panel", "show_dem", "render"]),
]

loaded = []
for modname, candidates in MODULES:
    mod = _load(modname)
    ok, used = _call_first(mod, candidates, T, ctx)
    loaded.append((modname, ok, used))

# ---------- RIEPILOGO ----------
with st.expander("Stato moduli caricati", expanded=False):
    for modname, ok, used in loaded:
        if ok:
            st.markdown(f"- **{modname}** → `.{used}`")
        else:
            st.markdown(f"- **{modname}** → *(non disponibile: {used})*")

st.markdown(
    "<div class='note'>Ogni modulo dovrebbe esporre una funzione "
    "<code>render_*(T, ctx)</code> (o uno degli alias supportati). "
    "I moduli possono usare/aggiornare <code>st.session_state['_ctx']</code> per condividere dati.</div>",
    unsafe_allow_html=True
)
