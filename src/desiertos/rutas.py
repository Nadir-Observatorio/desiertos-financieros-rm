"""Rutas del banco de datos.

El banco no se copia: se apunta. La raíz sale, en orden, de la variable de entorno
DESIERTOS_BANCO o del archivo configuracion.toml en la raíz del repositorio.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from desiertos.errores import ErrorConfiguracion

ARCHIVO_CONFIGURACION = "configuracion.toml"
VARIABLE_ENTORNO = "DESIERTOS_BANCO"


def raiz_repositorio() -> Path:
    """Raíz del repositorio, calculada desde este archivo (src/desiertos/rutas.py)."""
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Rutas:
    """Rutas absolutas a los originales y a los derivados del proyecto."""

    banco: Path

    @property
    def bruto(self) -> Path:
        return self.banco / "bruto"

    @property
    def derivados(self) -> Path:
        return self.banco / "derivados" / "desiertos"

    @property
    def censo_zip(self) -> Path:
        return self.bruto / "ine-censo2024" / "cartografia" / "Cartografia_censo2024_R13.zip"

    @property
    def bancoestado(self) -> Path:
        return self.bruto / "bancoestado" / "red-de-atencion"

    @property
    def cmf_zip(self) -> Path:
        return self.bruto / "cmf" / "reportes-comuna" / "CMF_sucursales_cajeros_comuna_202608.zip"

    @property
    def localizadores(self) -> Path:
        return self.bruto / "bancos-localizadores"

    @property
    def osm_direcciones(self) -> Path:
        return self.derivados / "osm" / "osm_direcciones.parquet"

    @property
    def osm_calles(self) -> Path:
        return self.derivados / "osm" / "osm_calles.parquet"

    @property
    def osm_financieros(self) -> Path:
        return self.derivados / "osm" / "osm_financieros.parquet"

    @property
    def osm_chile(self) -> Path:
        return self.bruto / "osm" / "geofabrik-chile" / "chile-latest.osm.pbf"

    @property
    def osm_rm(self) -> Path:
        return self.derivados / "osm" / "rm.osm.pbf"

    @property
    def gtfs_zip(self) -> Path:
        return self.bruto / "dtpm" / "gtfs" / "GTFS_20261003.zip"


def _banco_desde_toml(archivo: Path) -> Path | None:
    if not archivo.is_file():
        return None
    try:
        datos = tomllib.loads(archivo.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ErrorConfiguracion(f"{archivo} no es TOML válido: {exc}") from exc
    valor = datos.get("rutas", {}).get("banco")
    if valor is None:
        return None
    if not isinstance(valor, str):
        raise ErrorConfiguracion(f"[rutas].banco en {archivo} debe ser texto")
    return Path(valor)


def cargar_rutas(configuracion: Path | None = None) -> Rutas:
    """Resuelve la raíz del banco y comprueba que exista."""
    entorno = os.environ.get(VARIABLE_ENTORNO)
    if entorno:
        banco = Path(entorno)
    else:
        archivo = configuracion or (raiz_repositorio() / ARCHIVO_CONFIGURACION)
        desde_toml = _banco_desde_toml(archivo)
        if desde_toml is None:
            raise ErrorConfiguracion(f"Defina {VARIABLE_ENTORNO} o [rutas].banco en {archivo}")
        banco = desde_toml
    if not banco.is_dir():
        raise ErrorConfiguracion(f"La raíz del banco no existe: {banco}")
    return Rutas(banco=banco)
