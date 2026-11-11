from __future__ import annotations

import h3
import numpy as np
import pandas as pd
import pytest

from desiertos.errores import ErrorDatos
from desiertos.hipotesis import (
    bootstrap_por_bloques,
    holm,
    moran_log_tiempo,
    residuos,
    vecindad_anillo,
)


def _tabla() -> pd.DataFrame:
    """Disco de celdas: el centro es urbano y cercano; el borde, rural y lejano."""
    centro = h3.latlng_to_cell(-33.45, -70.65, 9)
    filas = []
    for k in range(0, 12):
        for c in h3.grid_ring(centro, k) if k else [centro]:
            rural = k >= 8
            filas.append(
                {
                    "h3": c,
                    "n_per": 50.0 if not rural else 5.0,
                    "rural": rural,
                    "n_60_mas": 5.0 if not rural else 2.0,
                    "n_per_con_60": 50.0 if not rural else 5.0,
                    "minutos": float(2 * k),
                }
            )
    return pd.DataFrame(filas)


def test_bootstrap_h1_h2_signos_y_reproducible() -> None:
    tabla = _tabla()
    h1, h2 = bootstrap_por_bloques(tabla, 15, 7, replicas=200)
    assert h1.efecto == pytest.approx(100.0)
    assert h1.p == 0.0
    assert h2.efecto == pytest.approx((2 / 5) / (tabla["n_60_mas"].sum() / tabla["n_per"].sum()))
    assert h2.efecto > 1
    otra, _ = bootstrap_por_bloques(tabla, 15, 7, replicas=200)
    assert otra == h1


def test_bootstrap_sin_rural_falla() -> None:
    tabla = _tabla().assign(rural=False)
    with pytest.raises(ErrorDatos):
        bootstrap_por_bloques(tabla, 15, 7, replicas=10)


def test_moran_positivo_con_gradiente() -> None:
    resultado = moran_log_tiempo(_tabla(), permutaciones=99)
    assert resultado.efecto > 0.5
    assert resultado.p == pytest.approx(1 / 100)


def test_vecindad_excluye_aisladas() -> None:
    a = h3.latlng_to_cell(-33.45, -70.65, 9)
    b = h3.grid_ring(a, 1)[0]
    lejos = h3.latlng_to_cell(-33.9, -71.2, 9)
    pesos = vecindad_anillo(pd.Series([a, b, lejos]))
    assert set(pesos.id_order) == {a, b}


def test_residuos_centrados() -> None:
    tabla = _tabla()
    r1, r2 = residuos(tabla, 15)
    pob = tabla["n_per"].to_numpy()
    rural = tabla["rural"].to_numpy()
    assert np.sum(r1[rural] * pob[rural]) == pytest.approx(0.0, abs=1e-9)
    assert len(r2) == len(tabla)


def test_holm() -> None:
    salida = holm({"H1": 0.01, "H2": 0.04, "H3": 0.03})
    assert salida["H1"] == (0.03, True)
    assert salida["H3"][0] == pytest.approx(0.06)
    assert salida["H2"][0] == pytest.approx(0.06)
    assert not salida["H2"][1]
