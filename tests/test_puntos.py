from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import Point

from desiertos import CRS_GEOGRAFICO
from desiertos.errores import ErrorDatos
from desiertos.puntos import METODOS_SENSIBILIDAD, unir_puntos


def _capas() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]:
    red = gpd.GeoDataFrame(
        {
            "id_punto": ["caja_vecina:1", "caja_vecina:2"],
            "tipo": ["caja_vecina", "caja_vecina"],
            "lectura_lat": ["original", "reparada"],
            "lectura_lon": ["original", "original"],
        },
        geometry=[Point(-70.66, -33.44), Point(-70.65, -33.44)],
        crs=CRS_GEOGRAFICO,
    )
    cola = gpd.GeoDataFrame(
        {
            "id_punto": ["caja_vecina:3", "caja_vecina:4", "caja_vecina:5"],
            "tipo": ["caja_vecina"] * 3,
            "metodo": ["interpolada", "numero_cercano", "calle"],
        },
        geometry=[Point(-70.64, -33.44), Point(-70.63, -33.44), Point(-70.62, -33.44)],
        crs=CRS_GEOGRAFICO,
    )
    osm = gpd.GeoDataFrame(
        {"id_osm": ["n9"], "amenidad": ["atm"]}, geometry=[Point(-70.6, -33.4)], crs=CRS_GEOGRAFICO
    )
    return red, cola, osm


def test_unir_metodos_aceptados() -> None:
    puntos = unir_puntos(*_capas())
    assert list(puntos["id_punto"]) == ["caja_vecina:1", "caja_vecina:2", "caja_vecina:3", "osm:n9"]
    assert list(puntos["origen_coordenada"]) == [
        "original",
        "reparada",
        "geocodificada_interpolada",
        "original",
    ]
    assert list(puntos["tipo"])[-1] == "osm_atm"


def test_unir_sensibilidad() -> None:
    puntos = unir_puntos(*_capas(), metodos=METODOS_SENSIBILIDAD)
    assert "caja_vecina:4" in set(puntos["id_punto"])
    assert "caja_vecina:5" not in set(puntos["id_punto"])


def test_unir_falla_sin_columnas() -> None:
    red, cola, osm = _capas()
    with pytest.raises(ErrorDatos):
        unir_puntos(red.drop(columns="lectura_lat"), cola, osm)
