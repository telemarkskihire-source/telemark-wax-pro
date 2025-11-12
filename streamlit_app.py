# streamlit_app.py
# Telemark · Pro Wax & Tune — main (solo ricerca + tema)
import streamlit as st
from datetime import date

# === IMPORT MODULI CORE ===
# Richiede: core/__init__.py (anche vuoto), core/i18n.py con dizionario L,
#           core/search.py (qui sotto).
from core.i18n import L
from core.search import COUNTRIES, country_selectbox, location_searchbox, get_current_selection

# ---------- THEME (dark) ----------
PRIMARY = "#06b6d4"; ACCENT  = "#f97316"; OK = "#10b981"; WARN = "#f59e0b"; ERR = "#ef4444"
st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{ --bg:#0b0f13; --panel:#121821; --muted:#9aa4af; --fg:#e5e7eb; --line:#1f2937; }}
html, body, .stApp {{ background:var(--bg); color:var(--fg); }}
[data-testid="stHeader"] {{ background:transparent; }}
section.main > div {{ padding-top: 0.6rem; }}
h1,h2,h3,h4 {{ color:#fff; letter-spacing: .2px }}
hr {{ border:none; border-top:1px solid var(--line); margin:.75rem 0 }}
.badge {{ display:inline-flex; align-items:center; gap:.5rem; background:#0b1220; border:1px solid #203045; color:#cce7f2; border-radius:12px; padding:.35rem .6rem; font-size:.85rem; }}
.card {{ background: var(--panel); border:1px solid var(--line); border-radius:12px; padding: .9rem .95rem; }}
.small {{ font-size:.9rem; color:#cbd5e1 }}
</style>
""", unsafe_allow_html=True)

# ---------- I18N + SIDEBAR ----------
st.sidebar.markdown("### ⚙️")
lang = st.sidebar.selectbox(L["it"]["lang"]+" / "+L["en"]["lang"], ["IT","EN"], index=0)
T = L["it"] if lang == "IT" else L["en"]

st.title("Telemark · Pro Wax & Tune")

# ---------- BLOCCO 1: Ricerca località ----------
st.markdown(f"### 1) {T['search_ph']}")
col = st.columns([2,1])
with col[1]:
    iso2 = country_selectbox(T)  # selectbox con paesi
with col[0]:
    selection = location_searchbox(T, iso2)  # searchbox con suggerimenti veloci

sel = get_current_selection()  # dict: {lat, lon, label, source}

if sel:
    st.markdown(
        f"<div class='badge'>📍 <b>{sel['label']}</b> · "
        f"lat <b>{sel['lat']:.5f}</b>, lon <b>{sel['lon']:.5f}</b> · src <i>{sel['source']}</i></div>",
        unsafe_allow_html=True
    )
else:
    st.info("Digita almeno 2–3 caratteri per vedere i suggerimenti.")

# ---------- MESSAGGIO DI PROSSIMI STEP ----------
st.markdown(
    "<div class='card small'>OK: ricerca località separata in modulo. "
    "Prossimo step: spostiamo meteo e mappa nei moduli <code>core/</code>.</div>",
    unsafe_allow_html=True
)
