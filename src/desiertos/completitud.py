"""Completitud de OSM frente a la CMF por comuna (regla P4 del protocolo).

Una comuna es apta si OSM/CMF queda entre 0,8 y 1,25 tanto en sucursales como en cajeros.
Una comuna con cero en la CMF no se puede evaluar y queda como no apta.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd

RAZON_MINIMA = 0.8
RAZON_MAXIMA = 1.25
# Las huellas comunales son la unión de manzanas y entidades: no cubren calles ni plazas. Un punto
# se asigna a la huella más cercana si está a esta distancia o menos (misma tolerancia que E-3).
DISTANCIA_MAXIMA_M = 1000.0


def asignar_comuna(puntos: gpd.GeoDataFrame, huellas: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Agrega la columna clave (comuna) por huella más cercana; descarta lo que queda lejos."""
    metricos = puntos.to_crs(huellas.crs)
    unidos = gpd.sjoin_nearest(
        metricos,
        huellas[["clave", "geometry"]],
        how="inner",
        max_distance=DISTANCIA_MAXIMA_M,
        distance_col="distancia_huella_m",
    )
    unidos = unidos[~unidos.index.duplicated(keep="first")]
    return gpd.GeoDataFrame(unidos.drop(columns="index_right"), crs=huellas.crs)


def conteo_osm_por_comuna(osm: gpd.GeoDataFrame, huellas: gpd.GeoDataFrame) -> pd.DataFrame:
    """Puntos OSM bank y atm por comuna (huella más cercana, hasta 1 km)."""
    unidos = asignar_comuna(osm, huellas)
    tabla = unidos.groupby(["clave", "amenidad"]).size().unstack(fill_value=0)
    tabla = tabla.reindex(columns=["bank", "atm"], fill_value=0)
    tabla.columns = pd.Index(["osm_bank", "osm_atm"])
    return pd.DataFrame(tabla.rename_axis("comuna").reset_index())


def evaluar_completitud(cmf: pd.DataFrame, osm: pd.DataFrame) -> pd.DataFrame:
    """Razones OSM/CMF y aptitud por comuna; incluye todas las comunas de la CMF."""
    tabla = cmf.merge(osm, on="comuna", how="left")
    tabla[["osm_bank", "osm_atm"]] = tabla[["osm_bank", "osm_atm"]].fillna(0).astype(int)
    with np.errstate(divide="ignore", invalid="ignore"):
        tabla["razon_sucursales"] = np.where(
            tabla["cmf_sucursales"] > 0, tabla["osm_bank"] / tabla["cmf_sucursales"], np.nan
        )
        tabla["razon_cajeros"] = np.where(
            tabla["cmf_cajeros"] > 0, tabla["osm_atm"] / tabla["cmf_cajeros"], np.nan
        )
    en_rango_s = tabla["razon_sucursales"].between(RAZON_MINIMA, RAZON_MAXIMA)
    en_rango_c = tabla["razon_cajeros"].between(RAZON_MINIMA, RAZON_MAXIMA)
    tabla["apta"] = en_rango_s & en_rango_c
    return tabla.sort_values("comuna").reset_index(drop=True)


# Bancos con localizador propio (enmienda E-4) y su nombre en los reportes de la CMF.
INSTITUCIONES_CMF = {
    "bci": "Banco de Credito e Inversiones",
    "falabella": "Banco Falabella",
    "scotiabank": "Scotiabank Chile",
}


def conteo_localizadores_por_comuna(
    capa: gpd.GeoDataFrame, huellas: gpd.GeoDataFrame
) -> pd.DataFrame:
    """Sucursales y cajeros de cada banco por comuna (huella más cercana, hasta 1 km)."""
    con_punto = capa[capa.geometry.notna() & ~capa.geometry.is_empty]
    unidos = asignar_comuna(con_punto, huellas)
    unidos["es_sucursal"] = (unidos["tipo"] == "sucursal").astype(int)
    tabla = (
        unidos.groupby(["clave", "banco"])[["es_sucursal", "n_cajeros"]]
        .sum()
        .reset_index()
        .rename(
            columns={"clave": "comuna", "es_sucursal": "loc_sucursales", "n_cajeros": "loc_cajeros"}
        )
    )
    return pd.DataFrame(tabla)


def evaluar_por_banco(cmf_institucion: pd.DataFrame, conteo: pd.DataFrame) -> pd.DataFrame:
    """Razón localizador/CMF por comuna y banco; NaN donde la CMF informa cero."""
    partes = []
    for banco, institucion in INSTITUCIONES_CMF.items():
        cmf = cmf_institucion[cmf_institucion["institucion"] == institucion][
            ["comuna", "cmf_sucursales", "cmf_cajeros"]
        ]
        loc = conteo[conteo["banco"] == banco][["comuna", "loc_sucursales", "loc_cajeros"]]
        tabla = cmf.merge(loc, on="comuna", how="outer").fillna(0)
        tabla.insert(0, "banco", banco)
        partes.append(tabla)
    tabla = pd.concat(partes, ignore_index=True)
    for col in ("cmf_sucursales", "cmf_cajeros", "loc_sucursales", "loc_cajeros"):
        tabla[col] = tabla[col].astype(int)
    with np.errstate(divide="ignore", invalid="ignore"):
        tabla["razon_sucursales"] = np.where(
            tabla["cmf_sucursales"] > 0, tabla["loc_sucursales"] / tabla["cmf_sucursales"], np.nan
        )
        tabla["razon_cajeros"] = np.where(
            tabla["cmf_cajeros"] > 0, tabla["loc_cajeros"] / tabla["cmf_cajeros"], np.nan
        )
    tabla["sucursales_en_rango"] = tabla["razon_sucursales"].between(RAZON_MINIMA, RAZON_MAXIMA)
    tabla["cajeros_en_rango"] = tabla["razon_cajeros"].between(RAZON_MINIMA, RAZON_MAXIMA)
    return tabla.sort_values(["banco", "comuna"]).reset_index(drop=True)
