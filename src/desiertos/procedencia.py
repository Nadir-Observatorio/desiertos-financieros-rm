"""Comprobación de originales contra su procedencia.toml antes de leerlos."""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

from desiertos.errores import ErrorProcedencia

_BLOQUE = 1 << 20


def sha256_archivo(ruta: Path) -> str:
    """Huella sha256 en hexadecimal, leyendo por bloques."""
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        while bloque := f.read(_BLOQUE):
            h.update(bloque)
    return h.hexdigest()


def huella_registrada(ruta: Path) -> str:
    """Huella declarada para `ruta` en la procedencia.toml de su carpeta."""
    archivo = ruta.parent / "procedencia.toml"
    if not archivo.is_file():
        raise ErrorProcedencia(f"Sin procedencia.toml junto a {ruta}")
    datos = tomllib.loads(archivo.read_text(encoding="utf-8"))
    for entrada in datos.get("archivo", []):
        if entrada.get("nombre") == ruta.name:
            valor = entrada.get("sha256")
            if not isinstance(valor, str):
                raise ErrorProcedencia(f"Entrada sin sha256 para {ruta.name} en {archivo}")
            return valor
    raise ErrorProcedencia(f"{ruta.name} no está registrado en {archivo}")


def verificar(ruta: Path) -> str:
    """Falla si el original no coincide con su huella registrada; devuelve la huella."""
    if not ruta.is_file():
        raise ErrorProcedencia(f"No existe el original {ruta}")
    esperada = huella_registrada(ruta)
    real = sha256_archivo(ruta)
    if real != esperada:
        raise ErrorProcedencia(f"{ruta.name}: sha256 {real} distinto del registrado {esperada}")
    return real
