"""Tabla comunal (exploratorio y indicador secundario de E-4).

Une, por comuna del Censo: población y desiertos agregados desde las celdas, puntos de acceso,
cifras de la CMF por 10.000 habitantes y pobreza SAE del MDSF. Las cifras comunales (CMF, SAE) no
se atribuyen a celdas (protocolo, sección 9).
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from desiertos.completitud import asignar_comuna
from desiertos.errores import ErrorDatos
from desiertos.ingesta.coordenadas import normalizar_comuna
from desiertos.procedencia import verificar


def leer_sae(ruta: Path, prefijo: str) -> pd.DataFrame:
    """Planilla SAE 2024: cut, <prefijo>_tasa, <prefijo>_li, <prefijo>_ls, <prefijo>_tipo."""
    verificar(ruta)
    bruto = pd.read_excel(ruta, header=None)
    fila_titulos = bruto.index[bruto[0].astype(str).str.strip().eq("Código")]
    if len(fila_titulos) != 1:
        raise ErrorDatos(f"{ruta.name}: no se encontró la fila de títulos")
    datos = bruto.iloc[int(fila_titulos[0]) + 1 :]
    datos = datos[pd.to_numeric(datos[0], errors="coerce").notna()]
    tabla = pd.DataFrame(
        {
            "cut": pd.to_numeric(datos[0]).astype(int).to_numpy(),
            f"{prefijo}_tasa": pd.to_numeric(datos[5]).to_numpy(dtype=float),
            f"{prefijo}_li": pd.to_numeric(datos[6]).to_numpy(dtype=float),
            f"{prefijo}_ls": pd.to_numeric(datos[7]).to_numpy(dtype=float),
            f"{prefijo}_tipo": datos[9].astype(str).str.strip().to_numpy(),
        }
    )
    if tabla["cut"].duplicated().any():
        raise ErrorDatos(f"{ruta.name}: códigos comunales repetidos")
    return tabla


def tabla_comunal(
    celdas: pd.DataFrame,
    nombres: pd.DataFrame,
    huellas: gpd.GeoDataFrame,
    puntos: gpd.GeoDataFrame,
    cmf: pd.DataFrame,
    sae: list[pd.DataFrame],
    umbral: float,
) -> pd.DataFrame:
    """Una fila por comuna con indicadores de acceso, banca tradicional y pobreza.

    celdas: h3, cut, n_per, n_per_rural, n_60_mas, n_per_con_60, minutos.
    nombres: cut y comuna (nombre del Censo). huellas: clave y geometría por comuna.
    puntos: tipo y geometría. cmf: comuna normalizada, cmf_sucursales, cmf_cajeros.
    """
    faltan = {"cut", "n_per", "n_per_rural", "n_60_mas", "n_per_con_60", "minutos"} - set(
        celdas.columns
    )
    if faltan:
        raise ErrorDatos(f"Faltan columnas en celdas: {sorted(faltan)}")
    c = celdas.assign(
        des=lambda t: np.where(t["minutos"] > umbral, t["n_per"], 0.0),
        min_pond=lambda t: t["minutos"] * t["n_per"],
    )
    base = c.groupby("cut").agg(
        poblacion=("n_per", "sum"),
        poblacion_rural=("n_per_rural", "sum"),
        poblacion_60=("n_60_mas", "sum"),
        poblacion_con_60=("n_per_con_60", "sum"),
        poblacion_desierto=("des", "sum"),
        minutos_suma=("min_pond", "sum"),
    )
    base["prop_desierto"] = base["poblacion_desierto"] / base["poblacion"]
    base["minutos_medios"] = base["minutos_suma"] / base["poblacion"]
    base["prop_rural"] = base["poblacion_rural"] / base["poblacion"]
    base["prop_60"] = base["poblacion_60"] / base["poblacion_con_60"]
    base = base.drop(columns=["minutos_suma"]).reset_index()
    claves = nombres.drop_duplicates("cut").assign(
        clave=lambda t: t["comuna"].map(normalizar_comuna)
    )[["cut", "clave"]]
    base = base.merge(claves, on="cut", how="left", validate="1:1")
    area = huellas.assign(area_km2=huellas.geometry.area / 1e6)[["clave", "area_km2"]]
    base = base.merge(area, on="clave", how="left")
    base["densidad_hab_km2"] = base["poblacion"] / base["area_km2"]
    asignados = asignar_comuna(puntos, huellas)
    conteo = (
        asignados.assign(caja_vecina=(asignados["tipo"] == "caja_vecina").astype(int), todos=1)
        .groupby("clave")[["todos", "caja_vecina"]]
        .sum()
    )
    base = base.merge(conteo, left_on="clave", right_index=True, how="left")
    base[["todos", "caja_vecina"]] = base[["todos", "caja_vecina"]].fillna(0)
    base["puntos_10k"] = base["todos"] / base["poblacion"] * 1e4
    base["caja_vecina_10k"] = base["caja_vecina"] / base["poblacion"] * 1e4
    base = base.merge(cmf, left_on="clave", right_on="comuna", how="left").drop(columns="comuna")
    base["sucursales_10k"] = base["cmf_sucursales"].fillna(0) / base["poblacion"] * 1e4
    base["cajeros_10k"] = base["cmf_cajeros"].fillna(0) / base["poblacion"] * 1e4
    for tabla in sae:
        base = base.merge(tabla, on="cut", how="left", validate="1:1")
    return base.sort_values("cut").reset_index(drop=True)
