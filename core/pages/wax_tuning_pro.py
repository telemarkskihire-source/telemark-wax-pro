# core/pages/wax_tuning_pro.py
# Telemark · Pro Wax & Tune — Wax & Tuning PRO Dashboard
#
# Usa i dati meteo già calcolati (st.session_state["_meteo_res"])
# e le funzioni di core.wax_logic per proporre:
#   - Analisi neve nella finestra oraria scelta
#   - Scioline consigliate (multi-brand, liquida/solida, spazzole)
#   - Tuning per disciplina modulato per livello sciatore
#
# Può funzionare anche "standalone" con upload CSV.

from __future__ import annotations

from datetime import datetime, time as dtime
from typing import Optional, Tuple

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from core import wax_logic as wax


# -------------------------------------------------------------
# CONFIG PAGINA
# -------------------------------------------------------------
st.set_page_config(
    page_title="Wax & Tuning PRO",
    page_icon="🛠️",
    layout="wide",
)

st.title("🛠️ Wax & Tuning PRO")
st.caption("Dashboard avanzata per scioline, struttura e tuning in base al profilo neve.")


# -------------------------------------------------------------
# FUNZIONI DI SUPPORTO
# -------------------------------------------------------------
def _get_meteo_df() -> Optional[pd.DataFrame]:
    """
    Recupera i dati meteo dalla sessione (app principale) oppure
    permette all'utente di caricare un CSV con le stesse colonne.
    Atteso (almeno):
      - time_local (datetime)
      - T_surf (°C superficie neve)
      - RH (%)
      - wind (m/s o km/h, non critico)
      - liq_water_pct
      - cloud
      - ptyp
    """
    df_session = st.session_state.get("_meteo_res")

    src = st.radio(
        "Sorgente dati neve",
        ["Usa meteo dall'app", "Carica CSV esterno"],
        index=0 if df_session is not None else 1,
        horizontal=True,
    )

    if src == "Usa meteo dall'app":
        if df_session is None or len(df_session) == 0:
            st.warning("Nessun profilo meteo trovato in sessione. Calcola prima il meteo dalla pagina principale oppure carica un CSV.")
            return None
        df = df_session.copy()
    else:
        up = st.file_uploader("Carica CSV con il profilo meteo/neve", type=["csv"])
        if not up:
            return None
        df = pd.read_csv(up)

    # Normalizzazione colonne base
    # time_local o time
    if "time_local" in df.columns:
        df["time_local"] = pd.to_datetime(df["time_local"])
    elif "time" in df.columns:
        df["time_local"] = pd.to_datetime(df["time"])
    else:
        st.error("Nel CSV manca una colonna 'time_local' o 'time'.")
        return None

    # Controlli minimi
    needed = ["T_surf", "RH"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        st.error(f"Mancano le colonne obbligatorie: {', '.join(missing)}")
        return None

    # Colonne opzionali
    for col, default in [
        ("wind", 0.0),
        ("liq_water_pct", 0.0),
        ("cloud", 0.0),
        ("ptyp", None),
    ]:
        if col not in df.columns:
            df[col] = default

    return df


def _select_time_window(df: pd.DataFrame) -> Tuple[pd.DataFrame, str]:
    """
    Selettore giorno + intervallo orario.
    Ritorna (df_window, descrizione_finestra).
    """
    # Giorni disponibili
    days = sorted(df["time_local"].dt.date.unique())
    default_day = st.session_state.get("ref_day", days[0])

    col_day, col_start, col_end = st.columns(3)

    with col_day:
        day = st.date_input("Giorno da analizzare", value=default_day, min_value=days[0], max_value=days[-1])

    # Orario default: 9–12
    with col_start:
        start_t = st.time_input(
            "Ora inizio finestra",
            value=st.session_state.get("wax_pro_start", dtime(hour=9, minute=0)),
            key="wax_pro_start_time",
        )
    with col_end:
        end_t = st.time_input(
            "Ora fine finestra",
            value=st.session_state.get("wax_pro_end", dtime(hour=12, minute=0)),
            key="wax_pro_end_time",
        )

    st.session_state["wax_pro_start"] = start_t
    st.session_state["wax_pro_end"] = end_t

    mask_day = df["time_local"].dt.date == day
    day_df = df[mask_day]
    if day_df.empty:
        st.warning("Nessun dato per il giorno selezionato, mostro l'intero dataset.")
        window_df = df.copy()
        label = "Tutto il profilo disponibile"
    else:
        sel = day_df[
            (day_df["time_local"].dt.time >= start_t)
            & (day_df["time_local"].dt.time <= end_t)
        ]
        if sel.empty:
            st.warning("Nessun dato nella finestra oraria scelta, uso tutto il giorno.")
            window_df = day_df.copy()
            label = f"{day} · intera giornata"
        else:
            window_df = sel.copy()
            label = f"{day} · {start_t.strftime('%H:%M')}–{end_t.strftime('%H:%M')}"

    return window_df, label


def _compute_block_metrics(df_window: pd.DataFrame):
    """Calcola medie e condizione neve per la finestra selezionata."""
    t_med = float(df_window["T_surf"].mean())
    rh_med = float(df_window["RH"].mean())
    v_eff = float(df_window.get("wind", pd.Series([0.0])).mean())

    # Per la label neve usiamo la prima riga della finestra
    row0 = df_window.iloc[0]
    cond = wax.classify_snow(row0)

    return t_med, rh_med, v_eff, cond


def _ensure_dyn_level():
    """
    Selettore livello sciatore PRO, sincronizzato con wax._current_level().
    """
    lvl_map = {
        "Turistico evoluto": "tourist",
        "Esperto": "expert",
        "FIS / Master": "fis",
        "WC / Coppa del Mondo": "wc",
    }
    inv_map = {v: k for k, v in lvl_map.items()}

    current = str(st.session_state.get("dyn_skier_level", "tourist")).lower()
    default_label = inv_map.get(current, "Turistico evoluto")

    label = st.selectbox(
        "Livello sciatore (influenza tuning angoli/struttura)",
        list(lvl_map.keys()),
        index=list(lvl_map.keys()).index(default_label),
    )
    tag = lvl_map[label]

    # aggiorno sessione per wax_logic._current_level()
    st.session_state["dyn_skier_level"] = tag
    return tag, label


# -------------------------------------------------------------
# CARICO DATI METEO / NEVE
# -------------------------------------------------------------
st.subheader("1️⃣ Sorgente dati neve")

df_meteo = _get_meteo_df()
if df_meteo is None:
    st.stop()

st.success(f"Profilo meteo/neve caricato: {len(df_meteo)} record.")

# Piccolo chart di overview (T_surf)
with st.expander("Mostra overview grafica T_surf su tutto il periodo"):
    chart_overview = (
        alt.Chart(df_meteo)
        .mark_line()
        .encode(
            x=alt.X("time_local:T", title="Orario"),
            y=alt.Y("T_surf:Q", title="T neve (°C)"),
            tooltip=["time_local:T", "T_surf:Q", "RH:Q"],
        )
        .properties(height=220)
    )
    st.altair_chart(chart_overview, use_container_width=True)


# -------------------------------------------------------------
# SELEZIONE FINESTRA ORARIA
# -------------------------------------------------------------
st.subheader("2️⃣ Finestra oraria gara/allenamento")

df_window, win_label = _select_time_window(df_meteo)

if df_window.empty:
    st.error("Nessun dato nella finestra selezionata.")
    st.stop()

st.info(f"Stai analizzando: **{win_label}**  ({len(df_window)} punti)")

# Mostra tabella sintetica (prime 10 righe)
with st.expander("Vedi tabella dettagliata della finestra (prime 10 righe)"):
    st.dataframe(
        df_window.head(10).style.format(
            {
                "T_surf": "{:.1f}",
                "RH": "{:.0f}",
                "wind": "{:.1f}",
                "liq_water_pct": "{:.1f}",
                "cloud": "{:.2f}",
            }
        ),
        use_container_width=True,
    )


# -------------------------------------------------------------
# METRICHE PRINCIPALI + CONDIZIONE NEVE
# -------------------------------------------------------------
st.subheader("3️⃣ Condizione neve nella finestra selezionata")

t_med, rh_med, v_eff, cond = _compute_block_metrics(df_window)

colA, colB, colC, colD = st.columns(4)
with colA:
    st.metric("T neve media", f"{t_med:.1f} °C")
with colB:
    st.metric("UR media", f"{rh_med:.0f} %")
with colC:
    st.metric("Vento medio", f"{v_eff:.1f}")
with colD:
    st.metric("Condizione neve", cond)

st.markdown(
    f"""
<div style="
    border-left:6px solid #f97316;
    background:#111827;
    padding:.9rem 1rem;
    border-radius:10px;
    margin-top:.5rem;
">
<b>Riassunto finestra</b><br>
Neve: <b>{cond}</b> · T neve ≈ <b>{t_med:.1f} °C</b> · UR ≈ <b>{rh_med:.0f}%</b> · vento ≈ <b>{v_eff:.1f}</b>
</div>
""",
    unsafe_allow_html=True,
)

# Piccolo chart T_surf + RH nella finestra
chart_win = (
    alt.Chart(df_window)
    .transform_fold(
        ["T_surf", "RH"],
        as_=["variable", "value"],
    )
    .mark_line(point=True)
    .encode(
        x=alt.X("time_local:T", title="Orario"),
        y=alt.Y("value:Q", title="Valore"),
        color=alt.Color("variable:N", title="Serie"),
        tooltip=["time_local:T", "variable:N", "value:Q"],
    )
    .properties(height=260)
)

st.altair_chart(chart_win, use_container_width=True)


# -------------------------------------------------------------
# WAX PRO — MULTI BRAND
# -------------------------------------------------------------
st.subheader("4️⃣ Scioline consigliate (PRO multi-brand)")

wax_form, brush_seq, use_topcoat = wax.wax_form_and_brushes(t_med, rh_med)

st.markdown(
    f"""
<div style="background:#020617; border-radius:10px; padding:.75rem .9rem; margin-bottom:.75rem;">
<b>Forma consigliata</b>: {wax_form}<br>
<b>Sequenza spazzole</b>: {brush_seq}
</div>
""",
    unsafe_allow_html=True,
)

# Griglia brand
st.markdown(
    """
<style>
.wax-grid {
  display:grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap:.7rem;
}
.wax-card {
  background:#0b1120;
  border:1px solid #1f2937;
  border-radius:12px;
  padding:.75rem .85rem;
  display:flex;
  gap:.65rem;
}
.wax-logo {
  flex:0 0 auto;
  width:52px;
  height:52px;
  border-radius:10px;
  border:1px solid #1f2937;
  background:#020617;
  display:flex;
  align-items:center;
  justify-content:center;
  overflow:hidden;
}
.wax-logo img {
  max-width:100%;
  max-height:100%;
}
.wax-body h4 {
  margin:0 0 .2rem 0;
  font-size:1rem;
  color:#e5e7eb;
}
.wax-body .line {
  font-size:.85rem;
  color:#9ca3af;
}
</style>
<div class="wax-grid">
""",
    unsafe_allow_html=True,
)

for (brand_name, solid_bands, liquid_bands) in wax.BRANDS:
    solid_rec = wax.pick_wax(solid_bands, t_med, rh_med)
    if use_topcoat:
        topcoat_rec = wax.pick_liquid(liquid_bands, t_med, rh_med)
    else:
        topcoat_rec = "non necessario"

    logo_b64 = wax.get_brand_logo_b64(brand_name)
    if logo_b64:
        logo_html = f"<div class='wax-logo'><img src='data:image/png;base64,{logo_b64}'/></div>"
    else:
        logo_html = "<div class='wax-logo'>🏷️</div>"

    st.markdown(
        f"""
<div class="wax-card">
  {logo_html}
  <div class="wax-body">
    <h4>{brand_name}</h4>
    <div class="line"><b>Base solida</b>: {solid_rec}</div>
    <div class="line"><b>Topcoat liquida</b>: {topcoat_rec}</div>
    <div class="line"><b>Forma</b>: {wax_form}</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

st.markdown("</div>", unsafe_allow_html=True)


# -------------------------------------------------------------
# TUNING PRO — DISCIPLINE & LIVELLO
# -------------------------------------------------------------
st.subheader("5️⃣ Tuning lamina & struttura (discipline PRO)")

lvl_tag, lvl_label = _ensure_dyn_level()

st.caption(f"Livello selezionato: **{lvl_label}** (interno: `{lvl_tag}`)")

disc_list = ["SL", "GS", "SG", "DH"]
rows = []
for d in disc_list:
    fam, side_edge, base_bevel = wax.tune_for(t_med, d)
    rows.append(
        {
            "Disciplina": d,
            "Struttura consigliata": fam,
            "Angolo SIDE (°)": f"{side_edge:.1f}",
            "Base bevel (°)": f"{base_bevel:.1f}",
        }
    )

df_tune = pd.DataFrame(rows)
st.table(df_tune)

st.markdown(
    """
> Nota: gli angoli SIDE sono angoli spigolo (es. 88.0°), non bevel.
> Il livello sciatore rende il tuning più permissivo (turistico) o più aggressivo (FIS/WC).
"""
)


# -------------------------------------------------------------
# EXPORT / RIASSUNTO
# -------------------------------------------------------------
st.subheader("6️⃣ Export & riassunto")

col_exp1, col_exp2 = st.columns(2)

with col_exp1:
    csv_window = df_window.to_csv(index=False)
    st.download_button(
        "📥 Scarica CSV finestra neve",
        data=csv_window,
        file_name="wax_tuning_pro_window.csv",
        mime="text/csv",
    )

with col_exp2:
    # breve riassunto testuale per copiare in note / WhatsApp
    summary = (
        f"Wax & Tuning PRO — {win_label}\n"
        f"Neve: {cond}\n"
        f"T_neve ≈ {t_med:.1f} °C, UR ≈ {rh_med:.0f}%, vento ≈ {v_eff:.1f}\n"
        f"Forma: {wax_form}\n"
        f"Livello: {lvl_label}\n"
    )
    st.text_area(
        "Riassunto rapido (copiabile):",
        value=summary,
        height=140,
  )
