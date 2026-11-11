"""Calidad de coordenadas de la red de BancoEstado (enmienda E-3).

Regla fija, decidida antes de cruzar puntos con población:

1. Un valor con a lo sumo un separador (coma o punto) cuyo valor absoluto está entre 17 y 110
   (latitudes y longitudes de Chile) es `original`.
2. Si no, un valor formado por dígitos y separadores, con al menos 5 dígitos, perdió su separador
   decimal o recibió separadores de miles al exportarse: se quitan todos los separadores y la coma
   decimal se reinserta después de los dos primeros dígitos (`reparada`).
3. La notación científica perdió precisión y no se repara.
4. Todo punto, original o reparado, se acepta solo si cae dentro de la caja de la región y a 1 km o
   menos de una manzana o entidad censal de la comuna que declara la fila. Lo que no cumple pasa a
   la cola de geocodificación por dirección.
"""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum

import geopandas as gpd
import numpy as np
import pandas as pd

from desiertos import CRS_GEOGRAFICO, CRS_METRICO_RM
from desiertos.errores import ErrorDatos

DISTANCIA_MAXIMA_M = 1000.0
DIGITOS_MINIMOS = 5
RANGO_CHILE = (17.0, 110.0)  # valor absoluto plausible de una latitud o longitud de Chile
# Caja de la Región Metropolitana con margen (grados).
CAJA_RM = (-71.8, -34.4, -69.7, -32.8)  # lon_min, lat_min, lon_max, lat_max

_CIENTIFICA = re.compile(r"^-?\d+([.,]\d+)?[eE][+-]?\d+$")
_DECIMAL = re.compile(r"^-?\d+([.,]\d+)?$")
_DIGITOS_Y_SEPARADORES = re.compile(r"^-?\d[\d.,]*$")


class Lectura(StrEnum):
    ORIGINAL = "original"
    REPARADA = "reparada"
    CIENTIFICA = "cientifica"
    ILEGIBLE = "ilegible"


class Estado(StrEnum):
    ACEPTADA = "aceptada"
    A_GEOCODIFICAR = "a_geocodificar"


def leer_coordenada(texto: object) -> tuple[float, Lectura]:
    """Lee un valor de latitud o longitud según la regla de E-3. NaN si no es utilizable."""
    if texto is None or (isinstance(texto, float) and np.isnan(texto)):
        return float("nan"), Lectura.ILEGIBLE
    s = str(texto).strip()
    if _CIENTIFICA.match(s):
        return float("nan"), Lectura.CIENTIFICA
    if _DECIMAL.match(s):
        valor = float(s.replace(",", "."))
        if RANGO_CHILE[0] <= abs(valor) <= RANGO_CHILE[1]:
            return valor, Lectura.ORIGINAL
    if _DIGITOS_Y_SEPARADORES.match(s):
        signo = -1.0 if s.startswith("-") else 1.0
        digitos = re.sub(r"[^0-9]", "", s)
        if len(digitos) >= DIGITOS_MINIMOS:
            return signo * float(f"{digitos[:2]}.{digitos[2:]}"), Lectura.REPARADA
        if _DECIMAL.match(s):
            return float(s.replace(",", ".")), Lectura.ORIGINAL
    return float("nan"), Lectura.ILEGIBLE


def normalizar_comuna(nombre: object) -> str:
    """Mayúsculas, sin tildes y solo letras: 'Til Til', 'TILTIL' y 'Tiltil.' coinciden."""
    texto = unicodedata.normalize("NFKD", str(nombre)).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z]", "", texto.upper())


def huellas_comunales(unidades: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Unión de las manzanas y entidades de cada comuna, en metros. Uso interno: no se dibuja."""
    if "comuna" not in unidades.columns:
        raise ErrorDatos("Las unidades censales no traen la columna comuna")
    base = unidades[["comuna", "geometry"]].to_crs(CRS_METRICO_RM).copy()
    base["clave"] = base["comuna"].map(normalizar_comuna)
    return base.dissolve(by="clave", as_index=False)[["clave", "geometry"]]


def evaluar(
    tabla: pd.DataFrame,
    unidades: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Aplica la regla de E-3 a una tabla con columnas latitud, longitud y comuna (texto crudo).

    Devuelve un GeoDataFrame en EPSG:4326 con lectura_lat, lectura_lon, estado, motivo y
    distancia_m (a la huella de su comuna; NaN si no se pudo medir).
    """
    faltan = {"latitud", "longitud", "comuna"} - set(tabla.columns)
    if faltan:
        raise ErrorDatos(f"Faltan columnas para evaluar coordenadas: {sorted(faltan)}")
    lat = [leer_coordenada(v) for v in tabla["latitud"]]
    lon = [leer_coordenada(v) for v in tabla["longitud"]]
    salida = tabla.copy()
    salida["lat"] = [v for v, _ in lat]
    salida["lon"] = [v for v, _ in lon]
    salida["lectura_lat"] = [c.value for _, c in lat]
    salida["lectura_lon"] = [c.value for _, c in lon]
    salida["clave_comuna"] = salida["comuna"].map(normalizar_comuna)

    lon_min, lat_min, lon_max, lat_max = CAJA_RM
    en_caja = salida["lat"].between(lat_min, lat_max) & salida["lon"].between(lon_min, lon_max)
    huellas = huellas_comunales(unidades)
    conocida = salida["clave_comuna"].isin(set(huellas["clave"]))

    puntos = gpd.GeoDataFrame(
        salida,
        geometry=gpd.points_from_xy(salida["lon"], salida["lat"]),
        crs=CRS_GEOGRAFICO,
    )
    metricos = puntos.to_crs(CRS_METRICO_RM).geometry
    por_clave = dict(zip(huellas["clave"], huellas.geometry, strict=True))
    distancias = np.full(len(puntos), np.nan)
    medibles = (en_caja & conocida).to_numpy()
    for i in np.flatnonzero(medibles):
        distancias[i] = metricos.iloc[i].distance(por_clave[salida["clave_comuna"].iloc[i]])
    puntos["distancia_m"] = distancias

    motivo = np.select(
        [
            ~salida["lat"].notna().to_numpy() | ~salida["lon"].notna().to_numpy(),
            ~en_caja.to_numpy(),
            ~conocida.to_numpy(),
            ~(puntos["distancia_m"] <= DISTANCIA_MAXIMA_M).to_numpy(),
        ],
        [
            "coordenada_inutilizable",
            "fuera_de_la_region",
            "comuna_no_reconocida",
            "lejos_de_su_comuna",
        ],
        default="",
    )
    puntos["motivo"] = motivo
    puntos["estado"] = np.where(motivo == "", Estado.ACEPTADA.value, Estado.A_GEOCODIFICAR.value)
    return puntos
