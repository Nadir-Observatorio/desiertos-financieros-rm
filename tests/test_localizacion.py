from __future__ import annotations

import pandas as pd
import pytest

from desiertos.errores import ErrorDatos
from desiertos.localizacion import mclp, mclp_voraz, p_mediana


def _caso() -> tuple[pd.Series, pd.DataFrame]:
    # Tres demandas grandes cubiertas por B y C juntas; A cubre solo la mayor. El voraz elige A
    # primero y con k=2 queda peor que el óptimo (B + C).
    pesos = pd.Series({"d1": 10.0, "d2": 6.0, "d3": 6.0})
    pares = pd.DataFrame(
        {
            "h3_origen": ["d1", "d1", "d2", "d1", "d3", "d2", "d3"],
            "h3_candidato": ["A", "B", "B", "C", "C", "A", "A"],
            "minutos": [5, 10, 10, 10, 10, 30, 30],
        }
    )
    return pesos, pares


def test_mclp_exacto_le_gana_al_voraz() -> None:
    pesos, pares = _caso()
    pares = pd.concat(
        [pares, pd.DataFrame({"h3_origen": ["d2"], "h3_candidato": ["A"], "minutos": [12]})]
    )
    exacto = mclp(pesos, pares, 1, 15)
    assert exacto.cubierta == pytest.approx(16.0)
    assert exacto.elegidos == ["A"] or exacto.elegidos == ["B"]
    dos = mclp(pesos, pares, 2, 15)
    assert dos.cubierta == pytest.approx(22.0)
    assert dos.brecha == pytest.approx(0.0, abs=1e-6)
    voraz = mclp_voraz(pesos, pares, 2, 15)
    assert voraz.cubierta <= dos.cubierta


def test_mclp_sin_cobertura_falla() -> None:
    pesos, pares = _caso()
    with pytest.raises(ErrorDatos):
        mclp(pesos, pares, 1, 1)
    with pytest.raises(ErrorDatos):
        mclp(pesos, pares, 0, 15)


def test_p_mediana_reduce_y_respeta_existentes() -> None:
    pesos, pares = _caso()
    actual = pd.Series({"d1": 40.0, "d2": 40.0, "d3": 8.0})
    elegidos, valor = p_mediana(pesos, actual, pares, 1)
    assert elegidos == ["B"]
    assert valor == pytest.approx(10 * 10 + 6 * 10 + 6 * 8)
    elegidos2, valor2 = p_mediana(pesos, actual, pares, 2)
    assert valor2 <= valor
    assert len(elegidos2) == 2
