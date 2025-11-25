# streamlit_app.py
# Telemark · Pro Wax & Tune — main modulare

import streamlit as st

from core.i18n import L
from core.search import country_selectbox, location_searchbox, get_current_selection
from core.maps import render_map

# ---------------- CONFIG & STILE ----------------
PRIMARY = "#06b6d4"

st.set_page_config(
    page_title="Telemark · Pro Wax & Tune",
    page_icon="❄️",
    layout="wide",
)

st.markdown(
    """
<style>
html, body, .stApp {
  background:#0b0f13;
  color:#e5e7eb;
}
[data-testid="stHeader"] { background:transparent; }
section.main > div { padding-top: 0.6rem; }
.card {
  background:#121821;
  border-radius:12px;
  border:1px solid #1f2937;
  padding: .9rem .95rem;
}
.small { font-size:.85rem; color:#9ca3af; }
</style>
""",
    unsafe_allow_html=True,
)

# ---------------- LINGUA ----------------
st.sidebar.markdown("### ⚙️")

lang = st.sidebar.selectbox(
    L["it"]["lang"] + " / " + L["en"]["lang"],
    ["IT", "EN"],
    index=0,
)
T = L["it"] if lang == "IT" else L["en"]

st.title("Telemark · Pro Wax & Tune")

# ---------------- PAESE + RICERCA ----------------
st.markdown("#### 🌍 Località")

iso2 = country_selectbox(T)
location_searchbox(T, iso2=iso2)

current = get_current_selection()
if current:
    st.markdown(
        f"""
<div class="card">
  <div class="small">{T.get("selected_place", "Località selezionata")}</div>
  <strong>{current['label']}</strong>
</div>
""",
        unsafe_allow_html=True,
    )

# ---------------- MAPPA & PISTE ----------------
ctx = {
    "lang": lang,
    "lat": current["lat"] if current else 45.83333,
    "lon": current["lon"] if current else 7.73333,
    "place_label": current["label"] if current else "🇮🇹  Champoluc-Champlan, Valle d’Aosta — IT",
}

render_map(T, ctx)

# In seguito qui aggiungeremo:
# - modulo pendenza/ombreggiatura (separato, usando ctx e piste selezionata)
# - modulo tuning / sciolina / grafici
