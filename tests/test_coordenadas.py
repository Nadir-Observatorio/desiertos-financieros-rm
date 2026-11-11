from __future__ import annotations

import math

import geopandas as gpd
import pandas as pd
import pytest

from desiertos.errores import ErrorDatos
from desiertos.ingesta.coordenadas import Lectura, evaluar, leer_coordenada, normalizar_comuna


@pytest.mark.parametrize(
    ("texto", "valor", "lectura"),
    [
        ("-33,4489", -33.4489, Lectura.ORIGINAL),
        ("-70.6693", -70.6693, Lectura.ORIGINAL),
        ("-334441", -33.4441, Lectura.REPARADA),
        ("-70653335", -70.653335, Lectura.REPARADA),
        ("-3337754", -33.37754, Lectura.REPARADA),
        ("-3.367.901", -33.67901, Lectura.REPARADA),
        ("-33.612.053", -33.612053, Lectura.REPARADA),
        ("-705.587", -70.5587, Lectura.REPARADA),
        ("-33445", -33.445, Lectura.REPARADA),
        ("0", 0.0, Lectura.ORIGINAL),
        ("-3352", -3352.0, Lectura.ORIGINAL),
    ],
)
def test_leer_coordenada(texto: str, valor: float, lectura: Lectura) -> None:
    obtenido, clase = leer_coordenada(texto)
    assert obtenido == pytest.approx(valor)
    assert clase is lectura


@pytest.mark.parametrize(
    ("texto", "lectura"),
    [("-3,67E+11", Lectura.CIENTIFICA), ("abc", Lectura.ILEGIBLE), (None, Lectura.ILEGIBLE)],
)
def test_coordenada_no_utilizable(texto: object, lectura: Lectura) -> None:
    obtenido, clase = leer_coordenada(texto)
    assert math.isnan(obtenido)
    assert clase is lectura


def test_normalizar_comuna() -> None:
    assert normalizar_comuna("Til Til") == normalizar_comuna("TILTIL")
    assert normalizar_comuna("Estación Central.") == "ESTACIONCENTRAL"
    assert normalizar_comuna("PUENTEALTO") == normalizar_comuna("Puente Alto")


def test_evaluar_reglas(unidades_rm: gpd.GeoDataFrame) -> None:
    tabla = pd.DataFrame(
        {
            "latitud": ["-33,445", "-33445", "-33,445", "-3,67E+11", "-33,52", "-33,445"],
            "longitud": ["-70,655", "-70655", "-70,655", "-7,06E+11", "-70,77", "-70,655"],
            "comuna": ["SANTIAGO", "SANTIAGO", "MAIPU", "SANTIAGO", "Maipú", "CALAMA"],
        }
    )
    salida = evaluar(tabla, unidades_rm)
    assert list(salida["estado"]) == [
        "aceptada",
        "aceptada",
        "a_geocodificar",
        "a_geocodificar",
        "aceptada",
        "a_geocodificar",
    ]
    assert list(salida["motivo"]) == [
        "",
        "",
        "lejos_de_su_comuna",
        "coordenada_inutilizable",
        "",
        "comuna_no_reconocida",
    ]
    assert salida.loc[1, "lectura_lat"] == "reparada"
    assert salida.loc[0, "distancia_m"] == pytest.approx(0.0)


def test_evaluar_fuera_de_region(unidades_rm: gpd.GeoDataFrame) -> None:
    tabla = pd.DataFrame({"latitud": ["-36,8"], "longitud": ["-73,05"], "comuna": ["SANTIAGO"]})
    assert evaluar(tabla, unidades_rm).loc[0, "motivo"] == "fuera_de_la_region"


def test_evaluar_columnas_faltantes(unidades_rm: gpd.GeoDataFrame) -> None:
    with pytest.raises(ErrorDatos):
        evaluar(pd.DataFrame({"latitud": ["1"]}), unidades_rm)
