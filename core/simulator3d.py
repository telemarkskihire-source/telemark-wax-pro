# core/simulator3d.py

import numpy as np
import pandas as pd
import pydeck as pdk
import plotly.graph_objects as go

def filter_track_by_altitude(track_df: pd.DataFrame,
                             alt_start: float,
                             alt_end: float) -> pd.DataFrame:
    """
    track_df: DataFrame con colonne ['lat', 'lon', 'elev'] ordinato lungo la pista.
    alt_start: altitudine di partenza scelta dall'utente (m)
    alt_end: altitudine di arrivo scelta dall'utente (m)
    """
    df = track_df.sort_index().copy()

    # Normalizziamo: alt_start più alto, alt_end più basso (tipico in discesa)
    high = max(alt_start, alt_end)
    low = min(alt_start, alt_end)

    # Prendiamo solo i punti tra le due quote
    mask = (df["elev"] <= high) & (df["elev"] >= low)
    df_seg = df.loc[mask].copy()

    # Safety: se è vuoto, ritorniamo l’intera pista
    if df_seg.empty:
        return df

    # Ricalcoliamo distanza cumulativa per il segmento
    df_seg["dist"] = compute_cumulative_distance(df_seg["lat"].values,
                                                 df_seg["lon"].values)
    return df_seg


def compute_cumulative_distance(lats, lons):
    """
    Distanza cumulativa in metri lungo la traccia.
    Semplice formula di Haversine.
    """
    R = 6371000  # raggio Terra in m
    lats_rad = np.radians(lats)
    lons_rad = np.radians(lons)

    dlat = np.diff(lats_rad)
    dlon = np.diff(lons_rad)

    a = np.sin(dlat / 2) ** 2 + np.cos(lats_rad[:-1]) * np.cos(lats_rad[1:]) * np.sin(dlon / 2) ** 2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    d = R * c

    dist = np.concatenate([[0], np.cumsum(d)])
    return dist


def build_3d_deck(track_df: pd.DataFrame) -> pdk.Deck:
    """
    Crea l'oggetto pydeck.Deck per la vista 3D della pista.
    """
    if track_df.empty:
        raise ValueError("Track DataFrame is empty")

    # path = lista di [lon, lat, elev]
    path = track_df[["lon", "lat", "elev"]].values.tolist()

    data = [{
        "path": path,
        "name": "Ski run",
    }]

    layer = pdk.Layer(
        "PathLayer",
        data=data,
        get_path="path",
        get_color=[255, 0, 0],
        width_scale=10,
        width_min_pixels=3,
        get_width=4,
        elevation_scale=1,
        # pydeck PathLayer non usa direttamente l'elev come "height" verticale,
        # ma possiamo sfruttare il pitch e l'elevation_scale per simulare 3D.
        pickable=True,
    )

    view_state = pdk.ViewState(
        latitude=float(track_df["lat"].mean()),
        longitude=float(track_df["lon"].mean()),
        zoom=13,
        pitch=60,   # inclina la camera per effetto 3D
        bearing=30, # ruota la vista
    )

    deck = pdk.Deck(
        layers=[layer],
        initial_view_state=view_state,
        map_style="mapbox://styles/mapbox/satellite-v9",
        tooltip={"text": "{name}"}
    )
    return deck


def build_altitude_profile(track_df: pd.DataFrame) -> go.Figure:
    """
    Crea il grafico profilo altimetrico (distanza vs quota).
    Si aspetta che track_df abbia 'dist' (metri) e 'elev' (m).
    """
    # Se dist non esiste, ricalcoliamo
    if "dist" not in track_df.columns:
        track_df = track_df.copy()
        track_df["dist"] = compute_cumulative_distance(
            track_df["lat"].values,
            track_df["lon"].values
        )

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=track_df["dist"],
            y=track_df["elev"],
            mode="lines",
            name="Altitudine"
        )
    )

    fig.update_layout(
        xaxis_title="Distanza lungo la pista (m)",
        yaxis_title="Altitudine (m)",
        margin=dict(l=40, r=20, t=40, b=40),
        height=300,
    )

    return fig
