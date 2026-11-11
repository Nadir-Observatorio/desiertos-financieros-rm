"""Paso de la población censal a la grilla H3 por ponderación de área.

Protocolo sellado, sección 2.3: densidad uniforme dentro de cada manzana o entidad. Sección 2.4:
una celda es rural si más del 50 % de su población asignada viene de unidades rurales. Tablas por
comuna: cada celda toma la comuna que le aporta más población (empate: el código menor).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
from shapely.geometry import Polygon

from desiertos import CRS_GEOGRAFICO, CRS_METRICO_RM
from desiertos.errores import ErrorDatos

UMBRAL_RURAL = 0.5
POBLACION_MINIMA = 1.0  # Protocolo 2.3: celda poblada si su población asignada es >= 1.


def celdas_que_tocan(geometria: Any, resolucion: int) -> list[str]:
    """Celdas H3 que se superponen (aunque sea en parte) con un polígono en EPSG:4326."""
    if geometria is None or geometria.is_empty:
        return []
    forma = h3.geo_to_h3shape(geometria.__geo_interface__)
    celdas = h3.h3shape_to_cells_experimental(forma, resolucion, contain="overlap")
    return list(celdas)


def poligono_celda(celda: str) -> Polygon:
    """Polígono de una celda H3 con coordenadas (lon, lat)."""
    return Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(celda)])


def _grilla(celdas: Iterable[str]) -> gpd.GeoDataFrame:
    unicas = sorted(set(celdas))
    return gpd.GeoDataFrame(
        {"h3": unicas}, geometry=[poligono_celda(c) for c in unicas], crs=CRS_GEOGRAFICO
    )


def pesos_por_area(unidades: gpd.GeoDataFrame, resolucion: int) -> pd.DataFrame:
    """Fracción del área de cada unidad que cae en cada celda (suma 1 por unidad)."""
    if unidades.crs is None:
        raise ErrorDatos("Unidades sin sistema de referencia")
    base = unidades.to_crs(CRS_GEOGRAFICO)
    todas: list[str] = []
    for geom in base.geometry:
        todas.extend(celdas_que_tocan(geom, resolucion))
    if not todas:
        raise ErrorDatos("Ninguna unidad toca la grilla H3")
    grilla = _grilla(todas).to_crs(CRS_METRICO_RM)
    piezas = gpd.overlay(
        base[["manzent", "geometry"]].to_crs(CRS_METRICO_RM),
        grilla,
        how="intersection",
        keep_geom_type=True,
    )
    piezas["area_m2"] = piezas.geometry.area
    piezas = piezas.loc[piezas["area_m2"] > 0, ["manzent", "h3", "area_m2"]]
    total = piezas.groupby("manzent")["area_m2"].transform("sum")
    piezas["peso"] = piezas["area_m2"] / total
    perdidas = set(base["manzent"]) - set(piezas["manzent"])
    if perdidas:
        raise ErrorDatos(f"{len(perdidas)} unidades quedaron sin celda (geometrías vacías)")
    return pd.DataFrame(piezas[["manzent", "h3", "peso"]]).reset_index(drop=True)


def pesos_dasimetricos(
    unidades: gpd.GeoDataFrame, edificios: gpd.GeoDataFrame, resolucion: int
) -> pd.DataFrame:
    """Pesos de la sensibilidad dasimétrica (enmienda E-6).

    La población de cada entidad rural con edificios de OSM dentro se reparte entre las celdas en
    proporción al área de planta de esos edificios (cada edificio cuenta en la celda de su punto).
    Las entidades rurales sin edificios y todas las manzanas urbanas conservan los pesos por área.
    """
    faltan = {"manzent", "area"} - set(unidades.columns)
    if faltan:
        raise ErrorDatos(f"Faltan columnas en unidades: {sorted(faltan)}")
    if "area_m2" not in edificios.columns or edificios.crs is None:
        raise ErrorDatos("Edificios sin area_m2 o sin sistema de referencia")
    por_area = pesos_por_area(unidades, resolucion)
    rurales = unidades.loc[unidades["area"] == "RURAL", ["manzent", "geometry"]]
    dentro = gpd.sjoin(
        edificios[["area_m2", "geometry"]],
        rurales.to_crs(edificios.crs),
        how="inner",
        predicate="within",
    )
    dentro = dentro[dentro["area_m2"] > 0]
    if dentro.empty:
        return por_area
    puntos = dentro.geometry.to_crs(CRS_GEOGRAFICO)
    dentro = pd.DataFrame(
        {
            "manzent": dentro["manzent"].to_numpy(),
            "h3": [h3.latlng_to_cell(p.y, p.x, resolucion) for p in puntos],
            "area_m2": dentro["area_m2"].to_numpy(dtype=float),
        }
    )
    por_edificio = dentro.groupby(["manzent", "h3"], as_index=False)["area_m2"].sum()
    por_edificio["peso"] = por_edificio["area_m2"] / por_edificio.groupby("manzent")[
        "area_m2"
    ].transform("sum")
    con_edificios = set(por_edificio["manzent"])
    partes: list[pd.DataFrame] = [
        pd.DataFrame(por_area[~por_area["manzent"].isin(con_edificios)]),
        pd.DataFrame(por_edificio[["manzent", "h3", "peso"]]),
    ]
    return pd.concat(partes, ignore_index=True)


def poblacion_por_celda(
    unidades: gpd.GeoDataFrame, resolucion: int, pesos: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Tabla de población por celda H3.

    Columnas: h3, cut, n_per, n_per_rural, n_60_mas, n_per_con_60 (población de las unidades con
    dato de 60 y más publicado), rural (bool), lat, lon (centro de la celda). Sin pesos se reparte
    por área (método sellado); con pesos, por los que se entreguen (manzent, h3, peso).
    """
    if pesos is None:
        pesos = pesos_por_area(unidades, resolucion)
    else:
        faltan = {"manzent", "h3", "peso"} - set(pesos.columns)
        if faltan:
            raise ErrorDatos(f"Faltan columnas en pesos: {sorted(faltan)}")
        sumas = pesos.groupby("manzent")["peso"].sum()
        if not np.allclose(sumas.to_numpy(), 1.0):
            raise ErrorDatos("Los pesos de alguna unidad no suman 1")
    atributos = pd.DataFrame(unidades.drop(columns="geometry"))
    tabla = pesos.merge(atributos, on="manzent", how="left", validate="many_to_one")
    w = tabla["peso"]
    rural = (tabla["area"] == "RURAL").to_numpy()
    con_60 = tabla["n_60_mas"].notna().to_numpy()
    tabla["n_per_w"] = tabla["n_per"] * w
    tabla["n_per_rural_w"] = np.where(rural, tabla["n_per_w"], 0.0)
    tabla["n_60_w"] = np.where(con_60, tabla["n_60_mas"].fillna(0.0) * w, 0.0)
    tabla["n_per_con_60_w"] = np.where(con_60, tabla["n_per_w"], 0.0)

    por_comuna = tabla.groupby(["h3", "cut"])["n_per_w"].sum().reset_index()
    por_comuna = por_comuna.sort_values(["h3", "n_per_w", "cut"], ascending=[True, False, True])
    comuna = por_comuna.drop_duplicates("h3")[["h3", "cut"]]

    celdas = (
        tabla.groupby("h3", as_index=False)[
            ["n_per_w", "n_per_rural_w", "n_60_w", "n_per_con_60_w"]
        ]
        .sum()
        .rename(
            columns={
                "n_per_w": "n_per",
                "n_per_rural_w": "n_per_rural",
                "n_60_w": "n_60_mas",
                "n_per_con_60_w": "n_per_con_60",
            }
        )
        .merge(comuna, on="h3", how="left", validate="one_to_one")
    )
    celdas = celdas.loc[celdas["n_per"] >= POBLACION_MINIMA].copy()
    celdas["rural"] = celdas["n_per_rural"] / celdas["n_per"] > UMBRAL_RURAL
    centros = [h3.cell_to_latlng(c) for c in celdas["h3"]]
    celdas["lat"] = [c[0] for c in centros]
    celdas["lon"] = [c[1] for c in centros]
    columnas = [
        "h3",
        "cut",
        "n_per",
        "n_per_rural",
        "n_60_mas",
        "n_per_con_60",
        "rural",
        "lat",
        "lon",
    ]
    return celdas[columnas].sort_values("h3").reset_index(drop=True)
