"""Agrupamientos locales del tiempo a pie (protocolo, sección 7; exploratorio).

- Gi* (Getis-Ord con la propia celda) sobre log(1 + minutos), p por permutaciones y control de
  falsos descubrimientos de Benjamini-Hochberg (q = 0,05).
- LISA (Moran local) con 999 permutaciones; cuadrantes alto-alto, bajo-bajo, alto-bajo y bajo-alto
  con p < 0,05 sin corrección, como es habitual en LISA; se rotula así.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from esda.getisord import G_Local
from esda.moran import Moran_Local

from desiertos.errores import ErrorDatos
from desiertos.hipotesis import PERMUTACIONES, SEMILLA, vecindad_anillo

Q_BH = 0.05
ALFA_LISA = 0.05
_CUADRANTES = {1: "alto_alto", 2: "bajo_alto", 3: "bajo_bajo", 4: "alto_bajo"}


def benjamini_hochberg(p: np.ndarray, q: float = Q_BH) -> np.ndarray:
    """Máscara de descubrimientos con el procedimiento de Benjamini-Hochberg."""
    n = len(p)
    if n == 0:
        return np.zeros(0, dtype=bool)
    orden = np.argsort(p)
    umbrales = q * np.arange(1, n + 1) / n
    pasan = p[orden] <= umbrales
    salida = np.zeros(n, dtype=bool)
    if pasan.any():
        ultimo = int(np.max(np.flatnonzero(pasan)))
        salida[orden[: ultimo + 1]] = True
    return salida


def agrupamientos(
    tabla: pd.DataFrame, permutaciones: int = PERMUTACIONES, semilla: int = SEMILLA
) -> pd.DataFrame:
    """Por celda: z de Gi*, clase de Gi* (caliente, frío, ninguno) y cuadrante LISA."""
    if {"h3", "minutos"} - set(tabla.columns):
        raise ErrorDatos("Faltan h3 o minutos")
    pesos = vecindad_anillo(tabla["h3"])
    valores = pd.Series(np.log1p(tabla["minutos"].to_numpy(dtype=float)), index=tabla["h3"])
    y = valores.loc[pesos.id_order].to_numpy()
    np.random.seed(semilla)
    gi = G_Local(y, pesos, star=True, permutations=permutaciones, transform="B")
    np.random.seed(semilla)
    lisa = Moran_Local(y, pesos, permutations=permutaciones)
    descubre = benjamini_hochberg(np.asarray(gi.p_sim, dtype=float))
    z = np.asarray(gi.Zs, dtype=float)
    clase_gi = np.where(
        descubre & (z > 0), "caliente", np.where(descubre & (z < 0), "frio", "ninguno")
    )
    sig = np.asarray(lisa.p_sim, dtype=float) < ALFA_LISA
    cuadrante = np.array(
        [_CUADRANTES[int(q)] if s else "no_significativo" for q, s in zip(lisa.q, sig, strict=True)]
    )
    return pd.DataFrame({"h3": pesos.id_order, "gi_z": z, "gi_clase": clase_gi, "lisa": cuadrante})
