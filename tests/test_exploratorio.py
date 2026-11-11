from __future__ import annotations

import h3
import numpy as np
import pandas as pd

from desiertos.exploratorio import agrupamientos, benjamini_hochberg


def test_benjamini_hochberg() -> None:
    p = np.array([0.001, 0.02, 0.03, 0.5])
    assert benjamini_hochberg(p, 0.05).tolist() == [True, True, True, False]
    assert benjamini_hochberg(np.array([0.2, 0.3]), 0.05).tolist() == [False, False]


def test_agrupamientos_detectan_foco() -> None:
    centro = h3.latlng_to_cell(-33.45, -70.65, 9)
    filas = []
    for k in range(0, 10):
        for c in h3.grid_ring(centro, k) if k else [centro]:
            filas.append({"h3": c, "minutos": 60.0 if k <= 2 else 2.0})
    tabla = pd.DataFrame(filas)
    salida = agrupamientos(tabla, permutaciones=99).set_index("h3")
    assert salida.loc[centro, "gi_clase"] == "caliente"
    assert salida.loc[centro, "lisa"] == "alto_alto"
    lejana = h3.grid_ring(centro, 8)[0]
    assert salida.loc[lejana, "gi_clase"] in {"frio", "ninguno"}
