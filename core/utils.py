# core/utils.py
import time
import requests
import numpy as np

UA = {"User-Agent":"telemark-wax-pro/1.0"}

def persist(key, default):
    import streamlit as st
    if key not in st.session_state: st.session_state[key]=default
    return st.session_state[key]

def _retry(func, attempts=2, sleep=0.8):
    for i in range(attempts):
        try:
            return func()
        except Exception:
            if i==attempts-1:
                raise
            time.sleep(sleep*(1.5**i))

def flag(cc:str)->str:
    try:
        c=cc.upper(); return chr(127397+ord(c[0]))+chr(127397+ord(c[1]))
    except: 
        return "🏳️"

def concise_label(addr:dict, fallback:str)->str:
    # compat con nominatim; per Open-Meteo usiamo name/admin1 separati
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village")
            or addr.get("town") or addr.get("city") or fallback)
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    parts = [p for p in [name, admin1] if p]
    s = ", ".join(parts)
    return f"{s} — {cc}" if cc else s
