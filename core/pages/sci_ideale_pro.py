# core/pages/sci_ideale_pro.py
from __future__ import annotations

from typing import Dict, Any

import streamlit as st

from core import wax_logic as wax_mod
from core.pages.ski_selector import recommend_skis_for_day


def _guess_snow_label():
    """Prova a dedurre la condizione neve dal meteo salvato in sessione."""
    df = st.session_state.get("_meteo_res")
    if df is None or len(df) == 0:
        return "Compatta/trasformata secca"

    # prendo il campione a metà giornata
    row = df.iloc[len(df) // 2]
    try:
        return wax_mod.classify_snow(row)
    except Exception:
        return "Compatta/trasformata secca"


def render_page(T, ctx: Dict[str, Any] | None = None):
    st.header("🎿 Sci Ideale PRO")

    default_label = _guess_snow_label()

    st.markdown(
        "Suggeritore modelli multi-marca in base a **livello**, **uso** "
        "e **condizione neve**."
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        level_choice = st.selectbox(
            "Livello sciatore",
            [
                ("Principiante", "beginner"),
                ("Intermedio", "intermediate"),
                ("Avanzato", "advanced"),
                ("Race / agonista", "race"),
            ],
            index=1,
            format_func=lambda x: x[0],
            key="sci_pro_level",
        )
    with col2:
        usage_pref = st.selectbox(
            "Uso principale",
            [
                "Pista allround",
                "SL / raggi stretti",
                "GS / raggi medi",
                "All-mountain",
                "Freeride",
                "Skialp / touring",
            ],
            index=0,
            key="sci_pro_usage",
        )
    with col3:
        cond_default_idx = 0
        cond_options = [
            default_label,
            "Neve nuova fredda",
            "Neve nuova umida",
            "Compatta/trasformata secca",
            "Primaverile/trasformata bagnata",
            "Rigelata/ghiacciata",
        ]
        # rimuovo eventuali duplicati
        cond_seen = []
        cond_unique = []
        for c in cond_options:
            if c not in cond_seen:
                cond_seen.append(c)
                cond_unique.append(c)
        if default_label in cond_unique:
            cond_default_idx = cond_unique.index(default_label)

        snow_label = st.selectbox(
            "Condizione neve",
            cond_unique,
            index=cond_default_idx,
            key="sci_pro_snowlabel",
        )

    level_tag = level_choice[1]
    skis = recommend_skis_for_day(
        level_tag=level_tag,
        usage_pref=usage_pref,
        snow_label=snow_label,
    )

    if not skis:
        st.info("Nessun modello suggerito per questi parametri (lista interna vuota).")
        return

    st.markdown("### Suggerimenti modelli")

    for ski in skis:
        st.markdown(
            f"<div class='card' style='background:#121821; "
            f"border:1px solid #1f2937; border-radius:12px; "
            f"padding:.9rem .95rem; margin-bottom:.6rem;'>"
            f"<div><b>{ski.brand} · {ski.model}</b></div>"
            f"<div style='font-size:.9rem; color:#cbd5e1;'>"
            f"Categoria: {ski.usage} · Focus neve: {ski.snow_focus}"
            f"</div>"
            f"<div style='font-size:.85rem; color:#94a3b8; margin-top:.25rem;'>"
            f"{ski.notes}"
            f"</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
