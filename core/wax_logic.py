# core/wax_logic.py
# Telemark · Pro Wax & Tune — pannello Scioline & Tuning
#
# Versione adattata al nuovo modello meteo:
# - usa MeteoProfile (meteo_mod.build_meteo_profile_for_race_day)
# - usa ctx["race_datetime"] per centrare la finestra intorno alla gara

from __future__ import annotations

import os
import base64
from datetime import timedelta
from typing import Any

import pandas as pd
import streamlit as st

# ---------------------- BRAND BANDS (solida + liquida) ----------------------
SWIX = [
    ("PS5 Turquoise", -18, -10),
    ("PS6 Blue", -12, -6),
    ("PS7 Violet", -8, -2),
    ("PS8 Red", -4, 4),
    ("PS10 Yellow", 0, 10),
]
TOKO = [("Blue", -30, -9), ("Red", -12, -4), ("Yellow", -6, 0)]
VOLA = [
    ("MX-E Blue", -25, -10),
    ("MX-E Violet", -12, -4),
    ("MX-E Red", -5, 0),
    ("MX-E Yellow", -2, 6),
]
RODE = [
    ("R20 Blue", -18, -8),
    ("R30 Violet", -10, -3),
    ("R40 Red", -5, 0),
    ("R50 Yellow", -1, 10),
]
HOLM = [
    ("UltraMix Blue", -20, -8),
    ("BetaMix Red", -14, -4),
    ("AlphaMix Yellow", -4, 5),
]
MAPL = [("Univ Cold", -12, -6), ("Univ Medium", -7, -2), ("Univ Soft", -5, 0)]
START = [("SG Blue", -12, -6), ("SG Purple", -8, -2), ("SG Red", -3, 7)]
SKIGO = [("Blue", -12, -6), ("Violet", -8, -2), ("Red", -3, 2)]

SWIX_LQ = [
    ("HS Liquid Blue", -12, -6),
    ("HS Liquid Violet", -8, -2),
    ("HS Liquid Red", -4, 4),
    ("HS Liquid Yellow", 0, 10),
]
TOKO_LQ = [
    ("LP Liquid Blue", -12, -6),
    ("LP Liquid Red", -6, -2),
    ("LP Liquid Yellow", -2, 8),
]
VOLA_LQ = [
    ("Liquid Blue", -12, -6),
    ("Liquid Violet", -8, -2),
    ("Liquid Red", -4, 4),
    ("Liquid Yellow", 0, 8),
]
RODE_LQ = [
    ("RL Blue", -12, -6),
    ("RL Violet", -8, -2),
    ("RL Red", -4, 3),
    ("RL Yellow", 0, 8),
]
HOLM_LQ = [
    ("Liquid Blue", -12, -6),
    ("Liquid Red", -6, 2),
    ("Liquid Yellow", 0, 8),
]
MAPL_LQ = [
    ("Liquid Cold", -12, -6),
    ("Liquid Medium", -7, -1),
    ("Liquid Soft", -2, 8),
]
START_LQ = [
    ("FHF Liquid Blue", -12, -6),
    ("FHF Liquid Purple", -8, -2),
    ("FHF Liquid Red", -3, 6),
]
SKIGO_LQ = [
    ("C110 Liquid Blue", -12, -6),
    ("C22 Liquid Violet", -8, -2),
    ("C44 Liquid Red", -3, 6),
]

BRANDS = [
    ("Swix", SWIX, SWIX_LQ),
    ("Toko", TOKO, TOKO_LQ),
    ("Vola", VOLA, VOLA_LQ),
    ("Rode", RODE, RODE_LQ),
    ("Holmenkol", HOLM, HOLM_LQ),
    ("Maplus", MAPL, MAPL_LQ),
    ("Start", START, START_LQ),
    ("Skigo", SKIGO, SKIGO_LQ),
]

BRAND_LOGO_FILES = {
    "Swix": "swix.png",
    "Toko": "toko.png",
    "Vola": "vola.png",
    "Rode": "rode.png",
    "Holmenkol": "holmenkol.png",
    "Maplus": "maplus.png",
    "Start": "start.png",
    "Skigo": "skigo.png",
}

# ---------------------- Helpers logo ----------------------
def _try_paths(filename: str) -> str | None:
    for root in ["logos", "assets/logos", "."]:
        path = os.path.join(root, filename)
        if os.path.exists(path):
            return path
    return None


@st.cache_data(show_spinner=False)
def _logo_b64(path: str | None) -> str | None:
    if not path:
        return None
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    except Exception:
        return None


def get_brand_logo_b64(brand_name: str) -> str | None:
    fname = BRAND_LOGO_FILES.get(brand_name)
    if not fname:
        return None
    p = _try_paths(fname)
    return _logo_b64(p)


# ---------------------- Logic wax & tuning ----------------------
def pick_wax(bands, t: float, rh: float) -> str:
    name = bands[0][0]
    for n, tmin, tmax in bands:
        if t >= tmin and t <= tmax:
            name = n
            break
    if rh < 60:
        rh_tag = " (secco)"
    elif rh < 80:
        rh_tag = " (medio)"
    else:
        rh_tag = " (umido)"
    return name + rh_tag


def pick_liquid(liq_bands, t: float, rh: float) -> str:
    name = liq_bands[0][0]
    for n, tmin, tmax in liq_bands:
        if t >= tmin and t <= tmax:
            name = n
            break
    return name


def wax_form_and_brushes(t_surf: float, rh: float) -> tuple[str, str, bool]:
    use_liquid = (t_surf > -1.0) or (rh >= 80.0)

    if t_surf <= -12:
        regime = "very_cold"
    elif t_surf <= -5:
        regime = "cold"
    elif t_surf <= -1:
        regime = "medium"
    else:
        regime = "warm"

    if use_liquid:
        form = "Liquida (topcoat) su base solida"
        if regime in ("very_cold", "cold"):
            brushes = "Ottone → Nylon duro → Feltro/Rotowool → Nylon morbido"
        elif regime == "medium":
            brushes = "Ottone → Nylon → Feltro/Rotowool → Crine"
        else:
            brushes = "Ottone → Nylon → Feltro/Rotowool → Panno microfibra"
    else:
        form = "Solida (panetto)"
        if regime == "very_cold":
            brushes = "Ottone → Nylon duro → Crine"
        elif regime == "cold":
            brushes = "Ottone → Nylon → Crine"
        elif regime == "medium":
            brushes = "Ottone → Nylon → Crine → Nylon fine"
        else:
            brushes = "Ottone → Nylon → Nylon fine → Panno"

    return form, brushes, use_liquid


def recommended_structure(Tsurf: float) -> str:
    if Tsurf <= -10:
        return "Linear fine (freddo / secco)"
    if Tsurf <= -3:
        return "Cross hatch leggera (universale freddo)"
    if Tsurf <= 0.5:
        return "Diagonal / scarico a V (umido)"
    return "Wave marcata (bagnato caldo)"


def tune_for(Tsurf: float, discipline: str) -> tuple[str, float, float]:
    if Tsurf <= -10:
        fam = "Linear fine"
        base = 0.5
        side_map = {"SL": 88.5, "GS": 88.0, "SG": 87.5, "DH": 87.5}
    elif Tsurf <= -3:
        fam = "Cross hatch leggera"
        base = 0.7
        side_map = {"SL": 88.0, "GS": 88.0, "SG": 87.5, "DH": 87.0}
    else:
        fam = "Diagonal / V"
        base = 0.8 if Tsurf <= 0.5 else 1.0
        side_map = {"SL": 88.0, "GS": 87.5, "SG": 87.0, "DH": 87.0}
    side = side_map.get(discipline, 88.0)
    return fam, side, base


def classify_snow_from_profile(
    t_surf: float,
    precip: float,
    snowfall: float,
    cloudcover: float,
) -> str:
    if precip > 0.4 and snowfall < 0.1 and t_surf >= -1.0:
        return "Neve bagnata / pioggia"
    if snowfall > 0.3:
        if t_surf > -2.0:
            return "Neve nuova umida"
        else:
            return "Neve nuova fredda"
    if t_surf >= 0.0 and precip > 0.0:
        return "Primaverile / trasformata bagnata"
    if t_surf <= -8.0 and cloudcover < 30.0:
        return "Rigelata / ghiacciata"
    return "Compatta / trasformata secca"


# ---------------------- UI helpers ----------------------
def brand_card_html(
    brand_name: str,
    base_solid: str,
    form: str,
    topcoat: str,
    brushes: str,
    logo_b64: str | None,
    lang: str = "IT",
) -> str:
    logo_html = (
        f"<div class='logo'><img src='data:image/png;base64,{logo_b64}'/></div>"
        if logo_b64
        else "<div class='logo'></div>"
    )

    base_lbl = (
        "Sciolina base (solida)" if lang == "IT" else "Base glide wax (solid)"
    )
    topcoat_lbl = "Topcoat liquida" if lang == "IT" else "Liquid topcoat"
    brushes_lbl = "Spazzole" if lang == "IT" else "Brush sequence"

    return f"""
    <style>
    .brand {{
      display:flex;
      align-items:flex-start;
      gap:.65rem;
      background:#0e141d;
      border:1px solid #1e2a3a;
      border-radius:10px;
      padding:.75rem .8rem;
      width:100%;
    }}
    .brand h4 {{
      margin:0 0 .25rem 0;
      font-size:1rem;
      color:#fff;
    }}
    .brand .muted {{ color:#a9bacb; }}
    .brand .sub {{ color:#93b2c6; font-size:.85rem; }}
    .brand .logo {{
      flex:0 0 auto;
      display:flex;
      align-items:center;
      justify-content:center;
      width:54px;
      height:54px;
      background:#0b121a;
      border:1px solid #1e2a3a;
      border-radius:10px;
      overflow:hidden;
    }}
    .grid-wax {{
      display:grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap:.6rem;
    }}
    @media (max-width: 900px) {{
      .grid-wax {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
    }}
    </style>
    <div class='brand'>
      {logo_html}
      <div style='flex:1'>
        <h4>{brand_name}</h4>
        <div class='muted'>{base_lbl}: <b>{base_solid}</b></div>
        <div class='sub'>Forma: {form}</div>
        <div class='sub'>{topcoat_lbl}: {topcoat}</div>
        <div class='sub'>{brushes_lbl}: {brushes}</div>
      </div>
    </div>
    """


# ---------------------- RENDER PRINCIPALE ----------------------
def render_wax(T: dict[str, Any], ctx: dict[str, Any], profile: Any) -> None:
    lang = ctx.get("lang", "IT")
    title = (
        "🎯 Scioline & tuning (intorno all'orario di gara)"
        if lang == "IT"
        else "🎯 Wax & tuning (around race time)"
    )
    st.markdown(f"### {title}")

    if profile is None:
        msg = (
            "Calcola prima il profilo meteo della gara."
            if lang == "IT"
            else "Please compute the race-day meteo profile first."
        )
        st.info(msg)
        return

    race_dt = ctx.get("race_datetime")
    if race_dt is None:
        msg = (
            "Seleziona prima una gara e l'orario di partenza."
            if lang == "IT"
            else "Select a race and start time first."
        )
        st.info(msg)
        return

    df = pd.DataFrame(
        {
            "time": profile.times,
            "snow_temp": profile.snow_temp,
            "rh": profile.rh,
            "windspeed": profile.windspeed,
            "cloudcover": profile.cloudcover,
            "precipitation": profile.precip,
            "snowfall": profile.snowfall,
        }
    ).set_index("time")

    start = race_dt - timedelta(hours=1.5)
    end = race_dt + timedelta(hours=1.5)
    window = df.loc[(df.index >= start) & (df.index <= end)]
    if window.empty:
        window = df

    t_med = float(window["snow_temp"].mean())
    rh_med = float(window["rh"].mean())
    v_eff = float(window["windspeed"].mean())
    precip_med = float(window["precipitation"].mean())
    snowfall_med = float(window["snowfall"].mean())
    cloud_med = float(window["cloudcover"].mean())

    cond = classify_snow_from_profile(
        t_surf=t_med,
        precip=precip_med,
        snowfall=snowfall_med,
        cloudcover=cloud_med,
    )

    if lang == "IT":
        banner_html = (
            f"<b>Condizioni neve:</b> {cond} · "
            f"<b>T neve media</b> {t_med:.1f}°C · "
            f"<b>UR media</b> {rh_med:.0f}% · "
            f"<b>Vento medio</b> {v_eff:.1f} m/s"
        )
        struct_lbl = "Struttura soletta consigliata:"
    else:
        banner_html = (
            f"<b>Snow conditions:</b> {cond} · "
            f"<b>Avg snow temp</b> {t_med:.1f}°C · "
            f"<b>Avg RH</b> {rh_med:.0f}% · "
            f"<b>Avg wind</b> {v_eff:.1f} m/s"
        )
        struct_lbl = "Recommended base structure:"

    st.markdown(
        "<div style='border-left:6px solid #f97316; "
        "background:#1a2230; padding:.75rem .9rem; border-radius:10px;'>"
        f"{banner_html}</div>",
        unsafe_allow_html=True,
    )

    st.markdown(f"**{struct_lbl}** {recommended_structure(t_med)}")

    wax_form, brush_seq, use_topcoat = wax_form_and_brushes(t_med, rh_med)

    st.markdown("<div class='grid-wax'>", unsafe_allow_html=True)
    for (name, solid_bands, liquid_bands) in BRANDS:
        rec_solid = pick_wax(solid_bands, t_med, rh_med)
        if use_topcoat:
            topcoat = pick_liquid(liquid_bands, t_med, rh_med)
        else:
            topcoat = "non necessario" if lang == "IT" else "not needed"

        logo_b64 = get_brand_logo_b64(name)
        html = brand_card_html(
            brand_name=name,
            base_solid=rec_solid,
            form=wax_form,
            topcoat=topcoat,
            brushes=brush_seq,
            logo_b64=logo_b64,
            lang=lang,
        )
        st.markdown(html, unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    if lang == "IT":
        tune_title = "Tuning edges per disciplina"
        col_side = "Side bevel (angolo sci)"
        col_base = "Base bevel"
    else:
        tune_title = "Edge tuning by discipline"
        col_side = "Side bevel (ski angle)"
        col_base = "Base bevel"

    rows = []
    for d in ["SL", "GS", "SG", "DH"]:
        fam, side, base = tune_for(t_med, d)
        rows.append((d, fam, f"{side:.1f}°", f"{base:.1f}°"))

    tune_list = "".join(
        [
            f"<li><b>{d}</b>: {fam} — {col_side} {side} · {col_base} {base}</li>"
            for d, fam, side, base in rows
        ]
    )

    st.markdown(
        "<div class='card' style='background:#121821; border:1px solid #1f2937; "
        "border-radius:12px; padding:.9rem .95rem;'>"
        f"<div><b>{tune_title}</b></div>"
        f"<ul class='small' style='margin:.5rem 0 0 1rem'>{tune_list}</ul>"
        "</div>",
        unsafe_allow_html=True,
    )

# alias compatibile col vecchio orchestratore
render = render_wax
