# telemark_pro_app.py
import streamlit as st
import pandas as pd
import requests, base64, math
import matplotlib.pyplot as plt
from datetime import time
from dateutil import tz
from streamlit_searchbox import st_searchbox  # ricerca live stile meteoblue

# ------------------------ TEMA & STILE ------------------------
PRIMARY = "#10bfcf"; BG = "#0f172a"; CARD = "#0f172a"; TEXT = "#eef2ff"
st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{
  --bg:{BG}; --card:{CARD}; --text:{TEXT};
}}
[data-testid="stAppViewContainer"] > .main {{
  background: radial-gradient(1200px 800px at 20% -10%, #13203d 0%, {BG} 40%, #0b1224 100%);
}}
.block-container {{ padding-top: .8rem; }}
h1,h2,h3,h4,h5, label, p, span, div {{ color: var(--text); }}
hr {{ border-color: rgba(255,255,255,.12); }}
.card {{ background: var(--card); border:1px solid rgba(255,255,255,.10);
        border-radius:16px; padding:14px; box-shadow:0 10px 22px rgba(0,0,0,.25); }}
.brand {{ display:flex; align-items:center; gap:10px; padding:8px 10px; border-radius:12px;
         background:rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.08); }}
.brand img {{ height:22px; }}
.badge {{ border:1px solid rgba(255,255,255,.15); padding:6px 10px; border-radius:999px; font-size:.78rem; opacity:.85; }}
.small {{ font-size:.82rem; opacity:.85; }}
</style>
""", unsafe_allow_html=True)

st.markdown("### Telemark · Pro Wax & Tune")
st.markdown("<span class='badge'>Ricerca tipo Meteoblue · Blocchi A/B/C · 8 marchi sciolina · Struttura + Angoli</span>", unsafe_allow_html=True)

# ------------------------ UTIL ------------------------
def flag_emoji(cc: str) -> str:
    try:
        c = cc.upper(); return chr(127397+ord(c[0])) + chr(127397+ord(c[1]))
    except Exception:
        return "🏳️"

def nominatim_search(q: str):
    """Richiamata ad ogni tasto da st_searchbox: restituisce etichette con bandierina."""
