# streamlit_app.py
# Telemark · Pro Wax & Tune — main entry, delega la logica ai moduli core/*

import streamlit as st

from core.i18n import L          # il tuo dizionario di testi IT/EN
from core.search import location_searchbox   # modulo di ricerca località

# ---------------------- PAGE CONFIG & THEME ----------------------
PRIMARY = "#06b6d4"
ACCENT  = "#f97316"
OK      = "#10b981"
WARN    = "#f59e0b"
ERR     = "#ef4444"

st.set_page_config(
    page_title="Telemark · Pro Wax & Tune",
    page_icon="❄️",
    layout="wide",
)

# CSS dark minimale
st.markdown(f"""
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
hr {{
  border:none;
  border-top:1px solid var(--line);
  margin:.75rem 0;
}}
.badge {{
  display:inline-flex;
  align-items:center;
  gap:.5rem;
  background:#0b1220;
  border:1px solid #203045;
  color:#cce7f2;
  border-radius:12px;
  padding:.35rem .6rem;
  font-size:.85rem;
}}
.card {{
  background: var(--panel);
  border:1px solid var(--line);
  border-radius:12px;
  padding: .9rem .95rem;
}}
.banner {{
  border-left: 6px solid {ACCENT};
  background:#1a2230;
  color:#e2e8f0;
  padding:.75rem .9rem;
  border-radius:10px;
  font-size:.98rem;
}}
.small {{
  font-size:.85rem;
  color:#cbd5e1;
}}
</style>
""", unsafe_allow_html=True)

# ---------------------- SIDEBAR: LINGUA ----------------------
st.sidebar.markdown("### ⚙️")

lang = st.sidebar.selectbox(
    L["it"]["lang"] + " / " + L["en"]["lang"],
    ["IT", "EN"],
    index=0,
)

T = L["it"] if lang == "IT" else L["en"]

st.title("Telemark · Pro Wax & Tune")

# ---------------------- 1) RICERCA LOCALITÀ -------------------
# Tutta la UI della ricerca è nel modulo core.search
location_searchbox(T)

# In futuro: qui richiameremo anche core.meteo, core.map, ecc.
