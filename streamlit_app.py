# streamlit_app.py
# Telemark · Pro Wax & Tune — versione diagnostica (località + mappa piste)

import streamlit as st

# importa moduli core
import core.search as search_mod
from core.search import country_selectbox, location_searchbox, get_current_selection
from core.i18n import L
from core.maps import render_map

# ---------------------- PAGE CONFIG ----------------------
st.set_page_config(
    page_title="Telemark · Pro Wax & Tune",
    page_icon="❄️",
    layout="wide",
)

# CSS molto semplice (dark)
st.markdown(
    """
    <style>
    html, body, .stApp {
      background-color: #05070b;
      color: #e5e7eb;
    }
    [data-testid="stHeader"] {
      background: transparent;
    }
    h1, h2, h3 {
      color: #ffffff;
    }
    .card {
      background: #111827;
      border-radius: 12px;
      padding: 0.75rem 0.9rem;
      border: 1px solid #1f2933;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------- DEBUG MODULO SEARCH ----------------------
st.sidebar.markdown("### Debug")
st.sidebar.write("Modulo search path:")
st.sidebar.code(getattr(search_mod, "__file__", "??"), language="text")
st.sidebar.write("Search.VERSION:")
st.sidebar.code(getattr(search_mod, "VERSION", "NO VERSION"), language="text")

# ---------------------- LINGUA ----------------------
lang = st.sidebar.selectbox(
    L["it"]["lang"] + " / " + L["en"]["lang"],
    ["IT", "EN"],
    index=0,
)

T = L["it"] if lang == "IT" else L["en"]

st.title("Telemark · Pro Wax & Tune")

# ---------------------- 1) SELEZIONE PAESE ----------------------
st.markdown("### 🌍 Località")

iso2 = country_selectbox(T)

# ---------------------- 2) SEARCH LOCALITÀ ----------------------
selection = location_searchbox(T, iso2=iso2)

curr = get_current_selection() or selection

if curr:
    # --- Riepilogo località selezionata (senza lat/lon) ---
sel = get_current_selection()
if sel:
    st.markdown(
        f"**Località selezionata:** {sel['label']}"
    )
    st.write("")  # piccolo spazio
else:
    st.info("Seleziona una località per continuare.")

# ---------------------- 3) MAPPA & PISTE ----------------------
if curr:
    ctx = {
        "lang": lang,
        "lat": curr["lat"],
        "lon": curr["lon"],
        "place_label": curr["label"],
    }
    render_map(T, ctx)
