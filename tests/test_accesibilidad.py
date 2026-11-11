from __future__ import annotations

import datetime as dt

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point

from desiertos import CRS_GEOGRAFICO, CRS_METRICO_RM
from desiertos.accesibilidad import CalculoMatriz, Escenario, por_tramos, tiempo_minimo
from desiertos.errores import ErrorDatos

SALIDA = dt.datetime(2026, 11, 17, 10, 0)


def _celdas(coordenadas: list[tuple[float, float]]) -> pd.DataFrame:
    filas = []
    for lat, lon in coordenadas:
        celda = h3.latlng_to_cell(lat, lon, 9)
        clat, clon = h3.cell_to_latlng(celda)
        filas.append({"h3": celda, "lat": clat, "lon": clon})
    return pd.DataFrame(filas)


def _recta(velocidad_kmh: float = 3.6) -> CalculoMatriz:
    """Calculador falso: tiempo = distancia en línea recta / velocidad, con tope."""

    def calcular(o: gpd.GeoDataFrame, d: gpd.GeoDataFrame, e: Escenario) -> pd.DataFrame:
        a = o.to_crs(CRS_METRICO_RM)
        b = d.to_crs(CRS_METRICO_RM)
        filas = []
        for oid, go in zip(a["id"], a.geometry, strict=True):
            for did, gd in zip(b["id"], b.geometry, strict=True):
                minutos = go.distance(gd) / (velocidad_kmh * 1000 / 60)
                filas.append(
                    {
                        "from_id": oid,
                        "to_id": did,
                        "travel_time": round(minutos) if minutos <= e.tope_min else np.nan,
                    }
                )
        return pd.DataFrame(filas)

    return calcular


def _puntos(coordenadas: list[tuple[float, float]]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"id_punto": [f"p{i}" for i in range(len(coordenadas))]},
        geometry=[Point(lon, lat) for lat, lon in coordenadas],
        crs=CRS_GEOGRAFICO,
    )


def test_tiempo_minimo_a_pie_igual_al_completo() -> None:
    celdas = _celdas([(-33.44, -70.65), (-33.60, -70.70), (-33.90, -71.20)])
    puntos = _puntos([(-33.445, -70.65), (-33.61, -70.70), (-33.40, -70.60)])
    escenario = Escenario("a_pie", "a_pie", 120, 3.6, SALIDA)
    calc = _recta()
    podado = tiempo_minimo(celdas, puntos, escenario, calc).set_index("h3")["minutos"]
    origenes = gpd.GeoDataFrame(
        {"id": celdas["h3"]},
        geometry=gpd.points_from_xy(celdas["lon"], celdas["lat"]),
        crs=CRS_GEOGRAFICO,
    )
    destinos = gpd.GeoDataFrame({"id": puntos["id_punto"]}, geometry=puntos.geometry)
    completo = calc(origenes, destinos, escenario).groupby("from_id")["travel_time"].min()
    pd.testing.assert_series_equal(
        podado, completo.reindex(podado.index), check_names=False, check_dtype=False
    )
    assert np.isnan(podado.iloc[2])


def test_por_tramos_censura_y_recupera_lejanas() -> None:
    celdas = _celdas([(-33.44, -70.65), (-33.47, -70.65), (-34.20, -70.65)])
    puntos = _puntos([(-33.44, -70.651)])
    escenario = Escenario("a_pie", "a_pie", 120, 3.6, SALIDA)
    tabla = por_tramos(celdas, puntos, escenario, _recta(), 30).set_index("h3")
    cerca, media, lejos = celdas["h3"]
    assert tabla.loc[cerca, "minutos"] < 5
    assert 30 < tabla.loc[media, "minutos"] < 120
    assert not tabla.loc[media, "censurada"]
    assert tabla.loc[lejos, "censurada"]
    assert tabla.loc[lejos, "minutos"] == 120


def test_no_peatonal_usa_vecinos() -> None:
    celdas = _celdas([(-33.44, -70.65)])
    puntos = _puntos([(-33.441, -70.65), (-33.50, -70.65)])
    escenario = Escenario("auto", "auto", 60, 3.6, SALIDA)
    tabla = tiempo_minimo(celdas, puntos, escenario, _recta(40.0))
    assert tabla["minutos"].iloc[0] == 0


def test_errores() -> None:
    escenario = Escenario("a_pie", "a_pie", 120, 3.6, SALIDA)
    with pytest.raises(ErrorDatos):
        tiempo_minimo(pd.DataFrame({"h3": []}), _puntos([(-33.4, -70.6)]), escenario, _recta())
    with pytest.raises(ErrorDatos):
        por_tramos(_celdas([(-33.44, -70.65)]), _puntos([(-33.4, -70.6)]), escenario, _recta(), 120)


def test_puntos_con_indice_no_contiguo() -> None:
    celdas = _celdas([(-33.44, -70.65)])
    puntos = _puntos([(-33.441, -70.65), (-33.50, -70.65), (-33.445, -70.65)])
    filtrados = puntos[puntos["id_punto"] != "p0"]
    escenario = Escenario("a_pie", "a_pie", 60, 3.6, SALIDA)
    tabla = tiempo_minimo(celdas, filtrados, escenario, _recta())
    assert tabla["minutos"].iloc[0] > 0
