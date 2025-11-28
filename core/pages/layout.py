# core/pages/layout.py
# Layout, stile e navigazione superiore per Telemark · Pro Wax & Tune

from __future__ import annotations
import streamlit as st


# -------------------------------------------------------------------
# 1) APPLY LAYOUT  → Tema grafico globale (CSS)
# -------------------------------------------------------------------
def apply_layout():
    st.markdown(
        """
<style>
/* ----------- ROOT COLORS ----------- */
:root {
  --bg:#0b0f13;
  --panel:#121821;
  --muted:#9aa4af;
  --fg:#e5e7eb;
  --line:#1f2937;
}

/* ----------- GLOBAL ----------- */
html, body, .stApp {
  background:var(--bg);
  color:var(--fg);
}

/* Rimuove header Streamlit */
[data-testid="stHeader"] {
  background:transparent;
}

/* Riduce padding superiore */
section.main > div {
  padding-top: 0.4rem;
}

/* Titoli */
h1,h2,h3,h4 {
  color:#fff;
  letter-spacing:.3px;
}

/* Cards */
.card {
  background: var(--panel);
  border:1px solid var(--line);
  border-radius:12px;
  padding:.9rem .95rem;
  margin-bottom: 0.4rem;
}

/* Testo piccolo */
.small {
  font-size:.85rem;
  color:#cbd5e1;
}

/* Badge */
.badge {
  display:inline-flex;
  align-items:center;
  gap:.35rem;
  background:#020617;
  border:1px solid #1e293b;
  border-radius:999px;
  padding:.15rem .55rem;
  font-size:.8rem;
  color:#e2e8f0;
}

/* Top navigation bar */
.topnav-container {
  display:flex;
  justify-content:center;
  gap:1rem;
  margin-top:0.3rem;
  margin-bottom:1.2rem;
}

.topnav-btn {
  padding:0.45rem 1.2rem;
  border-radius:8px;
  border:1px solid var(--line);
  background:var(--panel);
  cursor:pointer;
  color:var(--muted);
  font-size:0.92rem;
  transition: all .15s ease-in-out;
}

.topnav-btn:hover {
  background:#1a2330;
  color:#fff;
}

.topnav-btn-active {
  padding:0.45rem 1.2rem;
  border-radius:8px;
  background:#06b6d4;
  border:1px solid #06b6d4;
  color:black;
  font-weight:600;
  font-size:0.92rem;
}

</style>
""",
        unsafe_allow_html=True,
    )


# -------------------------------------------------------------------
# 2) TOP NAVIGATION (Località / Racing)
# -------------------------------------------------------------------
def top_navigation() -> str:
    """
    Barra di navigazione superiore stile WebApp.
    Ritorna:
        "local"   → Località & Mappa
        "racing"  → Racing / Calendari
    """

    if "page" not in st.session_state:
        st.session_state["page"] = "local"

    # Disegno pulsanti
    col1, col2 = st.columns([1,8])  # col1 = lingue futura?
    with col2:
        st.markdown("<div class='topnav-container'>", unsafe_allow_html=True)

        # --- LOCAL BUTTON ---
        local_active = st.session_state["page"] == "local"
        local_btn_class = "topnav-btn-active" if local_active else "topnav-btn"
        local_click = st.button(
            "🌍 Località & Mappa",
            key="topnav_local",
            help="Previsioni, mappa, sci ideale, tuning e scioline",
        )
        if local_click:
            st.session_state["page"] = "local"

        # --- RACING BUTTON ---
        race_active = st.session_state["page"] == "racing"
        race_btn_class = "topnav-btn-active" if race_active else "topnav-btn"
        race_click = st.button(
            "🏁 Racing / Calendari",
            key="topnav_racing",
            help="Calendari FIS / ASIVA, profilo meteo gara, tuning dinamico",
        )
        if race_click:
            st.session_state["page"] = "racing"

        st.markdown("</div>", unsafe_allow_html=True)

    return st.session_state["page"]
