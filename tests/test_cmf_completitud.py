from __future__ import annotations

import io
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point, box

from desiertos.completitud import conteo_osm_por_comuna, evaluar_completitud
from desiertos.errores import ErrorDatos
from desiertos.ingesta.cmf import (
    cajeros_por_comuna,
    hoja_de_region,
    leer_conteos_rm,
    sucursales_por_comuna,
)


def _hoja_sucursales() -> pd.DataFrame:
    h = pd.DataFrame(np.full((8, 9), np.nan, dtype=object))
    h.iat[2, 4] = "Región Metropolitana"
    h.iat[4, 5] = "Comuna / Institución"
    h.iat[6, 5], h.iat[6, 7] = "Alhué", 1
    h.iat[7, 6], h.iat[7, 7] = "Banco del Estado de Chile", 1
    return pd.concat(
        [h, pd.DataFrame([[np.nan] * 5 + ["Ñuñoa", np.nan, 19, 300]])], ignore_index=True
    )


def _hoja_cajeros() -> pd.DataFrame:
    h = pd.DataFrame(np.full((10, 10), np.nan, dtype=object))
    h.iat[3, 2] = "Región Metropolitana"
    h.iat[5, 4] = "Periodo"
    h.iat[5, 6], h.iat[5, 8] = "Alhué", "Ñuñoa"
    h.iat[6, 6], h.iat[6, 8], h.iat[6, 9] = "Banco de Chile", "BCI", "Santander"
    h.iat[7, 4], h.iat[7, 5] = 2026, "Jul"
    h.iat[8, 5] = "Ago"
    h.iat[7, 6], h.iat[7, 8], h.iat[7, 9] = 9, 9, 9
    h.iat[8, 6], h.iat[8, 8], h.iat[8, 9] = 3, "-", 5
    return h


def test_sucursales_por_comuna_normaliza_y_suma_totales() -> None:
    serie = sucursales_por_comuna(_hoja_sucursales())
    assert serie.to_dict() == {"ALHUE": 1, "NUNOA": 19}


def test_cajeros_por_comuna_lee_el_mes_y_trata_guion_como_cero() -> None:
    serie = cajeros_por_comuna(_hoja_cajeros(), 2026, "Ago")
    assert serie.to_dict() == {"ALHUE": 3, "NUNOA": 5}


def test_cajeros_periodo_ausente_falla() -> None:
    with pytest.raises(ErrorDatos):
        cajeros_por_comuna(_hoja_cajeros(), 2026, "Sep")


def test_hoja_de_region_sin_titulo_falla() -> None:
    with pytest.raises(ErrorDatos):
        hoja_de_region({"Hoja1": pd.DataFrame([["Arica"]])})


def test_leer_conteos_rm_desde_zip(tmp_path: Path) -> None:
    destino = tmp_path / "cmf.zip"
    with zipfile.ZipFile(destino, "w") as zf:
        for nombre, hoja in (
            ("20260801_CMF_SucursalesPersonasComunaBancoNumero.xlsx", _hoja_sucursales()),
            ("CMF_CajerosNroCajerosComunaRegInst.xlsx", _hoja_cajeros()),
        ):
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer) as w:
                pd.DataFrame([["Arica"]]).to_excel(w, sheet_name="Hoja1", header=False, index=False)
                hoja.to_excel(w, sheet_name="Hoja7", header=False, index=False)
            zf.writestr(nombre, buffer.getvalue())
    tabla = leer_conteos_rm(destino, 2026, "Ago")
    assert tabla.set_index("comuna").to_dict("index") == {
        "ALHUE": {"cmf_sucursales": 1, "cmf_cajeros": 3},
        "NUNOA": {"cmf_sucursales": 19, "cmf_cajeros": 5},
    }


def test_conteo_y_evaluacion_de_completitud() -> None:
    huellas = gpd.GeoDataFrame(
        {"clave": ["A", "B"]}, geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)], crs="EPSG:32719"
    )
    osm = gpd.GeoDataFrame(
        {"amenidad": ["bank", "atm", "atm", "bank"]},
        geometry=[Point(0.5, 0.5), Point(0.2, 0.2), Point(0.3, 0.3), Point(5000, 5000)],
        crs="EPSG:32719",
    )
    conteo = conteo_osm_por_comuna(osm, huellas)
    cmf = pd.DataFrame(
        {"comuna": ["A", "B", "C"], "cmf_sucursales": [1, 2, 0], "cmf_cajeros": [2, 4, 1]}
    )
    tabla = evaluar_completitud(cmf, conteo).set_index("comuna")
    assert tabla.loc["A", "apta"]
    assert not tabla.loc["B", "apta"]
    assert tabla.loc["B", "osm_bank"] == 0
    assert tabla["razon_sucursales"].isna()["C"]
    assert not tabla.loc["C", "apta"]
