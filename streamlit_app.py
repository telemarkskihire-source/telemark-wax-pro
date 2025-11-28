# streamlit_app.py
# Telemark · Pro Wax & Tune — versione modulare

from __future__ import annotations
import importlib
import sys
import streamlit as st

# --- Hard reload di tutti i moduli core.* ---
importlib.invalidate_caches()
for name in list(sys.modules.keys()):
    if name.startswith("core."):
        del sys.modules[name]

# --- Import moduli di pagina ---
from core.pages.layout import apply_layout, top_navigation
from core.pages.page_local import render_page_local
from core.pages.page_racing import render_page_racing


# ---------------------------------------------------------
# SETUP GENERALE
# ---------------------------------------------------------
st.set_page_config(
    page_title="Telemark · Pro Wax & Tune",
    page_icon="❄️",
    layout="wide",
)

apply_layout()  # CSS + theme

# NAVBAR SUPERIORE (non sidebar)
page = top_navigation()

# ---------------------------------------------------------
# ROUTING PULITO
# ---------------------------------------------------------
if page == "local":
    render_page_local()

elif page == "racing":
    render_page_racing()

else:
    st.error("Pagina non trovata (errore routing).")
