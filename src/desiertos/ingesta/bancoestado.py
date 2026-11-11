"""Red de atención de BancoEstado: Caja Vecina, sucursales y BancoEstado Express.

Enmienda E-1: se descartan al ingresar las columnas comerciales internas y nunca se publica la
lista de puntos. Un punto es activo si su columna `estado` vale VIGENTE.
Enmienda E-3: las coordenadas pasan por la regla de `desiertos.ingesta.coordenadas`; lo que no
se acepta queda en una cola de geocodificación con su dirección.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import geopandas as gpd
import pandas as pd

from desiertos import CRS_GEOGRAFICO
from desiertos.errores import ErrorDatos
from desiertos.ingesta.coordenadas import Estado, evaluar

COLUMNAS_DESCARTADAS = frozenset(
    {"puntaje", "score", "categoria", "clusterizacion_txs", "certificado", "estado_proceso"}
)
ESTADO_ACTIVO = "VIGENTE"


class TipoPunto(StrEnum):
    CAJA_VECINA = "caja_vecina"
    SUCURSAL_BE = "sucursal_bancoestado"
    BE_EXPRESS = "bancoestado_express"


@dataclass(frozen=True)
class Fuente:
    tipo: TipoPunto
    archivo: str
    columna_id: str


FUENTES: tuple[Fuente, ...] = (
    Fuente(TipoPunto.CAJA_VECINA, "bancoestado_caja-vecina.csv", "numero_pos"),
    Fuente(TipoPunto.SUCURSAL_BE, "bancoestado_sucursales.csv", "codigo_sucursal"),
    Fuente(TipoPunto.BE_EXPRESS, "bancoestado_be-express.csv", "codigo_sucursal"),
)


@dataclass(frozen=True)
class Resumen:
    """Conteo por tipo de lo leído, de lo activo en la región y del resultado de E-3."""

    tipo: TipoPunto
    filas: int
    activas_en_region: int
    aceptadas_originales: int
    aceptadas_reparadas: int
    a_geocodificar: int


def _leer_csv(ruta: Path) -> pd.DataFrame:
    try:
        tabla = pd.read_csv(ruta, sep=";", dtype=str, encoding="utf-8")
    except (OSError, UnicodeDecodeError, pd.errors.ParserError) as exc:
        raise ErrorDatos(f"No se pudo leer {ruta}: {exc}") from exc
    # El CSV de Caja Vecina repite la columna `estado`; pandas renombra la segunda como `estado.1`.
    repetidas = [c for c in tabla.columns if c.startswith("estado.")]
    tabla = tabla.drop(columns=repetidas)
    tabla = tabla.drop(columns=[c for c in tabla.columns if c in COLUMNAS_DESCARTADAS])
    faltan = {"region", "comuna", "latitud", "longitud", "estado"} - set(tabla.columns)
    if faltan:
        raise ErrorDatos(f"{ruta.name}: faltan columnas {sorted(faltan)}")
    return tabla


def leer_activos(carpeta: Path, fuente: Fuente, region: int) -> tuple[pd.DataFrame, int]:
    """Filas activas de `region` con coordenadas aún en texto, y el total de filas leídas."""
    tabla = _leer_csv(carpeta / fuente.archivo)
    if fuente.columna_id not in tabla.columns:
        raise ErrorDatos(f"{fuente.archivo}: falta la columna {fuente.columna_id}")
    estado = tabla["estado"].astype("string").str.strip().str.upper()
    activa = estado.eq(ESTADO_ACTIVO).fillna(False).astype(bool)
    en_region = pd.to_numeric(tabla["region"], errors="coerce").eq(region)
    elegidas = tabla.loc[activa & en_region]
    salida = pd.DataFrame(
        {
            "id_punto": fuente.tipo.value + ":" + elegidas[fuente.columna_id].astype(str),
            "tipo": fuente.tipo.value,
            "comuna": elegidas["comuna"].astype("string").str.strip().str.upper(),
            "direccion": elegidas.get("direccion", pd.Series(dtype="string")),
            "numero": elegidas.get("numero", pd.Series(dtype="string")),
            "latitud": elegidas["latitud"],
            "longitud": elegidas["longitud"],
        }
    ).reset_index(drop=True)
    return salida, len(tabla)


@dataclass(frozen=True)
class Red:
    aceptados: gpd.GeoDataFrame
    cola_geocodificacion: pd.DataFrame
    resumenes: list[Resumen]


def leer_red(carpeta: Path, region: int, unidades: gpd.GeoDataFrame) -> Red:
    """Une los tres tipos de punto y aplica la regla de coordenadas de E-3."""
    partes: list[gpd.GeoDataFrame] = []
    resumenes: list[Resumen] = []
    for fuente in FUENTES:
        activos, filas = leer_activos(carpeta, fuente, region)
        evaluados = evaluar(activos, unidades)
        aceptada = evaluados["estado"] == Estado.ACEPTADA.value
        reparada = (evaluados["lectura_lat"] == "reparada") | (
            evaluados["lectura_lon"] == "reparada"
        )
        resumenes.append(
            Resumen(
                tipo=fuente.tipo,
                filas=filas,
                activas_en_region=len(evaluados),
                aceptadas_originales=int((aceptada & ~reparada).sum()),
                aceptadas_reparadas=int((aceptada & reparada).sum()),
                a_geocodificar=int((~aceptada).sum()),
            )
        )
        partes.append(evaluados)
    todos = gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), crs=CRS_GEOGRAFICO)
    if todos["id_punto"].duplicated().any():
        raise ErrorDatos("Identificadores de punto repetidos en la red de BancoEstado")
    columnas = [
        "id_punto",
        "tipo",
        "comuna",
        "direccion",
        "numero",
        "lectura_lat",
        "lectura_lon",
        "distancia_m",
    ]
    aceptados = todos.loc[todos["estado"] == Estado.ACEPTADA.value, [*columnas, "geometry"]]
    cola = pd.DataFrame(
        todos.loc[
            todos["estado"] != Estado.ACEPTADA.value,
            ["id_punto", "tipo", "comuna", "direccion", "numero", "latitud", "longitud", "motivo"],
        ]
    )
    return Red(
        aceptados=gpd.GeoDataFrame(aceptados.reset_index(drop=True), crs=CRS_GEOGRAFICO),
        cola_geocodificacion=cola.reset_index(drop=True),
        resumenes=resumenes,
    )
