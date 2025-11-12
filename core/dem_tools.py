# core/dem_tools.py
import streamlit as st

def render_dem(T, ctx):
    st.markdown("#### 6) DEM / Esposizione & pendenza")
    st.caption("Modulo DEM verrà ripristinato (patch 3×3, Horn).")

render = render_dem
