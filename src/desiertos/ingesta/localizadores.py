"""Localizadores públicos de BCI, Banco Falabella y Scotiabank (enmienda E-4).

Cada lector devuelve la misma tabla: id_punto, banco, tipo (sucursal o cajero), n_cajeros,
direccion, comuna (normalizada), region_rm y geometry en EPSG:4326. Scotiabank no publica
coordenadas: su geometría queda vacía hasta geocodificar. Uso interno: la lista de puntos no se
publica.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from desiertos import CRS_GEOGRAFICO
from desiertos.errores import ErrorDatos
from desiertos.ingesta.coordenadas import normalizar_comuna
from desiertos.procedencia import verificar

COLUMNAS = [
    "id_punto",
    "banco",
    "tipo",
    "n_cajeros",
    "direccion",
    "comuna",
    "region_rm",
    "geometry",
]
TIPOS_BCI = ("sucursal", "cajero")


def _tabla(filas: list[dict[str, Any]]) -> gpd.GeoDataFrame:
    if not filas:
        raise ErrorDatos("El localizador no trae puntos")
    tabla = gpd.GeoDataFrame(pd.DataFrame(filas), geometry="geometry", crs=CRS_GEOGRAFICO)
    if tabla["id_punto"].duplicated().any():
        raise ErrorDatos("Identificadores repetidos en el localizador")
    return tabla[COLUMNAS]


def _punto(lon: object, lat: object) -> Point | None:
    try:
        x, y = float(str(lon)), float(str(lat))
    except ValueError:
        return None
    if not (-110.0 < x < -66.0 and -56.0 < y < -17.0):
        return None
    return Point(x, y)


def leer_bci(carpeta: Path) -> gpd.GeoDataFrame:
    """Respuestas JSON del servicio del localizador de BCI (bci_<tipo>_pNN.json)."""
    filas: list[dict[str, Any]] = []
    for tipo in TIPOS_BCI:
        archivos = sorted(carpeta.glob(f"bci_{tipo}_p*.json"))
        if not archivos:
            raise ErrorDatos(f"Sin respuestas de BCI para el tipo {tipo} en {carpeta}")
        for archivo in archivos:
            verificar(archivo)
            try:
                entradas = json.loads(archivo.read_text(encoding="utf-8"))["entries"]
            except (json.JSONDecodeError, KeyError) as exc:
                raise ErrorDatos(f"{archivo.name} no es una respuesta válida de BCI") from exc
            for entrada in entradas:
                campos = entrada["fields"]
                ubicaciones = campos.get("Ubicación") or []
                if not ubicaciones:
                    continue
                u = ubicaciones[0]
                loc = u.get("location") or {}
                n = campos.get("Número de Cajeros") if tipo == "cajero" else 0
                filas.append(
                    {
                        "id_punto": f"bci:{entrada['meta']['uuid']}",
                        "banco": "bci",
                        "tipo": tipo,
                        "n_cajeros": int(n or 0) if str(n or 0).isdigit() else 0,
                        "direccion": str(u.get("location_street") or ""),
                        "comuna": normalizar_comuna(u.get("administrative_area_level_3")),
                        "region_rm": "Metropolitana" in str(u.get("administrative_area_level_1")),
                        "geometry": _punto(loc.get("lon"), loc.get("lat")),
                    }
                )
    return _tabla(filas)


_TROZO_NEXT = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')


def _objetos_falabella(texto: str) -> list[dict[str, Any]]:
    """Objetos {"id":..,"name":..} del listado incrustado en los trozos de datos de la página."""
    try:
        plano = "".join(json.loads(m.group(1)) for m in _TROZO_NEXT.finditer(texto))
    except json.JSONDecodeError as exc:
        raise ErrorDatos("No se pudieron leer los datos incrustados de la página") from exc
    objetos: list[dict[str, Any]] = []
    decodificador = json.JSONDecoder()
    for m in re.finditer(r'\{"id":"[A-Za-z0-9]+","name":', plano):
        try:
            obj, _ = decodificador.raw_decode(plano, m.start())
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            objetos.append(obj)
    return objetos


def leer_falabella(pagina: Path) -> gpd.GeoDataFrame:
    """Página pública de oficinas de Banco Falabella; solo puntos en estado disponible."""
    verificar(pagina)
    filas: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for obj in _objetos_falabella(pagina.read_text(encoding="utf-8", errors="replace")):
        if "coordinates" not in obj or "esCajero" not in obj or obj["id"] in vistos:
            continue
        vistos.add(obj["id"])
        if obj.get("estado") != "disponible":
            continue
        coord = obj["coordinates"] or {}
        filas.append(
            {
                "id_punto": f"falabella:{obj['id']}",
                "banco": "falabella",
                "tipo": "cajero" if obj["esCajero"] is True else "sucursal",
                "n_cajeros": 1 if obj["esCajero"] is True else 0,
                "direccion": str(obj.get("address") or ""),
                "comuna": normalizar_comuna(obj.get("localidad")),
                "region_rm": "Metropolitana" in str(obj.get("divisionAdministrativa")),
                "geometry": _punto(coord.get("lon"), coord.get("lat")),
            }
        )
    return _tabla(filas)


_FICHA = re.compile(
    r'<div class="sc-sucursal-card(?P<clase>[^"]*)" data-region="(?P<region>[^"]+)"'
    r' data-comuna="(?P<slug>[^"]+)">.*?<span class="caption">(?P<nombre>.*?)</span><br\s*/?>'
    r"(?P<direccion>.*?)</div>\s*<div[^>]*>(?P<comuna>.*?)</div>",
    re.S,
)


def leer_scotiabank(pagina: Path) -> gpd.GeoDataFrame:
    """Fichas de sucursales de Scotiabank; las comentadas o deshabilitadas no se cuentan."""
    verificar(pagina)
    texto = re.sub(
        r"<!--.*?-->", "", pagina.read_text(encoding="utf-8", errors="replace"), flags=re.S
    )
    filas: list[dict[str, Any]] = []
    for m in _FICHA.finditer(texto):
        if "disabled" in m["clase"]:
            continue
        direccion = html.unescape(re.sub(r"<[^>]+>", " ", m["direccion"])).strip()
        comuna = html.unescape(re.sub(r"<[^>]+>", " ", m["comuna"])).strip()
        filas.append(
            {
                "id_punto": "scotiabank:"
                + normalizar_comuna(f"{m['slug']} {m['nombre']} {direccion}").lower(),
                "banco": "scotiabank",
                "tipo": "sucursal",
                "n_cajeros": 0,
                "direccion": re.sub(r"\s+", " ", direccion),
                "comuna": normalizar_comuna(comuna),
                "region_rm": m["region"].strip().upper() == "RM",
                "geometry": None,
            }
        )
    return _tabla(filas)


_NUMERO_CASA = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ.']\s*[#Nº°]*\s*(\d+)")


def separar_numero(direccion: str) -> tuple[str, str | None]:
    """Calle y número de casa: el primer número que sigue a una palabra.

    'El Rodeo 12699, Local 1' -> ('El Rodeo', '12699'); '5 de Abril 98' -> ('5 de Abril', '98').
    Sin número devuelve None.
    """
    m = _NUMERO_CASA.search(direccion)
    if m is None:
        return direccion.strip(), None
    calle = re.sub(r"[#Nº°.,\s]+$", "", direccion[: m.start(1)]).strip()
    return calle, m.group(1)
