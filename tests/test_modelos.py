from __future__ import annotations

import h3
import numpy as np
import pandas as pd
import pytest

from desiertos.errores import ErrorDatos
from desiertos.modelos import (
    ORIENTE,
    PERIURBANA,
    POPULAR,
    clasificacion,
    densidad_kernel,
    nombrar_perfiles,
    perfiles,
    regresion_espacial,
    reserva_federal,
)


def test_perfiles_separa_dos_grupos() -> None:
    rng = np.random.default_rng(1)
    a = rng.normal(0, 0.1, (20, 2))
    b = rng.normal(5, 0.1, (20, 2))
    tabla = pd.DataFrame(np.vstack([a, b]), columns=["u", "v"])
    salida = perfiles(tabla, ["u", "v"], ks=range(2, 5))
    assert salida["k"] == 2
    assert len(set(salida["etiquetas"][:20])) == 1


def test_perfiles_con_faltantes_falla() -> None:
    with pytest.raises(ErrorDatos):
        perfiles(pd.DataFrame({"u": [1.0, np.nan, 2.0]}), ["u"])


def test_reserva_federal() -> None:
    recta = np.array([1000.0, 4000.0, 10000.0, 20000.0])
    rural = np.array([False, False, True, True])
    assert reserva_federal(recta, rural).tolist() == [False, True, False, True]


def test_densidad_kernel_mayor_cerca_de_la_masa() -> None:
    xy = np.array([[0.0, 0.0], [100.0, 0.0], [20000.0, 0.0]])
    d = densidad_kernel(xy, np.array([100.0, 0.0, 0.0]))
    assert d[0] > d[1] > d[2]


def test_clasificacion_por_bloques() -> None:
    rng = np.random.default_rng(2)
    centro = h3.latlng_to_cell(-33.45, -70.65, 9)
    celdas = list(h3.grid_disk(centro, 25))
    x = rng.normal(size=len(celdas))
    tabla = pd.DataFrame({"h3": celdas, "x": x, "ruido": rng.normal(size=len(celdas))})
    tabla["y"] = (tabla["x"] + rng.normal(0, 0.3, len(celdas)) > 0).astype(int)
    salida = clasificacion(tabla, ["x", "ruido"], "y", resolucion_bloque=7)
    assert salida["logistica"]["auc"] > 0.8


def test_regresion_espacial_recupera_signo() -> None:
    rng = np.random.default_rng(3)
    n = 60
    tabla = pd.DataFrame(
        {
            "x1": rng.normal(size=n),
            "x2": rng.normal(size=n),
            "lon": rng.uniform(0, 1e5, n),
            "lat": rng.uniform(0, 1e5, n),
        }
    )
    tabla["y"] = 2 * tabla["x1"] - tabla["x2"] + rng.normal(0, 0.5, n)
    salida = regresion_espacial(tabla, "y", ["x1", "x2"], "lon", "lat")
    assert salida["mco"]["coeficientes"]["x1"] > 1.5
    assert salida["mco"]["coeficientes"]["x2"] < -0.5
    assert salida["n"] == n


def _centros(filas: dict[int, tuple[float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame.from_dict(
        filas, orient="index", columns=["prop_rural", "ing_tasa", "prop_desierto"]
    )


def test_nombrar_tres_perfiles_por_contenido() -> None:
    # Mismos centros que el resultado de la Región Metropolitana (exploratorio_registro.json).
    centros = _centros(
        {0: (0.010, 0.158, 0.025), 1: (0.000, 0.042, 0.086), 2: (0.378, 0.169, 0.319)}
    )
    assert nombrar_perfiles(centros) == {2: PERIURBANA, 1: ORIENTE, 0: POPULAR}


def test_nombres_no_dependen_del_numero_de_la_etiqueta() -> None:
    centros = _centros(
        {0: (0.378, 0.169, 0.319), 1: (0.010, 0.158, 0.025), 2: (0.000, 0.042, 0.086)}
    )
    assert nombrar_perfiles(centros) == {0: PERIURBANA, 2: ORIENTE, 1: POPULAR}


def test_otro_numero_de_perfiles_usa_nombres_neutros() -> None:
    centros = _centros({0: (0.1, 0.1, 0.30), 1: (0.0, 0.2, 0.05)})
    assert nombrar_perfiles(centros) == {1: "Perfil 1", 0: "Perfil 2"}


def test_nombrar_sin_variables_falla() -> None:
    with pytest.raises(ErrorDatos):
        nombrar_perfiles(pd.DataFrame({"prop_rural": [0.1]}))
