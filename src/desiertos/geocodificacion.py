"""Geocodificador propio contra direcciones y calles de OpenStreetMap (competencia 5).

Orden de búsqueda dentro de la comuna declarada:
1. `exacta`: un punto OSM con la misma calle y el mismo número.
2. `interpolada`: interpolación lineal entre los dos números más cercanos de la misma calle, uno
   menor y otro mayor.
3. `numero_cercano`: el número más cercano de la calle, si está a 100 o menos en la numeración.
4. `calle`: el punto medio de la calle en la comuna (precisión baja; se rotula).
5. `sin_resultado`.

La calle se busca por nombre normalizado; si no aparece, por similitud (difflib, umbral 0,85).
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from desiertos import CRS_GEOGRAFICO, CRS_METRICO_RM
from desiertos.errores import ErrorDatos
from desiertos.ingesta.coordenadas import normalizar_comuna

UMBRAL_SIMILITUD = 0.85
SALTO_MAXIMO_NUMERO = 100
ACIERTO_M = 100.0
# Las calles corren entre manzanas: sin este margen una calle no toca la huella de su comuna.
MARGEN_COMUNA_M = 30.0  # Protocolo, sección 8: acierto si el resultado cae a 100 m o menos.

_PREFIJOS = {"AVENIDA", "AV", "AVDA", "CALLE", "PASAJE", "PJE", "PSJE", "PJ"}
# Desde la primera de estas palabras (o el primer número) el texto deja de ser nombre de calle.
_CORTES = {
    "N",
    "NRO",
    "NUM",
    "NUMERO",
    "SITIO",
    "PARCELA",
    "CASA",
    "LOTE",
    "DEPTO",
    "DPTO",
    "LOCAL",
    "VILLA",
    "POBLACION",
    "POB",
    "KM",
    "PARADERO",
    "PDA",
    "BLOCK",
    "TORRE",
    "SN",
}
_SINONIMOS = {
    "GRAL": "GENERAL",
    "STA": "SANTA",
    "STO": "SANTO",
    "PDTE": "PRESIDENTE",
    "PTE": "PRESIDENTE",
    "DR": "DOCTOR",
    "CAP": "CAPITAN",
    "TTE": "TENIENTE",
}


class Metodo(StrEnum):
    EXACTA = "exacta"
    INTERPOLADA = "interpolada"
    NUMERO_CERCANO = "numero_cercano"
    CALLE = "calle"
    SIN_RESULTADO = "sin_resultado"


@dataclass(frozen=True)
class Resultado:
    lon: float
    lat: float
    metodo: Metodo
    calle_osm: str | None


def normalizar_calle(nombre: object) -> str:
    """Mayúsculas sin tildes, sin prefijos de tipo de vía y con abreviaturas expandidas."""
    texto = unicodedata.normalize("NFKD", str(nombre)).encode("ascii", "ignore").decode().upper()
    texto = re.sub(r"[^A-Z0-9 ]", " ", texto)
    palabras = [_SINONIMOS.get(p, p) for p in texto.split()]
    while palabras and palabras[0] in _PREFIJOS:
        palabras = palabras[1:]
    for i, palabra in enumerate(palabras):
        if i > 0 and (palabra.isdigit() or palabra in _CORTES):
            palabras = palabras[:i]
            break
    return " ".join(palabras)


def leer_numero(valor: object) -> int | None:
    """Primer grupo de dígitos de un número de calle; None si no hay."""
    coincidencia = re.search(r"\d+", str(valor)) if valor is not None else None
    return int(coincidencia.group()) if coincidencia else None


def _asignar_comuna(
    capa: gpd.GeoDataFrame, huellas: gpd.GeoDataFrame, margen_m: float = 0.0
) -> gpd.GeoDataFrame:
    metrica = capa.to_crs(CRS_METRICO_RM)
    zonas = huellas[["clave", "geometry"]].copy()
    if margen_m > 0:
        zonas["geometry"] = zonas.geometry.buffer(margen_m)
    unidas = gpd.sjoin(metrica, zonas, how="inner", predicate="intersects")
    return unidas.drop(columns="index_right")


class Geocodificador:
    """Índices por (comuna, calle) construidos una vez; consultas en memoria."""

    def __init__(
        self,
        direcciones: gpd.GeoDataFrame,
        calles: gpd.GeoDataFrame,
        huellas: gpd.GeoDataFrame,
    ) -> None:
        if huellas.crs is None or huellas.crs.to_string() != CRS_METRICO_RM:
            huellas = huellas.to_crs(CRS_METRICO_RM)
        dirs = _asignar_comuna(direcciones, huellas)
        dirs["norm"] = dirs["calle"].map(normalizar_calle)
        dirs["n"] = dirs["numero"].map(leer_numero)
        dirs = dirs.dropna(subset=["n"])
        self._numeros: dict[tuple[str, str], pd.DataFrame] = {}
        for (comuna, calle), grupo in dirs.groupby(["clave", "norm"]):
            tabla = pd.DataFrame(
                {"n": grupo["n"].astype(int), "x": grupo.geometry.x, "y": grupo.geometry.y}
            )
            self._numeros[(str(comuna), str(calle))] = (
                tabla.groupby("n", as_index=False)[["x", "y"]].mean().sort_values("n")
            )
        vias = _asignar_comuna(calles, huellas, MARGEN_COMUNA_M)
        vias["norm"] = vias["calle"].map(normalizar_calle)
        # La unión de tramos se hace al consultar (y se guarda), no al construir el índice.
        self._tramos: dict[tuple[str, str], list[BaseGeometry]] = {
            (str(c), str(n)): list(g.geometry) for (c, n), g in vias.groupby(["clave", "norm"])
        }
        self._calles: dict[tuple[str, str], BaseGeometry] = {}
        nombres: dict[str, set[str]] = {}
        for comuna, calle in [*self._numeros.keys(), *self._tramos.keys()]:
            nombres.setdefault(comuna, set()).add(calle)
        self._nombres = {c: sorted(v) for c, v in nombres.items()}

    def _resolver_calle(self, comuna: str, calle: str) -> str | None:
        if (comuna, calle) in self._numeros or (comuna, calle) in self._tramos:
            return calle
        candidatos = difflib.get_close_matches(
            calle, self._nombres.get(comuna, []), n=1, cutoff=UMBRAL_SIMILITUD
        )
        return candidatos[0] if candidatos else None

    def _via(self, comuna: str, calle: str) -> BaseGeometry | None:
        clave = (comuna, calle)
        if clave not in self._calles:
            tramos = self._tramos.get(clave)
            if tramos is None:
                return None
            self._calles[clave] = unary_union(tramos)
        return self._calles[clave]

    def _salida(self, x: float, y: float, metodo: Metodo, calle: str) -> Resultado:
        punto = gpd.GeoSeries(gpd.points_from_xy([x], [y]), crs=CRS_METRICO_RM).to_crs(
            CRS_GEOGRAFICO
        )
        return Resultado(float(punto.x.iloc[0]), float(punto.y.iloc[0]), metodo, calle)

    def geocodificar(self, calle: object, numero: object, comuna: object) -> Resultado:
        clave = normalizar_comuna(comuna)
        nombre = self._resolver_calle(clave, normalizar_calle(calle))
        if nombre is None:
            return Resultado(float("nan"), float("nan"), Metodo.SIN_RESULTADO, None)
        n = leer_numero(numero)
        tabla = self._numeros.get((clave, nombre))
        if tabla is not None and n is not None and len(tabla) > 0:
            numeros = tabla["n"].to_numpy()
            igual = np.flatnonzero(numeros == n)
            if igual.size:
                fila = tabla.iloc[int(igual[0])]
                return self._salida(float(fila["x"]), float(fila["y"]), Metodo.EXACTA, nombre)
            menores = np.flatnonzero(numeros < n)
            mayores = np.flatnonzero(numeros > n)
            if menores.size and mayores.size:
                a, b = tabla.iloc[int(menores[-1])], tabla.iloc[int(mayores[0])]
                t = (n - a["n"]) / (b["n"] - a["n"])
                x = float(a["x"] + t * (b["x"] - a["x"]))
                y = float(a["y"] + t * (b["y"] - a["y"]))
                return self._salida(x, y, Metodo.INTERPOLADA, nombre)
            cercano = int(np.argmin(np.abs(numeros - n)))
            if abs(int(numeros[cercano]) - n) <= SALTO_MAXIMO_NUMERO:
                fila = tabla.iloc[cercano]
                return self._salida(
                    float(fila["x"]), float(fila["y"]), Metodo.NUMERO_CERCANO, nombre
                )
        via = self._via(clave, nombre)
        if via is not None and not via.is_empty:
            medio = (
                via.interpolate(0.5, normalized=True)
                if via.geom_type.endswith("LineString")
                else via.representative_point()
            )
            return self._salida(float(medio.x), float(medio.y), Metodo.CALLE, nombre)
        return Resultado(float("nan"), float("nan"), Metodo.SIN_RESULTADO, nombre)


def geocodificar_tabla(geo: Geocodificador, tabla: pd.DataFrame) -> gpd.GeoDataFrame:
    """Geocodifica una tabla con columnas direccion, numero y comuna."""
    faltan = {"direccion", "numero", "comuna"} - set(tabla.columns)
    if faltan:
        raise ErrorDatos(f"Faltan columnas para geocodificar: {sorted(faltan)}")
    resultados = [
        geo.geocodificar(d, n, c)
        for d, n, c in zip(tabla["direccion"], tabla["numero"], tabla["comuna"], strict=True)
    ]
    salida = tabla.copy()
    salida["metodo"] = [r.metodo.value for r in resultados]
    salida["calle_osm"] = [r.calle_osm for r in resultados]
    return gpd.GeoDataFrame(
        salida,
        geometry=gpd.points_from_xy([r.lon for r in resultados], [r.lat for r in resultados]),
        crs=CRS_GEOGRAFICO,
    )


def medir_calidad(
    estimados: gpd.GeoDataFrame, verdaderos: gpd.GeoSeries
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Error en metros por fila y resumen (protocolo, sección 8).

    La tasa de acierto se calcula sobre todas las filas: un resultado vacío cuenta como fallo.
    """
    if len(estimados) != len(verdaderos):
        raise ErrorDatos("Estimados y verdaderos deben tener el mismo largo")
    a = estimados.geometry.to_crs(CRS_METRICO_RM).reset_index(drop=True)
    b = verdaderos.to_crs(CRS_METRICO_RM).reset_index(drop=True)
    error = a.distance(b)
    tabla = pd.DataFrame({"metodo": estimados["metodo"].to_numpy(), "error_m": error.to_numpy()})
    con = tabla["error_m"].notna()
    resumen = {
        "filas": float(len(tabla)),
        "tasa_con_resultado": float(con.mean()),
        "tasa_acierto_100m": float((tabla["error_m"] <= ACIERTO_M).mean()),
        "error_mediana_m": float(tabla.loc[con, "error_m"].median()) if con.any() else float("nan"),
        "error_p90_m": float(tabla.loc[con, "error_m"].quantile(0.9))
        if con.any()
        else float("nan"),
    }
    return tabla, resumen
