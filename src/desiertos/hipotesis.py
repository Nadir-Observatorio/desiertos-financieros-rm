"""Hipótesis confirmatorias H1 a H3 (protocolo sellado, secciones 5 y 6; enmiendas E-2 y E-6).

- H1: proporción de población en desierto en celdas rurales menos la de celdas urbanas, en puntos
  porcentuales. Bootstrap por bloques H3; p unilateral = fracción de réplicas con efecto <= 0.
- H2: proporción de 60 años y más (E-2) dentro de las celdas desierto dividida por la de toda el
  área. Bootstrap por bloques; p unilateral = fracción de réplicas con razón <= 1.
- H3: I de Moran de log(1 + minutos) con vecindad de anillo 1 entre celdas pobladas y 999
  permutaciones; p unilateral = (permutaciones con I >= observado + 1) / (999 + 1).
- Holm sobre los tres p, alfa familiar 0,05.
"""

from __future__ import annotations

from dataclasses import dataclass

import h3
import numpy as np
import pandas as pd
from esda.moran import Moran
from libpysal.weights import W

from desiertos.errores import ErrorDatos

SEMILLA = 20261109
REPLICAS = 2000
PERMUTACIONES = 999
ALFA = 0.05
COLUMNAS = ("h3", "n_per", "rural", "n_60_mas", "n_per_con_60", "minutos")


@dataclass(frozen=True)
class Resultado:
    hipotesis: str
    efecto: float
    ic_inf: float
    ic_sup: float
    p: float
    nulo: float


def _validar(tabla: pd.DataFrame) -> None:
    faltan = set(COLUMNAS) - set(tabla.columns)
    if faltan:
        raise ErrorDatos(f"Faltan columnas para las hipótesis: {sorted(faltan)}")
    if tabla.empty:
        raise ErrorDatos("No hay celdas para probar hipótesis")


def _componentes(tabla: pd.DataFrame, umbral: float) -> pd.DataFrame:
    """Sumas por celda que bastan para H1 y H2 (se agregan por bloque en el bootstrap)."""
    desierto = (tabla["minutos"] > umbral).to_numpy()
    rural = tabla["rural"].to_numpy(dtype=bool)
    pob = tabla["n_per"].to_numpy(dtype=float)
    return pd.DataFrame(
        {
            "rur_pob": np.where(rural, pob, 0.0),
            "rur_des": np.where(rural & desierto, pob, 0.0),
            "urb_pob": np.where(~rural, pob, 0.0),
            "urb_des": np.where(~rural & desierto, pob, 0.0),
            "des_60": np.where(desierto, tabla["n_60_mas"].to_numpy(dtype=float), 0.0),
            "des_base": np.where(desierto, tabla["n_per_con_60"].to_numpy(dtype=float), 0.0),
            "tot_60": tabla["n_60_mas"].to_numpy(dtype=float),
            "tot_base": tabla["n_per_con_60"].to_numpy(dtype=float),
        }
    )


def _h1(s: np.ndarray) -> np.ndarray:
    # s: (..., 8) en el orden de _componentes
    return np.asarray(100.0 * (s[..., 1] / s[..., 0] - s[..., 3] / s[..., 2]), dtype=float)


def _h2(s: np.ndarray) -> np.ndarray:
    return np.asarray((s[..., 4] / s[..., 5]) / (s[..., 6] / s[..., 7]), dtype=float)


def bootstrap_por_bloques(
    tabla: pd.DataFrame,
    umbral: float,
    resolucion_bloque: int,
    replicas: int = REPLICAS,
    semilla: int = SEMILLA,
) -> tuple[Resultado, Resultado]:
    """H1 y H2 con bootstrap por bloques H3 (IC 95 % por percentiles, p unilateral)."""
    _validar(tabla)
    comp = _componentes(tabla, umbral)
    bloques = [h3.cell_to_parent(c, resolucion_bloque) for c in tabla["h3"]]
    por_bloque = comp.groupby(np.asarray(bloques)).sum().to_numpy()
    observado = por_bloque.sum(axis=0)
    if observado[0] <= 0 or observado[2] <= 0:
        raise ErrorDatos("H1 necesita población rural y urbana")
    if observado[5] <= 0:
        raise ErrorDatos("H2 necesita población en celdas desierto")
    rng = np.random.default_rng(semilla)
    n = por_bloque.shape[0]
    conteos = rng.multinomial(n, np.full(n, 1.0 / n), size=replicas)
    sumas = conteos @ por_bloque
    with np.errstate(divide="ignore", invalid="ignore"):
        r1, r2 = _h1(sumas), _h2(sumas)
    salida = []
    for nombre, obs, rep, nulo in (
        ("H1", float(_h1(observado)), r1, 0.0),
        ("H2", float(_h2(observado)), r2, 1.0),
    ):
        validas = rep[np.isfinite(rep)]
        salida.append(
            Resultado(
                nombre,
                obs,
                float(np.percentile(validas, 2.5)),
                float(np.percentile(validas, 97.5)),
                float(np.mean(validas <= nulo)),
                nulo,
            )
        )
    return salida[0], salida[1]


def vecindad_anillo(celdas: pd.Series) -> W:
    """Pesos de anillo 1 entre celdas presentes; las celdas sin vecino quedan fuera."""
    presentes = set(celdas)
    vecinos = {c: sorted(v for v in h3.grid_ring(c, 1) if v in presentes) for c in celdas}
    vecinos = {c: v for c, v in vecinos.items() if v}
    if not vecinos:
        raise ErrorDatos("Ninguna celda tiene vecinos poblados")
    pesos = W(vecinos, silence_warnings=True)
    pesos.transform = "r"
    return pesos


def moran_log_tiempo(
    tabla: pd.DataFrame,
    columna: str = "minutos",
    permutaciones: int = PERMUTACIONES,
    semilla: int = SEMILLA,
) -> Resultado:
    """H3: I de Moran de log(1 + tiempo), p unilateral por permutaciones."""
    _validar(tabla)
    pesos = vecindad_anillo(tabla["h3"])
    valores = pd.Series(np.log1p(tabla[columna].to_numpy(dtype=float)), index=tabla["h3"])
    y = valores.loc[pesos.id_order].to_numpy()
    np.random.seed(semilla)
    m = Moran(y, pesos, permutations=permutaciones)
    mayores = int(np.sum(m.sim >= m.I))
    p = (mayores + 1) / (permutaciones + 1)
    return Resultado("H3", float(m.I), float("nan"), float("nan"), p, 0.0)


def moran_valores(tabla: pd.DataFrame, valores: np.ndarray, semilla: int = SEMILLA) -> float:
    """I de Moran de una variable por celda (diagnóstico de residuos), sin permutaciones."""
    pesos = vecindad_anillo(tabla["h3"])
    serie = pd.Series(valores, index=tabla["h3"].to_numpy())
    np.random.seed(semilla)
    return float(Moran(serie.loc[pesos.id_order].to_numpy(), pesos, permutations=0).I)


def residuos(tabla: pd.DataFrame, umbral: float) -> tuple[np.ndarray, np.ndarray]:
    """Residuos por celda de H1 (desierto menos media ponderada de su grupo) y de H2
    (proporción de 60 y más de la celda menos la de toda el área)."""
    desierto = (tabla["minutos"] > umbral).astype(float).to_numpy()
    rural = tabla["rural"].to_numpy(dtype=bool)
    pob = tabla["n_per"].to_numpy(dtype=float)
    medias = np.where(
        rural,
        np.sum(desierto * pob * rural) / np.sum(pob * rural),
        np.sum(desierto * pob * ~rural) / np.sum(pob * ~rural),
    )
    base = tabla["n_per_con_60"].to_numpy(dtype=float)
    n60 = tabla["n_60_mas"].to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        prop = np.where(base > 0, n60 / base, 0.0)
    return desierto - medias, prop - n60.sum() / base.sum()


def holm(p: dict[str, float], alfa: float = ALFA) -> dict[str, tuple[float, bool]]:
    """p ajustados de Holm (monótonos) y decisión al nivel alfa."""
    orden = sorted(p, key=lambda k: p[k])
    m = len(orden)
    ajustados: dict[str, float] = {}
    previo = 0.0
    for i, clave in enumerate(orden):
        valor = min(1.0, max(previo, (m - i) * p[clave]))
        ajustados[clave] = valor
        previo = valor
    return {k: (ajustados[k], ajustados[k] < alfa) for k in p}
