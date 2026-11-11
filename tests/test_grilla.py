from __future__ import annotations

import geopandas as gpd
import h3
import pytest
from shapely.geometry import box

from desiertos import CRS_GEOGRAFICO
from desiertos.errores import ErrorDatos
from desiertos.grilla import celdas_que_tocan, pesos_por_area, poblacion_por_celda, poligono_celda

# Un punto de Santiago centro.
LAT, LON = -33.4489, -70.6693


def _unidades(filas: list[dict[str, object]]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(filas, geometry="geometry", crs=CRS_GEOGRAFICO)


def test_celdas_que_tocan_incluye_poligono_menor_que_celda() -> None:
    chico = box(LON - 0.0002, LAT - 0.0002, LON + 0.0002, LAT + 0.0002)
    celdas = celdas_que_tocan(chico, 9)
    assert h3.latlng_to_cell(LAT, LON, 9) in celdas


def test_pesos_suman_uno_por_unidad() -> None:
    grande = box(LON - 0.01, LAT - 0.01, LON + 0.01, LAT + 0.01)
    chico = box(LON, LAT, LON + 0.0003, LAT + 0.0003)
    unidades = _unidades([{"manzent": 1, "geometry": grande}, {"manzent": 2, "geometry": chico}])
    pesos = pesos_por_area(unidades, 9)
    sumas = pesos.groupby("manzent")["peso"].sum()
    assert sumas.to_numpy() == pytest.approx([1.0, 1.0])
    assert pesos.loc[pesos["manzent"] == 1, "h3"].nunique() > 5


def test_poblacion_se_conserva_y_ruralidad() -> None:
    celda = h3.latlng_to_cell(LAT, LON, 9)
    hexagono = poligono_celda(celda)
    urbana = hexagono.buffer(-0.0005)
    unidades = _unidades(
        [
            {
                "manzent": 1,
                "cut": 13101,
                "area": "URBANO",
                "n_per": 300.0,
                "n_60_mas": 60.0,
                "geometry": urbana,
            },
            {
                "manzent": 2,
                "cut": 13101,
                "area": "RURAL",
                "n_per": 100.0,
                "n_60_mas": None,
                "geometry": hexagono.buffer(-0.0008),
            },
        ]
    )
    tabla = poblacion_por_celda(unidades, 9)
    assert len(tabla) == 1
    fila = tabla.iloc[0]
    assert fila["h3"] == celda
    assert fila["n_per"] == pytest.approx(400.0)
    assert fila["n_per_rural"] == pytest.approx(100.0)
    assert fila["n_60_mas"] == pytest.approx(60.0)
    assert fila["n_per_con_60"] == pytest.approx(300.0)
    assert not bool(fila["rural"])
    assert int(fila["cut"]) == 13101


def test_comuna_mayoritaria_y_umbral_rural() -> None:
    celda = h3.latlng_to_cell(LAT, LON, 9)
    hexagono = poligono_celda(celda)
    unidades = _unidades(
        [
            {
                "manzent": 1,
                "cut": 13102,
                "area": "RURAL",
                "n_per": 51.0,
                "n_60_mas": 5.0,
                "geometry": hexagono.buffer(-0.0006),
            },
            {
                "manzent": 2,
                "cut": 13101,
                "area": "URBANO",
                "n_per": 49.0,
                "n_60_mas": 5.0,
                "geometry": hexagono.buffer(-0.0007),
            },
        ]
    )
    fila = poblacion_por_celda(unidades, 9).iloc[0]
    assert int(fila["cut"]) == 13102
    assert bool(fila["rural"])


def test_celdas_bajo_minimo_se_excluyen() -> None:
    celda = h3.latlng_to_cell(LAT, LON, 9)
    unidades = _unidades(
        [
            {
                "manzent": 1,
                "cut": 13101,
                "area": "URBANO",
                "n_per": 0.4,
                "n_60_mas": 0.0,
                "geometry": poligono_celda(celda).buffer(-0.0005),
            }
        ]
    )
    assert poblacion_por_celda(unidades, 9).empty


def test_sin_crs_falla() -> None:
    unidades = gpd.GeoDataFrame({"manzent": [1]}, geometry=[box(0, 0, 1, 1)])
    with pytest.raises(ErrorDatos):
        pesos_por_area(unidades, 9)


def test_pesos_dasimetricos_concentran_en_edificios() -> None:
    import geopandas as gpd
    from shapely.geometry import Point, box

    from desiertos.grilla import pesos_dasimetricos

    rural = box(-70.70, -33.50, -70.66, -33.47)
    urbana = box(-70.65, -33.45, -70.64, -33.44)
    unidades = gpd.GeoDataFrame(
        {"manzent": ["R1", "U1"], "area": ["RURAL", "URBANO"]},
        geometry=[rural, urbana],
        crs="EPSG:4326",
    )
    edificios = gpd.GeoDataFrame(
        {"area_m2": [300.0, 100.0, 50.0]},
        geometry=[Point(-70.69, -33.49), Point(-70.67, -33.48), Point(-70.645, -33.445)],
        crs="EPSG:4326",
    )
    pesos = pesos_dasimetricos(unidades, edificios, 9)
    r1 = pesos[pesos["manzent"] == "R1"]
    assert len(r1) == 2
    assert sorted(r1["peso"].round(2)) == [0.25, 0.75]
    u1 = pesos[pesos["manzent"] == "U1"]
    assert len(u1) > 1
    assert abs(u1["peso"].sum() - 1) < 1e-9
