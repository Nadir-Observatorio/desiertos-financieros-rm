"""Capa única de puntos de acceso para el indicador principal (enmiendas E-1, E-3 y E-4).

Une la red de BancoEstado aceptada, la cola geocodificada con método aceptado, los localizadores
de BCI, Banco Falabella y Scotiabank, y los bancos y cajeros de OpenStreetMap. Con localizadores,
OSM conserva solo los puntos de bancos sin fuente propia (E-4). Uso interno: la lista de puntos
no se publica.
"""

from __future__ import annotations

import re
import unicodedata

import geopandas as gpd
import pandas as pd

from desiertos import CRS_GEOGRAFICO
from desiertos.errores import ErrorDatos
from desiertos.geocodificacion import Metodo

# Decisión registrada en docs/enmiendas.md (E-3): p90 de 73 y 179 m en la muestra de prueba.
METODOS_ACEPTADOS = frozenset({Metodo.EXACTA.value, Metodo.INTERPOLADA.value})
# Sensibilidad registrada en E-3: agrega el número cercano (p90 de 459 m).
METODOS_SENSIBILIDAD = METODOS_ACEPTADOS | {Metodo.NUMERO_CERCANO.value}
COLUMNAS = ["id_punto", "fuente", "tipo", "origen_coordenada", "geometry"]
# Operadores OSM de bancos con fuente propia (E-4); se comparan sin tildes, en mayúsculas.
_MARCAS_CON_FUENTE = re.compile(
    r"\bBCI\b|CREDITO E INVERSIONES|FALABELLA|SCOTIA|BANCO ?ESTADO|BANCO DEL ESTADO|CAJA ?VECINA"
)


def _sin_tildes(texto: object) -> str:
    plano = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in plano if not unicodedata.combining(c)).upper()


def es_marca_con_fuente(operador: object) -> bool:
    """True si el operador OSM es un banco cuya capa viene de su propia fuente (E-4)."""
    if operador is None or (isinstance(operador, float) and pd.isna(operador)):
        return False
    return _MARCAS_CON_FUENTE.search(_sin_tildes(operador)) is not None


def _origen_bancoestado(red: gpd.GeoDataFrame) -> pd.Series:
    reparada = (red["lectura_lat"] == "reparada") | (red["lectura_lon"] == "reparada")
    return pd.Series(["reparada" if r else "original" for r in reparada], index=red.index)


def unir_puntos(
    red: gpd.GeoDataFrame,
    cola_geocodificada: gpd.GeoDataFrame,
    osm: gpd.GeoDataFrame,
    metodos: frozenset[str] = METODOS_ACEPTADOS,
    localizadores: gpd.GeoDataFrame | None = None,
) -> gpd.GeoDataFrame:
    """Devuelve la capa de puntos con id, fuente, tipo y origen de la coordenada.

    `localizadores` trae las columnas id_punto, banco, tipo, origen_coordenada y geometry; los
    puntos sin geometría se descartan antes de llamar. Con localizadores, OSM pierde los puntos
    cuyo operador es un banco con fuente propia.
    """
    for nombre, capa, columnas in (
        ("red", red, {"id_punto", "tipo", "lectura_lat", "lectura_lon"}),
        ("cola", cola_geocodificada, {"id_punto", "tipo", "metodo"}),
        ("osm", osm, {"id_osm", "amenidad"}),
    ):
        faltan = columnas - set(capa.columns)
        if faltan:
            raise ErrorDatos(f"Capa {nombre}: faltan columnas {sorted(faltan)}")
    a = gpd.GeoDataFrame(
        {
            "id_punto": red["id_punto"],
            "fuente": "bancoestado",
            "tipo": red["tipo"],
            "origen_coordenada": _origen_bancoestado(red),
        },
        geometry=red.geometry.to_crs(CRS_GEOGRAFICO),
    )
    elegidos = cola_geocodificada[cola_geocodificada["metodo"].isin(metodos)]
    b = gpd.GeoDataFrame(
        {
            "id_punto": elegidos["id_punto"],
            "fuente": "bancoestado",
            "tipo": elegidos["tipo"],
            "origen_coordenada": "geocodificada_" + elegidos["metodo"].astype(str),
        },
        geometry=elegidos.geometry.to_crs(CRS_GEOGRAFICO),
    )
    if localizadores is not None:
        if "operador" not in osm.columns:
            raise ErrorDatos("Capa osm: falta la columna operador para filtrar marcas (E-4)")
        osm = osm[~osm["operador"].map(es_marca_con_fuente)]
    c = gpd.GeoDataFrame(
        {
            "id_punto": "osm:" + osm["id_osm"].astype(str),
            "fuente": "osm",
            "tipo": "osm_" + osm["amenidad"].astype(str),
            "origen_coordenada": "original",
        },
        geometry=osm.geometry.to_crs(CRS_GEOGRAFICO),
    )
    partes = [a, b, c]
    if localizadores is not None:
        faltan = {"id_punto", "banco", "tipo", "origen_coordenada"} - set(localizadores.columns)
        if faltan:
            raise ErrorDatos(f"Capa localizadores: faltan columnas {sorted(faltan)}")
        partes.append(
            gpd.GeoDataFrame(
                {
                    "id_punto": localizadores["id_punto"],
                    "fuente": localizadores["banco"],
                    "tipo": localizadores["banco"] + "_" + localizadores["tipo"],
                    "origen_coordenada": localizadores["origen_coordenada"],
                },
                geometry=localizadores.geometry.to_crs(CRS_GEOGRAFICO),
            )
        )
    todos = gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), crs=CRS_GEOGRAFICO)
    if todos["id_punto"].duplicated().any():
        raise ErrorDatos("Identificadores repetidos al unir puntos")
    if todos.geometry.is_empty.any() or todos.geometry.isna().any():
        raise ErrorDatos("Hay puntos sin geometría en la capa unida")
    return todos[COLUMNAS]
