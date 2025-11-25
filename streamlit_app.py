# streamlit_app.py
# Telemark · Pro Wax & Tune — STEP 1: ricerca località (modulo core.search)

import streamlit as st

from core.i18n import L
from core.search import location_searchbox

# ---------------------- PAGE CONFIG + THEME ----------------------
st.set_page_config(
    page_title="Telemark · Pro Wax & Tune",
    page_icon="❄️",
    layout="wide",
)

st.markdown(
    """
    <style>
    :root {
        --bg:#05070a;
        --panel:#0f172a;
        --fg:#e5e7eb;
        --line:#1f2937;
        --muted:#9ca3af;
    }
    html, body, .stApp { background:var(--bg); color:var(--fg); }
    [data-testid="stHeader"] { background:transparent; }
    section.main > div { padding-top: 0.75rem; }
    h1, h2, h3 { color:#f9fafb; letter-spacing:0.02em; }
    .card {
        background:var(--panel);
        border-radius:12px;
        border:1px solid var(--line);
        padding:0.85rem 0.95rem;
    }
    .muted { color:var(--muted); font-size:0.9rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Telemark · Pro Wax & Tune")

# ---------------------- SIDEBAR: LINGUA ----------------------
st.sidebar.markdown("### ⚙️")

lang_code = st.sidebar.selectbox(
    "Language / Lingua",
    ["IT", "EN"],
    index=0,
)

T = L["it"] if lang_code == "IT" else L["en"]
st.sidebar.markdown(
    "🌐 **{}**".format("Italiano" if lang_code == "IT" else "English")
)

# ---------------------- MAIN: STEP 1 – RICERCA LOCALITÀ ----------------------
st.markdown(f"### {T['search_title']}")

lat, lon, place_label, iso2 = location_searchbox(T)

# Card di riepilogo sempre visibile
st.markdown(
    f"""
    <div class="card">
      <div>📍 <b>{place_label}</b></div>
      <div class="muted">
        lat {lat:.5f}, lon {lon:.5f} · ISO2 {iso2}
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Per ora ci fermiamo qui; i moduli meteo / mappe li ricolleghiamo in seguito.
