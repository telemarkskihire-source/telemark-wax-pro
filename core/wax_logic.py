# core/wax_logic.py
# Telemark · Pro Wax & Tune — pannello Scioline & Tuning (estratto dal monoblocco, no ricorsioni)

import os, base64
import numpy as np
import pandas as pd
import streamlit as st

# ---------------------- BRAND BANDS (solida + liquida) ----------------------
SWIX = [("PS5 Turquoise",-18,-10),("PS6 Blue",-12,-6),("PS7 Violet",-8,-2),("PS8 Red",-4,4),("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10),("MX-E Violet",-12,-4),("MX-E Red",-5,0),("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8),("R30 Violet",-10,-3),("R40 Red",-5,0),("R50 Yellow",-1,10)]
HOLM = [("UltraMix Blue",-20,-8),("BetaMix Red",-14,-4),("AlphaMix Yellow",-4,5)]
MAPL = [("Univ Cold",-12,-6),("Univ Medium",-7,-2),("Univ Soft",-5,0)]
START= [("SG Blue",-12,-6),("SG Purple",-8,-2),("SG Red",-3,7)]
SKIGO= [("Blue",-12,-6),("Violet",-8,-2),("Red",-3,2)]

SWIX_LQ = [("HS Liquid Blue",-12,-6),("HS Liquid Violet",-8,-2),("HS Liquid Red",-4,4),("HS Liquid Yellow",0,10)]
TOKO_LQ = [("LP Liquid Blue",-12,-6),("LP Liquid Red",-6,-2),("LP Liquid Yellow",-2,8)]
VOLA_LQ = [("Liquid Blue",-12,-6),("Liquid Violet",-8,-2),("Liquid Red",-4,4),("Liquid Yellow",0,8)]
RODE_LQ = [("RL Blue",-12,-6),("RL Violet",-8,-2),("RL Red",-4,3),("RL Yellow",0,8)]
HOLM_LQ = [("Liquid Blue",-12,-6),("Liquid Red",-6,2),("Liquid Yellow",0,8)]
MAPL_LQ = [("Liquid Cold",-12,-6),("Liquid Medium",-7,-1),("Liquid Soft",-2,8)]
START_LQ= [("FHF Liquid Blue",-12,-6),("FHF Liquid Purple",-8,-2),("FHF Liquid Red",-3,6)]
SKIGO_LQ= [("C110 Liquid Blue",-12,-6),("C22 Liquid Violet",-8,-2),("C44 Liquid Red",-3,6)]

BRANDS = [
    ("Swix",SWIX,SWIX_LQ),
    ("Toko",TOKO,TOKO_LQ),
    ("Vola",VOLA,VOLA_LQ),
    ("Rode",RODE,RODE_LQ),
    ("Holmenkol",HOLM,HOLM_LQ),
    ("Maplus",MAPL,MAPL_LQ),
    ("Start",START,START_LQ),
    ("Skigo",SKIGO,SKIGO_LQ),
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
def _try_paths(filename: str):
    for root in ["logos", "assets/logos", "."]:
        path = os.path.join(root, filename)
        if os.path.exists(path): return path
    return None

@st.cache_data(show_spinner=False)
def _logo_b64(path: str):
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    except Exception:
        return None

def get_brand_logo_b64(brand_name: str):
    fname = BRAND_LOGO_FILES.get(brand_name)
    if not fname: return None
    p = _try_paths(fname)
    return _logo_b64(p) if p else None

# ---------------------- Logic wax & tuning ----------------------
def pick_wax(bands, t, rh):
    name = bands[0][0]
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax:
            name = n; break
    rh_tag = " (secco)" if rh<60 else " (medio)" if rh<80 else " (umido)"
    return name + rh_tag

def pick_liquid(liq_bands, t, rh):
    name = liq_bands[0][0]
    for n,tmin,tmax in liq_bands:
        if t>=tmin and t<=tmax:
            name = n; break
    return name

def wax_form_and_brushes(t_surf: float, rh: float):
    use_liquid = (t_surf > -1.0) or (rh >= 80)
    if t_surf <= -12: regime = "very_cold"
    elif t_surf <= -5: regime = "cold"
    elif t_surf <= -1: regime = "medium"
    else: regime = "warm"
    if use_liquid:
        form = "Liquida (topcoat) su base solida"
        if regime in ("very_cold","cold"):
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

def recommended_structure(Tsurf):
    if Tsurf <= -10: return "Linear Fine (freddo/secco)"
    if Tsurf <= -3:  return "Cross Hatch leggera (universale freddo)"
    if Tsurf <= 0.5: return "Diagonal / Scarico a V (umido)"
    return "Wave marcata (bagnato caldo)"

def tune_for(Tsurf, discipline):
    if Tsurf <= -10:
        fam = "Linear Fine"; base = 0.5; side = {"SL":88.5,"GS":88.0,"SG":87.5,"DH":87.5}[discipline]
    elif Tsurf <= -3:
        fam = "Cross Hatch leggera"; base=0.7; side = {"SL":88.0,"GS":88.0,"SG":87.5,"DH":87.0}[discipline]
    else:
        fam = "Diagonal / V"; base = 0.8 if Tsurf<=0.5 else 1.0; side = {"SL":88.0,"GS":87.5,"SG":87.0,"DH":87.0}[discipline]
    return fam, side, base

def classify_snow(row):
    if getattr(row, "ptyp", None) == "rain": return "Neve bagnata/pioggia"
    if getattr(row, "ptyp", None) == "mixed": return "Mista pioggia-neve"
    if getattr(row, "ptyp", None) == "snow" and row.T_surf>-2: return "Neve nuova umida"
    if getattr(row, "ptyp", None) == "snow" and row.T_surf<=-2: return "Neve nuova fredda"
    if getattr(row, "liq_water_pct", 0) >= 3.0: return "Primaverile/trasformata bagnata"
    if row.T_surf<=-8 and getattr(row, "cloud", 0)<0.4: return "Rigelata/ghiacciata"
    return "Compatta/trasformata secca"

# ---------------------- UI helpers ----------------------
def brand_card_html(T, name, base_solid, form, topcoat, brushes, logo_b64):
    logo_html = f"<div class='logo'><img src='data:image/png;base64,{logo_b64}'/></div>" if logo_b64 else "<div class='logo'></div>"
    return f"""
    <style>
    .brand {{ display:flex; align-items:flex-start; gap:.65rem; background:#0e141d; border:1px solid #1e2a3a; border-radius:10px; padding:.75rem .8rem; width:100% }}
    .brand h4 {{ margin:0 0 .25rem 0; font-size:1rem; color:#fff }}
    .brand .muted {{ color:#a9bacb }}
    .brand .sub {{ color:#93b2c6; font-size:.85rem }}
    .brand .logo {{ flex:0 0 auto; display:flex; align-items:center; justify-content:center; width:54px; height:54px; background:#0b121a; border:1px solid #1e2a3a; border-radius:10px; overflow:hidden }}
    .grid {{ display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:.6rem; }}
    </style>
    <div class='brand'>
      {logo_html}
      <div style='flex:1'>
        <h4>{name}</h4>
        <div class='muted'>{T['base_solid']}: <b>{base_solid}</b></div>
        <div class='sub'>Forma: {form}</div>
        <div class='sub'>{T['topcoat_lbl']}: {topcoat}</div>
        <div class='sub'>Spazzole: {brushes}</div>
      </div>
    </div>
    """

def _window_subset(disp: pd.DataFrame, target_day, s, e):
    mask_day = disp["time_local"].dt.date == target_day
    day_df = disp[mask_day]
    if day_df.empty:
        return disp.head(6)
    sel = day_df[(day_df["time_local"].dt.time>=s) & (day_df["time_local"].dt.time<=e)]
    return sel if not sel.empty else day_df.head(6)

# ---------------------- RENDER ----------------------
def render_wax(T, ctx):
    st.markdown("#### 4) Scioline & tuning")
    X = st.session_state.get("_meteo_res")
    if X is None or len(X)==0:
        st.info(T.get("nodata","Nessun dato nella finestra scelta.") + " Calcola prima il meteo (sezione 3).")
        return

    # day & windows dalla UI principale se presenti
    target_day = st.session_state.get("ref_day") or X["time_local"].dt.date.iloc[0]
    A = (st.session_state.get("A_s"), st.session_state.get("A_e"))
    B = (st.session_state.get("B_s"), st.session_state.get("B_e"))
    C = (st.session_state.get("C_s"), st.session_state.get("C_e"))

    blocks = []
    if A[0] and A[1]: blocks.append(("A", A))
    if B[0] and B[1]: blocks.append(("B", B))
    if C[0] and C[1]: blocks.append(("C", C))
    if not blocks:
        blocks = [("Now", (None, None))]

    for lbl, (s, e) in blocks:
        st.markdown("---")
        st.markdown(f"### Blocco {lbl}" if lbl!="Now" else "### Prossime ore")

        if s is not None and e is not None:
            W = _window_subset(X, target_day, s, e)
        else:
            W = X.head(6)

        if W is None or W.empty:
            st.info(T.get("nodata","Nessun dato nella finestra scelta.")); continue

        # metriche
        t_med = float(W["T_surf"].mean())
        rh_med = float(W["RH"].mean())
        v_eff = float(W["wind"].mean())
        cond = classify_snow(W.iloc[0]) if "T_surf" in W.columns else "—"

        st.markdown(
            f"<div class='banner' style='border-left:6px solid #f97316; background:#1a2230; padding:.75rem .9rem; border-radius:10px;'>"
            f"<b>{T['cond']}</b> {cond} · <b>T_neve med</b> {t_med:.1f}°C · "
            f"<b>UR med</b> {rh_med:.0f}% · <b>V eff</b> {v_eff:.1f} m/s</div>",
            unsafe_allow_html=True
        )

        # struttura neve
        st.markdown(f"**{T['struct']}** {recommended_structure(t_med)}")

        # forma & spazzole
        wax_form, brush_seq, use_topcoat = wax_form_and_brushes(t_med, rh_med)

        # cards brand
        st.markdown("<div class='grid'>", unsafe_allow_html=True)
        for (name, solid_bands, liquid_bands) in BRANDS:
            rec_solid  = pick_wax(solid_bands, t_med, rh_med)
            topcoat = (pick_liquid(liquid_bands, t_med, rh_med) if use_topcoat
                       else ("non necessario" if ctx.get("lang","IT")=="IT" else "not needed"))
            logo_b64 = get_brand_logo_b64(name)
            html = brand_card_html(T, name, rec_solid, wax_form, topcoat, brush_seq, logo_b64)
            st.markdown(html, unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # tuning per disciplina
        rows=[]
        for d in ["SL","GS","SG","DH"]:
            fam, side, base = tune_for(t_med, d)
            rows.append((d, fam, f"{side:.1f}°", f"{base:.1f}°"))
        tune_list = "".join([f"<li><b>{d}</b>: {fam} — SIDE {side} · BASE {base}</li>" for d,fam,side,base in rows])
        st.markdown(
            "<div class='card' style='background:#121821; border:1px solid #1f2937; border-radius:12px; padding:.9rem .95rem;'>"
            "<div><b>Tuning per disciplina</b></div>"
            f"<ul class='small' style='margin:.5rem 0 0 1rem'>{tune_list}</ul>"
            "</div>", unsafe_allow_html=True
        )

# alias che l’orchestratore riconosce
render = render_wax
