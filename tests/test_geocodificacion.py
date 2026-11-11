from __future__ import annotations

import math

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, box

from desiertos import CRS_GEOGRAFICO, CRS_METRICO_RM
from desiertos.errores import ErrorDatos
from desiertos.geocodificacion import (
    Geocodificador,
    Metodo,
    geocodificar_tabla,
    leer_numero,
    medir_calidad,
    normalizar_calle,
)


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Avenida José Joaquín Pérez", "JOSE JOAQUIN PEREZ"),
        ("PINTOR ROBERTO MATTA 7188 VILLA BARRIO ALTO", "PINTOR ROBERTO MATTA"),
        ("CALLE ROMA NRO", "ROMA"),
        ("PASAJE QUILLAY SITIO N1", "QUILLAY"),
        ("Gral. Bulnes", "GENERAL BULNES"),
        ("AVENIDA 1 DE MAYO", "1 DE MAYO"),
    ],
)
def test_normalizar_calle(texto: str, esperado: str) -> None:
    assert normalizar_calle(texto) == esperado


def test_leer_numero() -> None:
    assert leer_numero("1234-B") == 1234
    assert leer_numero("s/n") is None
    assert leer_numero(None) is None


def _geocodificador() -> Geocodificador:
    # Una calle recta este-oeste en Santiago centro, con dos números conocidos.
    y = -33.445
    calle = LineString([(-70.660, y), (-70.650, y)])
    direcciones = gpd.GeoDataFrame(
        {"calle": ["Calle Prueba", "Calle Prueba"], "numero": ["100", "300"]},
        geometry=[Point(-70.660, y), Point(-70.650, y)],
        crs=CRS_GEOGRAFICO,
    )
    calles = gpd.GeoDataFrame(
        {"calle": ["Calle Prueba", "Otra"]},
        geometry=[calle, LineString([(-70.66, -33.44), (-70.65, -33.44)])],
        crs=CRS_GEOGRAFICO,
    )
    huellas = gpd.GeoDataFrame(
        {"clave": ["SANTIAGO"]},
        geometry=[box(-70.67, -33.46, -70.64, -33.43)],
        crs=CRS_GEOGRAFICO,
    ).to_crs(CRS_METRICO_RM)
    return Geocodificador(direcciones, calles, huellas)


def test_metodos() -> None:
    geo = _geocodificador()
    exacta = geo.geocodificar("PRUEBA", "100", "Santiago")
    assert exacta.metodo is Metodo.EXACTA
    assert exacta.lon == pytest.approx(-70.660, abs=1e-6)
    medio = geo.geocodificar("Calle Prueba", "200", "SANTIAGO")
    assert medio.metodo is Metodo.INTERPOLADA
    assert medio.lon == pytest.approx(-70.655, abs=1e-6)
    cercano = geo.geocodificar("PRUEBA", "350", "SANTIAGO")
    assert cercano.metodo is Metodo.NUMERO_CERCANO
    lejano = geo.geocodificar("PRUEBA", "900", "SANTIAGO")
    assert lejano.metodo is Metodo.CALLE
    solo_calle = geo.geocodificar("OTRA", "5", "SANTIAGO")
    assert solo_calle.metodo is Metodo.CALLE
    nada = geo.geocodificar("INEXISTENTE", "5", "SANTIAGO")
    assert nada.metodo is Metodo.SIN_RESULTADO
    assert math.isnan(nada.lon)


def test_similitud_tolera_errata() -> None:
    assert _geocodificador().geocodificar("PRUEBAA", "100", "SANTIAGO").metodo is Metodo.EXACTA


def test_tabla_y_calidad() -> None:
    geo = _geocodificador()
    tabla = pd.DataFrame(
        {"direccion": ["PRUEBA", "INEXISTENTE"], "numero": ["100", "1"], "comuna": ["SANTIAGO"] * 2}
    )
    estimados = geocodificar_tabla(geo, tabla)
    verdaderos = gpd.GeoSeries([Point(-70.660, -33.445), Point(-70.66, -33.44)], crs=CRS_GEOGRAFICO)
    filas, resumen = medir_calidad(estimados, verdaderos)
    assert list(filas["metodo"]) == ["exacta", "sin_resultado"]
    assert resumen["tasa_con_resultado"] == pytest.approx(0.5)
    assert resumen["tasa_acierto_100m"] == pytest.approx(0.5)
    assert resumen["error_mediana_m"] == pytest.approx(0.0, abs=0.01)


def test_errores_de_entrada() -> None:
    geo = _geocodificador()
    with pytest.raises(ErrorDatos):
        geocodificar_tabla(geo, pd.DataFrame({"direccion": ["X"]}))
    vacio = gpd.GeoDataFrame({"metodo": []}, geometry=[], crs=CRS_GEOGRAFICO)
    with pytest.raises(ErrorDatos):
        medir_calidad(vacio, gpd.GeoSeries([Point(0, 0)], crs=CRS_GEOGRAFICO))
