# core/wax_logic.py
import streamlit as st

def render_wax(T, ctx):
    st.markdown("#### 4) Scioline & tuning")
    X = st.session_state.get("_meteo_res")
    if X is None or X.empty:
        st.info("Calcola prima il meteo (sezione 3).")
        return
    t_med = float(X["T_surf"].head(6).mean())
    rh_med = float(X["RH"].head(6).mean())
    st.write(f"T_neve media (prossime ore): **{t_med:.1f} °C** · UR **{rh_med:.0f}%**")
    st.caption("Qui rimetteremo le card brand/brush come da versione monoblocco.")

render = render_wax
