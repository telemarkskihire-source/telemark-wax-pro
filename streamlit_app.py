# streamlit_app.py
# Telemark · Pro Wax & Tune — main entry: delega a core/*

import streamlit as st

# --- Import dai moduli (devono esistere in core/) ---
from core.i18n import L                                  # dizionario lingue
from core.search import location_search_ui               # UI ricerca località
from core.map import map_ui                              # UI mappa (facoltativo)
from core.meteo import meteo_ui                          # UI meteo & calcolo (grafici, pdf, csv)

# ---------------------- THEME (dark) ----------------------
PRIMARY = "#06b6d4"; ACCENT  = "#f97316"; OK = "#10b981"; WARN = "#f59e0b"; ERR = "#ef4444"
st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{ --bg:#0b0f13; --panel:#121821; --muted:#9aa4af; --fg:#e5e7eb; --line:#1f2937; }}
html, body, .stApp {{ background:var(--bg); color:var(--fg); }}
[data-testid="stHeader"] {{ background:transparent; }}
section.main > div {{ padding-top: .6rem; }}
h1,h2,h3,h4 {{ color:#fff; letter-spacing:.2px }}
hr {{ border:none; border-top:1px solid var(--line); margin:.75rem 0 }}
.badge {{ display:inline-flex
