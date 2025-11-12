import os, base64, streamlit as st

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

BRANDS = [("Swix",SWIX,SWIX_LQ),("Toko",TOKO,TOKO_LQ),("Vola",VOLA,VOLA_LQ),("Rode",RODE,RODE_LQ),
          ("Holmenkol",HOLM,HOLM_LQ),("Maplus",MAPL,MAPL_LQ),("Start",START,START_LQ),("Skigo",SKIGO,SKIGO_LQ)]

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

def _try_paths(filename: str):
    for root in ["logos", "assets/logos", ".","assets","assets/brand","assets/img"]:
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
# --- EXPORT COMPAT ---
def render_wax(T, ctx):
    for name in ["wax_panel", "show_wax", "main", "render"]:
        fn = globals().get(name)
        if callable(fn):
            return fn(T, ctx)
    import streamlit as st
    st.markdown("**[wax]** pronto (stub).")

render = render_wax
# --- export di fallback ---
if not any(k in globals() for k in ("render_wax","wax_panel","render")):
    def render_wax(T, ctx):
        import streamlit as st
        st.markdown("**[wax_logic]** pronto (stub).")
    render = render_wax
