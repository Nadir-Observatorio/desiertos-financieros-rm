"""Escenarios de localización de puntos nuevos (protocolo, sección 7; exploratorio).

- MCLP (cobertura máxima): elegir k candidatos que maximicen la población hoy en desierto que
  queda a 15 minutos a pie o menos de algún punto nuevo. Programa entero resuelto con HiGHS
  (scipy.optimize.milp); se informa la brecha de optimalidad y, como referencia, la solución voraz.
- p-mediana: elegir k candidatos que minimicen el tiempo a pie ponderado por población de la
  demanda en desierto, contando el punto existente más cercano (tiempo actual). Heurística de
  adición voraz más intercambio (Teitz y Bart); se rotula como heurística.

Demanda: celdas desierto con su población. Candidatos: centros de celdas desierto pobladas.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.optimize import Bounds, LinearConstraint, milp

from desiertos.errores import ErrorDatos


@dataclass(frozen=True)
class SolucionCobertura:
    k: int
    elegidos: list[str]
    cubierta: float
    brecha: float
    metodo: str


def _matriz_cobertura(pares: pd.DataFrame, umbral: float) -> dict[str, set[str]]:
    """Candidato -> conjunto de demandas que cubre (minutos <= umbral)."""
    validos = pares[pares["minutos"] <= umbral]
    return {str(c): set(map(str, g["h3_origen"])) for c, g in validos.groupby("h3_candidato")}


def mclp_voraz(pesos: pd.Series, pares: pd.DataFrame, k: int, umbral: float) -> SolucionCobertura:
    """Cobertura máxima por adición voraz (referencia)."""
    cubre = _matriz_cobertura(pares, umbral)
    cubiertas: set[str] = set()
    elegidos: list[str] = []
    for _ in range(min(k, len(cubre))):
        mejor, ganancia = None, 0.0
        for c, demandas in cubre.items():
            if c in elegidos:
                continue
            g = float(pesos.reindex(list(demandas - cubiertas)).fillna(0).sum())
            if g > ganancia:
                mejor, ganancia = c, g
        if mejor is None:
            break
        elegidos.append(mejor)
        cubiertas |= cubre[mejor]
    total = float(pesos.reindex(list(cubiertas)).fillna(0).sum())
    return SolucionCobertura(k, elegidos, total, float("nan"), "voraz")


def mclp(
    pesos: pd.Series,
    pares: pd.DataFrame,
    k: int,
    umbral: float,
    tiempo_limite_s: int = 120,
) -> SolucionCobertura:
    """Cobertura máxima exacta (HiGHS vía scipy.optimize.milp). `pesos` por h3 de demanda."""
    if k < 1:
        raise ErrorDatos("k debe ser al menos 1")
    cubre = _matriz_cobertura(pares, umbral)
    if not cubre:
        raise ErrorDatos("Ningún candidato cubre demanda dentro del umbral")
    candidatos = sorted(cubre)
    demandas = sorted({d for s in cubre.values() for d in s})
    ic = {c: i for i, c in enumerate(candidatos)}
    idm = {d: i for i, d in enumerate(demandas)}
    nc, nd = len(candidatos), len(demandas)
    w = np.array([float(pesos.get(d, 0.0)) for d in demandas])
    costo = np.concatenate([np.zeros(nc), -w])
    filas, columnas, valores = [], [], []
    for c, ds in cubre.items():
        for d in ds:
            filas.append(idm[d])
            columnas.append(ic[c])
            valores.append(-1.0)
    filas += list(range(nd))
    columnas += [nc + i for i in range(nd)]
    valores += [1.0] * nd
    cubrir = sparse.csr_matrix((valores, (filas, columnas)), shape=(nd, nc + nd))
    limite = sparse.csr_matrix(np.concatenate([np.ones(nc), np.zeros(nd)]))
    restricciones = [
        LinearConstraint(cubrir, -np.inf, 0.0),
        LinearConstraint(limite, -np.inf, float(k)),
    ]
    enteros = np.concatenate([np.ones(nc), np.zeros(nd)])
    salida = milp(
        costo,
        constraints=restricciones,
        integrality=enteros,
        bounds=Bounds(0.0, 1.0),
        options={"time_limit": tiempo_limite_s, "mip_rel_gap": 1e-4, "disp": False},
    )
    if salida.x is None:
        raise ErrorDatos(f"HiGHS no entregó solución: {salida.message}")
    elegidos = [candidatos[i] for i in np.flatnonzero(salida.x[:nc] > 0.5)]
    cubiertas = {d for c in elegidos for d in cubre[c]}
    valor = float(pesos.reindex(list(cubiertas)).fillna(0).sum())
    brecha = float(getattr(salida, "mip_gap", 0.0) or 0.0)
    return SolucionCobertura(k, elegidos, valor, brecha, "highs")


def p_mediana(
    pesos: pd.Series,
    tiempo_actual: pd.Series,
    pares: pd.DataFrame,
    k: int,
    iteraciones: int = 20,
) -> tuple[list[str], float]:
    """p-mediana con puntos existentes: adición voraz e intercambio. Devuelve (elegidos, objetivo).

    Objetivo: suma de población por minutos al punto más cercano (existente o nuevo).
    """
    demandas = list(pesos.index)
    pos = {d: i for i, d in enumerate(demandas)}
    w = pesos.to_numpy(dtype=float)
    base = tiempo_actual.reindex(demandas).to_numpy(dtype=float)
    if np.isnan(base).any():
        raise ErrorDatos("Falta el tiempo actual de alguna demanda")
    columnas: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    validos = pares[pares["h3_origen"].isin(pos)]
    for c, g in validos.groupby("h3_candidato"):
        filas = np.array([pos[d] for d in g["h3_origen"]])
        columnas[str(c)] = (filas, g["minutos"].to_numpy(dtype=float))
    if not columnas:
        raise ErrorDatos("Ningún candidato alcanza demanda")

    def objetivo(elegidos: list[str]) -> tuple[float, np.ndarray]:
        actual = base.copy()
        for c in elegidos:
            filas, minutos = columnas[c]
            actual[filas] = np.minimum(actual[filas], minutos)
        return float(np.sum(w * actual)), actual

    elegidos: list[str] = []
    valor, actual = objetivo(elegidos)
    for _ in range(min(k, len(columnas))):
        mejor, mejor_valor = None, valor
        for c, (filas, minutos) in columnas.items():
            if c in elegidos:
                continue
            ahorro = np.sum(w[filas] * np.maximum(actual[filas] - minutos, 0.0))
            if valor - ahorro < mejor_valor:
                mejor, mejor_valor = c, valor - ahorro
        if mejor is None:
            break
        elegidos.append(mejor)
        valor, actual = objetivo(elegidos)
    for _ in range(iteraciones):
        mejoro = False
        for i in range(len(elegidos)):
            sin_i = elegidos[:i] + elegidos[i + 1 :]
            valor_sin, actual_sin = objetivo(sin_i)
            mejor, mejor_valor = elegidos[i], valor
            for c, (filas, minutos) in columnas.items():
                if c in elegidos:
                    continue
                ahorro = np.sum(w[filas] * np.maximum(actual_sin[filas] - minutos, 0.0))
                if valor_sin - ahorro < mejor_valor - 1e-9:
                    mejor, mejor_valor = c, valor_sin - ahorro
            if mejor != elegidos[i]:
                elegidos[i] = mejor
                valor, actual = objetivo(elegidos)
                mejoro = True
        if not mejoro:
            break
    return elegidos, valor
