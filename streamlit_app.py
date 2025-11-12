# streamlit_app.py — BUILD v7-clean
# Telemark · Pro Wax & Tune — orchestratore pulito (ordine 2→3→4, niente debug/moduli)

import sys, importlib
import streamlit as st

# ---------- theme ----------
st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown("""
<style>
:root { --bg:#0b0f13; --panel:#121821; --muted:#9aa4af; --fg:#e5e7eb; --line:#1f2937; }
html, body, .stApp { background:var(--bg); color:#e5e7eb; }
[data-testid="stHeader"] { background:transparent; }
section.main > div { padding-top: .6rem; }
h1,h2,h3,h4 { color:#fff; letter-spacing:.2px }
.badge { display:inline-flex; align-items:center; gap:.5rem; background:#0b1220;
  border:1px solid #203045; color:#cce7f2; border-radius:12px; padding:.35rem .6rem; font-size:.85rem; }
</style>
""", unsafe_allow_html=True)

st.title("Telemark · Pro Wax & Tune")
st.caption("BUILD v7-clean · entrypoint = streamlit_app.py")

# ---------- hard reload + clear cache ----------
colr,_ = st.columns([1,3])
with colr:
    if st.button("Force hard reload", help="Svuota cache e ricarica core.*"):
        try:
            st.cache_data.clear()
            st.cache_resource.clear()
        except Exception:
            pass
        importlib.invalidate_caches()
        for n in list(sys.modules.keys()):
            if n == "core" or n.startswith("core."):
                del sys.modules[n]
        st.rerun()

# ---------- import core (dopo eventuale clear) ----------
from core.i18n import L
from core.search import country_selectbox, location_searchbox
try:
    from core.search import reverse_geocode as _revgeo
except Exception:
    _revgeo = None

# ---------- lingua ----------
st.sidebar.markdown("### ⚙️")
lang = st.sidebar.selectbox(L["it"]["lang"]+" / "+L["en"]["lang"], ["IT","EN"], index=0)
T = L["it"] if lang=="IT" else L["en"]

# ---------- 1) Ricerca località ----------
st.markdown(f"### 1) {T['search_ph']}")
iso2 = country_selectbox(T)
_res = location_searchbox(T, iso2)

lat  = float(st.session_state.get("lat", 45.831))
lon  = float(st.session_state.get("lon", 7.730))
plab = st.session_state.get("place_label", "🇮🇹  Champoluc, Valle d’Aosta — IT")

if isinstance(_res, tuple) and len(_res)==3:
    try:
        lat, lon, plab = float(_res[0]), float(_res[1]), str(_res[2])
    except Exception:
        pass
elif isinstance(_res, str) and "|||" in _res and "_options" in st.session_state:
    info = (getattr(st.session_state, "_options", {}) or {}).get(_res, {})
    lat = float(info.get("lat", lat)); lon = float(info.get("lon", lon)); plab = str(info.get("label", plab))

st.session_state["lat"] = lat
st.session_state["lon"] = lon
st.session_state["place_label"] = plab

st.markdown(f"<div class='badge'>📍 <b>{plab}</b> · lat <b>{lat:.5f}</b>, lon <b>{lon:.5f}</b></div>", unsafe_allow_html=True)

ctx = {"lat": lat, "lon": lon, "place_label": plab, "iso2": iso2, "lang": lang, "T": T}
st.session_state["_ctx"] = ctx

# ---------- helpers ----------
def _load(modname: str):
    try:
        importlib.invalidate_caches()
        return importlib.import_module(modname)
    except Exception as e:
        st.error(f"Import fallito {modname}: {e}")
        return None

def _call_first(mod, names, *args, **kwargs):
    if not mod: return False
    for n in names:
        fn = getattr(mod, n, None)
        if callable(fn):
            fn(*args, **kwargs); return True
    st.warning(f"Nessuna funzione di render trovata in {mod.__name__}")
    return False

# ---------- 2) Meteo & calcolo ----------
st.markdown("### 2) " + (T.get("status_title","Meteo & calcolo")))
m_meteo = _load("core.meteo")
_call_first(m_meteo, ["render_meteo","panel_meteo","run_meteo","show_meteo","main","app","render"], T, ctx)

# ---------- 3) Scioline & tuning ----------
st.markdown("### 3) Scioline & tuning")
m_wax = _load("core.wax_logic")
_call_first(m_wax, ["render_wax","wax_panel","show_wax","main","app","render"], T, ctx)

# ---------- 4) Mappa (selezione) ----------
st.markdown("### 4) " + T.get("map","Mappa"))
m_map = _load("core.maps")
_call_first(m_map, ["render_map","map_panel","show_map","main","app","render"], T, ctx)

# se la mappa ha aggiornato le coord., aggiorna label
if st.session_state.get("_last_click"):
    lat = float(st.session_state.get("lat", lat))
    lon = float(st.session_state.get("lon", lon))
    if callable(_revgeo):
        try:
            plab = _revgeo(lat, lon); st.session_state["place_label"] = plab
        except Exception:
            pass
    st.markdown(f"<div class='badge'>📍 <b>{plab}</b> · lat <b>{lat:.5f}</b>, lon <b>{lon:.5f}</b></div>", unsafe_allow_html=True)

# ---------- 5) DEM ----------
m_dem = _load("core.dem_tools")
_call_first(m_dem, ["render_dem","dem_panel","show_dem","main","app","render"], T, ctx)
