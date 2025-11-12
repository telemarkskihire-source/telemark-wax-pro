# streamlit_app.py
# Telemark · Pro Wax & Tune — orchestratore con DEBUG per core/*

import os, sys, importlib, importlib.util
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
.block { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:.9rem .95rem; margin:.6rem 0; }
.small { color:#9aa4af; font-size:.9rem; }
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

_res = location_searchbox(T, iso2)  # può restituire tupla / chiave / None

# Defaults/persistiti
lat = float(st.session_state.get("lat", 45.831))
lon = float(st.session_state.get("lon", 7.730))
place_label = st.session_state.get("place_label", "🇮🇹  Champoluc, Valle d’Aosta — IT")

# Normalizzazione output
if isinstance(_res, tuple) and len(_res) == 3:
    try:
        lat, lon, place_label = float(_res[0]), float(_res[1]), str(_res[2])
        st.session_state["lat"], st.session_state["lon"], st.session_state["place_label"] = lat, lon, place_label
    except Exception:
        pass
elif isinstance(_res, str) and "|||" in _res and "_options" in st.session_state:
    info = (getattr(st.session_state, "_options", {}) or {}).get(_res, {})
    lat = float(info.get("lat", lat)); lon = float(info.get("lon", lon))
    place_label = str(info.get("label", place_label))
    st.session_state["lat"], st.session_state["lon"], st.session_state["place_label"] = lat, lon, place_label

st.markdown(
    f"<div class='badge'>📍 <b>{place_label}</b> · lat <b>{lat:.5f}</b>, lon <b>{lon:.5f}</b></div>",
    unsafe_allow_html=True
)

# ---------- CONTEXT condiviso ----------
ctx = {"lat": lat, "lon": lon, "place_label": place_label, "iso2": iso2, "lang": lang, "T": T}
st.session_state["_ctx"] = ctx

# ---------- 2) MODULI + DEBUG ----------
st.markdown("## 2) Moduli")

MODULES = [
    ("core.meteo",     ["render_meteo", "panel_meteo", "run_meteo", "show_meteo", "main", "app", "render"]),
    ("core.wax_logic", ["render_wax", "wax_panel", "show_wax", "main", "app", "render"]),
    ("core.maps",      ["render_map", "map_panel", "show_map", "main", "app", "render"]),
    ("core.dem_tools", ["render_dem", "dem_panel", "show_dem", "main", "app", "render"]),
]

# Mostra path e contenuto di core/
st.markdown("#### Debug pacchetto `core`")
core_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "core"))
st.code(f"sys.path[0]={os.path.abspath(os.getcwd())}\ncore_path={core_path}")
try:
    st.write("Contenuto core/:", os.listdir(core_path))
except Exception as e:
    st.warning(f"Impossibile leggere core/: {e}")

def _find_spec(modname: str):
    try:
        return importlib.util.find_spec(modname)
    except Exception:
        return None

def _load(modname: str):
    try:
        return importlib.import_module(modname)
    except Exception as e:
        st.error(f"🔴 Import fallito {modname}: {e}")
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
                st.exception(e)
                return False, f"error:{n}"
    return False, "no-render-fn"

statuses = []
for modname, candidates in MODULES:
    st.markdown(f"<div class='block'><b>{modname}</b></div>", unsafe_allow_html=True)
    spec = _find_spec(modname)
    if not spec:
        st.warning(f"🟡 Spec NON trovato per {modname} (file mancante o __init__.py assente?).")
        statuses.append((modname, False, "spec-missing"))
        continue

    st.write("• spec trovato:", spec.origin)
    mod = _load(modname)
    ok, used = _call_first(mod, candidates, T, ctx)
    if ok:
        st.success(f"✅ funzione usata: `{used}`")
    else:
        st.info(f"⏭️ nessuna funzione tra {candidates} trovata. Aggiungi in fondo al file, per esempio:")
        # suggerimento semplice per export
        base = ("render_meteo" if modname.endswith("meteo") else
                "render_wax" if modname.endswith("wax_logic") else
                "render_map" if modname.endswith("maps") else
                "render_dem")
        snippet = f"""def {base}(T, ctx):
    import streamlit as st
    st.markdown("**[{modname.split('.')[-1]}]** pronto (stub).")
render = {base}
"""
        st.code(snippet, language="python")
    statuses.append((modname, ok, used))

with st.expander("Stato moduli caricati", expanded=True):
    for modname, ok, used in statuses:
        st.write(("✅" if ok else "⏭️"), modname, "→", used)
