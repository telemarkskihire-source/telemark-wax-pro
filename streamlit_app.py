# streamlit_app.py
# Telemark · Pro Wax & Tune — main entry

import streamlit as st

from core.i18n import L
from core.search import country_selectbox, location_searchbox, get_current_selection

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
  --bg:#0b0f13;
  --panel:#121821;
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
  padding-top: 0.6rem;
}}
h1,h2,h3,h4 {{
  color:#fff;
  letter-spacing: .2px;
}}
.card {{
  background: var(--panel);
  border:1px solid var(--line);
  border-radius:12px;
  padding: .9rem .95rem;
}}
.small {{
  font-size:.85rem;
  color:#cbd5e1;
}}
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------- SIDEBAR: LINGUA ----------------------
st.sidebar.markdown("### ⚙️")

lang = st.sidebar.selectbox(
    L["it"]["lang"] + " / " + L["en"]["lang"],
    ["IT", "EN"],
    index=0,
)
T = L["it"] if lang == "IT" else L["en"]

st.title("Telemark · Pro Wax & Tune")

# ---------------------- 1) PAESE + RICERCA LOCALITÀ -------------------
st.markdown("#### 🌍 Località")

iso2 = country_selectbox(T)
sel = location_searchbox(T, iso2=iso2)

current = get_current_selection()
if current:
    st.markdown(
        f"""<div class="card">
        <div class="small">Località selezionata</div>
        <strong>{current['label']}</strong><br>
        <span class="small">lat {current['lat']:.5f}, lon {current['lon']:.5f}</span>
        </div>""",
        unsafe_allow_html=True,
    )

# ---------------------- FUTURO: MAPPA, PENDENZA, OMBRA, TUNING, ECC. -------------------
# Qui in seguito richiameremo i moduli:
#   - core.maps   → mappa interattiva + selezione pista + pendenza / ombreggiatura
#   - core.tuning → logica sciolina / setup sci
#   - core.charts → grafici
