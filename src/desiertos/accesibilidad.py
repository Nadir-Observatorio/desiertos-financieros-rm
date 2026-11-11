"""Tiempo de viaje desde cada celda al punto de acceso más cercano (protocolo y enmienda E-5).

Motor R5 vía r5py. Para no materializar la matriz completa celda por punto, el cálculo se hace por
bloques de celdas (padre H3) y, en cada bloque, solo contra los puntos que podrían alcanzarse:

- A pie, un punto alcanzable en t minutos está a lo sumo a v·t en línea recta (la red nunca es más
  corta que la recta). Se usan los puntos dentro de ese radio más un margen de enganche; el mínimo
  que resulta es exacto.
- En auto y transporte público no hay cota en línea recta útil. Se usan los K puntos más cercanos en
  línea recta de cada celda; el mínimo es una cota superior del tiempo real (se rotula así).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from desiertos import CRS_GEOGRAFICO, CRS_METRICO_RM
from desiertos.errores import ErrorDatos

MARGEN_ENGANCHE_M = 500.0
RESOLUCION_BLOQUE = 6
VECINOS_CANDIDATOS = 30


@dataclass(frozen=True)
class Escenario:
    """Un cálculo: modo, tope, velocidad a pie, hora de salida y ventana."""

    nombre: str
    modo: str  # "a_pie", "auto" o "transporte_publico"
    tope_min: int
    velocidad_kmh: float
    salida: dt.datetime
    ventana_min: int = 0


# Firma del cálculo de una matriz: (origenes, destinos, escenario) -> from_id, to_id, travel_time.
CalculoMatriz = Callable[[gpd.GeoDataFrame, gpd.GeoDataFrame, Escenario], pd.DataFrame]


def _metricos(capa: gpd.GeoDataFrame) -> np.ndarray:
    m = capa.to_crs(CRS_METRICO_RM).geometry
    return np.column_stack([m.x.to_numpy(), m.y.to_numpy()])


def tiempo_minimo(
    celdas: pd.DataFrame,
    puntos: gpd.GeoDataFrame,
    escenario: Escenario,
    calcular: CalculoMatriz,
    progreso: Callable[[int, int], None] | None = None,
) -> pd.DataFrame:
    """Minutos al punto más cercano por celda (h3); NaN si ninguno está dentro del tope.

    `celdas` trae h3, lat y lon; `puntos` trae id_punto y geometría.
    """
    faltan = {"h3", "lat", "lon"} - set(celdas.columns)
    if faltan or "id_punto" not in puntos.columns:
        raise ErrorDatos(f"Faltan columnas para el cálculo de accesibilidad: {sorted(faltan)}")
    if puntos.empty or celdas.empty:
        raise ErrorDatos("No hay celdas o puntos para calcular")
    origenes = gpd.GeoDataFrame(
        {"id": celdas["h3"].to_numpy()},
        geometry=gpd.points_from_xy(celdas["lon"], celdas["lat"]),
        crs=CRS_GEOGRAFICO,
    )
    base = puntos.reset_index(drop=True)
    destinos = gpd.GeoDataFrame(
        {"id": base["id_punto"].to_numpy()}, geometry=base.geometry.to_crs(CRS_GEOGRAFICO)
    )
    xy_o = _metricos(origenes)
    xy_d = _metricos(destinos)
    arbol = cKDTree(xy_d)
    bloques = pd.Series(
        [h3.cell_to_parent(c, RESOLUCION_BLOQUE) for c in origenes["id"]], index=origenes.index
    )
    radio = escenario.velocidad_kmh * 1000.0 / 60.0 * escenario.tope_min + MARGEN_ENGANCHE_M
    resultados: list[pd.Series] = []
    grupos = list(bloques.groupby(bloques).groups.values())
    for i, indices in enumerate(grupos, start=1):
        idx = np.asarray(indices)
        if escenario.modo == "a_pie":
            cercanos = arbol.query_ball_point(xy_o[idx], r=radio)
            elegidos = sorted({j for lista in cercanos for j in lista})
        else:
            k = min(VECINOS_CANDIDATOS, len(destinos))
            _, vecinos = arbol.query(xy_o[idx], k=k)
            elegidos = sorted(set(np.asarray(vecinos).ravel().tolist()))
        if elegidos:
            matriz = calcular(origenes.iloc[idx], destinos.iloc[elegidos], escenario)
            minimo = matriz.dropna(subset=["travel_time"]).groupby("from_id")["travel_time"].min()
            resultados.append(minimo)
        if progreso is not None:
            progreso(i, len(grupos))
    if resultados:
        todos = pd.concat(resultados)
        todos = todos.groupby(level=0).min()
    else:
        todos = pd.Series(dtype=float)
    salida = pd.DataFrame({"h3": celdas["h3"].to_numpy()})
    salida["minutos"] = salida["h3"].map(todos).astype(float)
    return salida


def por_tramos(
    celdas: pd.DataFrame,
    puntos: gpd.GeoDataFrame,
    escenario: Escenario,
    calcular: CalculoMatriz,
    tope_corto_min: int,
    progreso: Callable[[int, int], None] | None = None,
) -> pd.DataFrame:
    """Primero con tope corto para todas; las celdas sin punto se recalculan con el tope final.

    Devuelve h3, minutos y censurada (True si ningún punto está dentro del tope final o si el
    tiempo lo supera; en ese caso minutos queda en el tope).
    """
    if tope_corto_min >= escenario.tope_min:
        raise ErrorDatos("El tope corto debe ser menor que el tope final")
    corto = Escenario(
        escenario.nombre,
        escenario.modo,
        tope_corto_min,
        escenario.velocidad_kmh,
        escenario.salida,
        escenario.ventana_min,
    )
    primero = tiempo_minimo(celdas, puntos, corto, calcular, progreso)
    faltan = primero["minutos"].isna()
    if faltan.any():
        segundo = tiempo_minimo(
            celdas[faltan.to_numpy()], puntos, escenario, calcular, progreso
        ).set_index("h3")["minutos"]
        primero.loc[faltan, "minutos"] = primero.loc[faltan, "h3"].map(segundo)
    # R5 puede sumar la caminata de enganche por sobre el tope: se trata igual que sin punto.
    primero["censurada"] = primero["minutos"].isna() | (primero["minutos"] > escenario.tope_min)
    primero.loc[primero["censurada"], "minutos"] = float(escenario.tope_min)
    return primero


def pares_a_pie(
    origenes_tabla: pd.DataFrame,
    candidatos_tabla: pd.DataFrame,
    escenario: Escenario,
    calcular: CalculoMatriz,
) -> pd.DataFrame:
    """Todos los pares origen-candidato a pie dentro del tope (h3_origen, h3_candidato, minutos).

    Ambas tablas traen h3, lat y lon. Misma poda exacta en línea recta que tiempo_minimo.
    """
    if escenario.modo != "a_pie":
        raise ErrorDatos("Los pares se calculan solo a pie (la poda exige una cota en línea recta)")
    for tabla in (origenes_tabla, candidatos_tabla):
        if {"h3", "lat", "lon"} - set(tabla.columns) or tabla.empty:
            raise ErrorDatos("Origenes y candidatos necesitan h3, lat y lon")
    origenes = gpd.GeoDataFrame(
        {"id": origenes_tabla["h3"].to_numpy()},
        geometry=gpd.points_from_xy(origenes_tabla["lon"], origenes_tabla["lat"]),
        crs=CRS_GEOGRAFICO,
    )
    candidatos = gpd.GeoDataFrame(
        {"id": candidatos_tabla["h3"].to_numpy()},
        geometry=gpd.points_from_xy(candidatos_tabla["lon"], candidatos_tabla["lat"]),
        crs=CRS_GEOGRAFICO,
    )
    xy_o = _metricos(origenes)
    arbol = cKDTree(_metricos(candidatos))
    radio = escenario.velocidad_kmh * 1000.0 / 60.0 * escenario.tope_min + MARGEN_ENGANCHE_M
    bloques = pd.Series([h3.cell_to_parent(c, RESOLUCION_BLOQUE) for c in origenes["id"]])
    partes: list[pd.DataFrame] = []
    for indices in bloques.groupby(bloques).groups.values():
        idx = np.asarray(indices)
        elegidos = sorted(
            {j for lista in arbol.query_ball_point(xy_o[idx], r=radio) for j in lista}
        )
        if not elegidos:
            continue
        matriz = calcular(origenes.iloc[idx], candidatos.iloc[elegidos], escenario)
        matriz = matriz.dropna(subset=["travel_time"])
        partes.append(matriz[matriz["travel_time"] <= escenario.tope_min])
    if not partes:
        return pd.DataFrame(columns=["h3_origen", "h3_candidato", "minutos"])
    todos = pd.concat(partes, ignore_index=True)
    return pd.DataFrame(
        {
            "h3_origen": todos["from_id"].to_numpy(),
            "h3_candidato": todos["to_id"].to_numpy(),
            "minutos": todos["travel_time"].astype(float).to_numpy(),
        }
    )
