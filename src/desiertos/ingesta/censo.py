"""Base manzana-entidad del Censo 2024 (INE) desde la cartografía geoparquet regional.

Une manzanas (urbanas y de aldea) y entidades rurales en una sola tabla de unidades con
población total y de 60 años y más (enmienda E-2).
"""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd

from desiertos import CRS_GEOGRAFICO
from desiertos.errores import ErrorDatos

COLUMNAS = ["MANZENT", "CUT", "COMUNA", "AREA_C", "n_per", "n_edad_60_mas"]
SUFIJOS = ("_Manzanas.parquet", "_Entidades.parquet")
AREAS_VALIDAS = frozenset({"URBANO", "RURAL"})


def _miembro(nombres: list[str], sufijo: str) -> str:
    candidatos = [n for n in nombres if n.endswith(sufijo)]
    if len(candidatos) != 1:
        raise ErrorDatos(f"Se esperaba un archivo *{sufijo} en el zip y hay {len(candidatos)}")
    return candidatos[0]


def _leer_capa(ruta: Path) -> gpd.GeoDataFrame:
    try:
        capa = gpd.read_parquet(ruta)
    except (OSError, ValueError) as exc:
        raise ErrorDatos(f"No se pudo leer {ruta.name}: {exc}") from exc
    faltan = set(COLUMNAS) - set(capa.columns)
    if faltan:
        raise ErrorDatos(f"{ruta.name}: faltan columnas {sorted(faltan)}")
    capa = capa[[*COLUMNAS, capa.geometry.name]].rename_geometry("geometry")
    if capa.crs is None:
        raise ErrorDatos(f"{ruta.name}: sin sistema de referencia")
    return capa


def leer_unidades(ruta_zip: Path) -> gpd.GeoDataFrame:
    """Manzanas y entidades del zip regional, en EPSG:4326, con nombres normalizados.

    Columnas: manzent, cut, comuna, area (URBANO o RURAL), n_per, n_60_mas (NaN cuando el INE
    no publica el dato), geometry.
    """
    try:
        archivo = zipfile.ZipFile(ruta_zip)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ErrorDatos(f"No se pudo abrir {ruta_zip}: {exc}") from exc
    with archivo, tempfile.TemporaryDirectory() as tmp:
        nombres = archivo.namelist()
        capas = []
        for sufijo in SUFIJOS:
            miembro = _miembro(nombres, sufijo)
            destino = Path(archivo.extract(miembro, tmp))
            capas.append(_leer_capa(destino))
    crs = capas[0].crs
    unidades = gpd.GeoDataFrame(
        pd.concat([c.to_crs(crs) for c in capas], ignore_index=True), crs=crs
    ).to_crs(CRS_GEOGRAFICO)
    unidades = unidades.rename(
        columns={
            "MANZENT": "manzent",
            "CUT": "cut",
            "COMUNA": "comuna",
            "AREA_C": "area",
            "n_edad_60_mas": "n_60_mas",
        }
    )
    unidades["area"] = unidades["area"].astype("string").str.strip().str.upper()
    raras = set(unidades["area"].dropna().unique()) - AREAS_VALIDAS
    if raras or unidades["area"].isna().any():
        raise ErrorDatos(f"Valores de AREA_C no previstos: {sorted(raras)}")
    if unidades["manzent"].duplicated().any():
        raise ErrorDatos("MANZENT repetido entre manzanas y entidades")
    if unidades["n_per"].isna().any() or (unidades["n_per"] < 0).any():
        raise ErrorDatos("n_per con nulos o negativos")
    unidades["cut"] = unidades["cut"].astype("int64")
    unidades["n_per"] = unidades["n_per"].astype("float64")
    unidades["n_60_mas"] = unidades["n_60_mas"].astype("float64")
    unidades["geometry"] = unidades.geometry.make_valid()
    return unidades
