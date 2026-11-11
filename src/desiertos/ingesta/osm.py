"""Extracción desde OpenStreetMap (.osm.pbf): puntos financieros, direcciones y calles con nombre.

Licencia ODbL. Las áreas (ways cerrados) se representan por el promedio de sus nodos.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import osmium
import pandas as pd
from shapely import wkb
from shapely.geometry import LineString, Polygon

from desiertos import CRS_GEOGRAFICO, CRS_METRICO_RM
from desiertos.errores import ErrorDatos

AMENIDADES_FINANCIERAS = frozenset({"bank", "atm"})
PREFIJOS_EXCLUIDOS = ("disused:", "abandoned:")
# Valores de building que no son una construcción habitable en pie (enmienda E-6).
EDIFICIOS_EXCLUIDOS = frozenset({"no", "roof", "ruins", "construction"})


@dataclass(frozen=True)
class ExtractoOSM:
    puntos_financieros: gpd.GeoDataFrame
    direcciones: gpd.GeoDataFrame
    calles: gpd.GeoDataFrame


def _centro_way(way: osmium.osm.Way) -> tuple[float, float] | None:
    coords = [(n.location.lon, n.location.lat) for n in way.nodes if n.location.valid()]
    if not coords:
        return None
    return sum(c[0] for c in coords) / len(coords), sum(c[1] for c in coords) / len(coords)


def _vigente(tags: osmium.osm.TagList, fecha_extracto: str | None) -> bool:
    if any(k.startswith(PREFIJOS_EXCLUIDOS) for k, _ in tags):
        return False
    fin = tags.get("end_date")
    return not (fin and fecha_extracto and fin[:10] < fecha_extracto)


def extraer(pbf: Path, fecha_extracto: str | None = None) -> ExtractoOSM:
    """Recorre el .pbf una vez y devuelve las tres capas en EPSG:4326."""
    if not pbf.is_file():
        raise ErrorDatos(f"No existe {pbf}")
    fabrica = osmium.geom.WKBFactory()
    financieros: list[dict[str, object]] = []
    direcciones: list[dict[str, object]] = []
    calles: list[dict[str, object]] = []
    for obj in osmium.FileProcessor(str(pbf)).with_locations():
        xy: tuple[float, float] | None
        if isinstance(obj, osmium.osm.Node):
            if not obj.location.valid():
                continue
            xy = (obj.location.lon, obj.location.lat)
        elif isinstance(obj, osmium.osm.Way):
            xy = _centro_way(obj)
        else:
            continue
        tags = obj.tags
        amenidad = tags.get("amenity")
        if amenidad in AMENIDADES_FINANCIERAS and xy and _vigente(tags, fecha_extracto):
            financieros.append(
                {
                    "id_osm": f"{obj.type_str()}{obj.id}",
                    "amenidad": amenidad,
                    "operador": tags.get("operator") or tags.get("brand") or tags.get("name"),
                    "calle": tags.get("addr:street"),
                    "numero": tags.get("addr:housenumber"),
                    "lon": xy[0],
                    "lat": xy[1],
                }
            )
        if "addr:housenumber" in tags and "addr:street" in tags and xy:
            direcciones.append(
                {
                    "calle": tags["addr:street"],
                    "numero": tags["addr:housenumber"],
                    "lon": xy[0],
                    "lat": xy[1],
                }
            )
        if isinstance(obj, osmium.osm.Way) and "highway" in tags and "name" in tags:
            try:
                linea = wkb.loads(fabrica.create_linestring(obj), hex=True)
            except (RuntimeError, osmium.InvalidLocationError):
                continue
            calles.append({"calle": tags["name"], "geometry": linea})

    def _puntos(filas: list[dict[str, object]]) -> gpd.GeoDataFrame:
        tabla = pd.DataFrame(filas)
        if tabla.empty:
            return gpd.GeoDataFrame(tabla, geometry=[], crs=CRS_GEOGRAFICO)
        return gpd.GeoDataFrame(
            tabla.drop(columns=["lon", "lat"]),
            geometry=gpd.points_from_xy(tabla["lon"], tabla["lat"]),
            crs=CRS_GEOGRAFICO,
        )

    capa_calles = gpd.GeoDataFrame(
        pd.DataFrame(calles), geometry="geometry" if calles else [], crs=CRS_GEOGRAFICO
    )
    return ExtractoOSM(
        puntos_financieros=_puntos(financieros),
        direcciones=_puntos(direcciones),
        calles=capa_calles,
    )


def extraer_edificios(pbf: Path) -> gpd.GeoDataFrame:
    """Edificios de OSM (ways cerrados con building) para la sensibilidad dasimétrica (E-6).

    Cada edificio queda como un punto interior de su planta (representative_point de shapely, que
    siempre cae dentro del polígono, a diferencia del promedio de nodos en plantas cóncavas), con
    su área de planta en m² (UTM 19 S). Se excluyen los valores de EDIFICIOS_EXCLUIDOS.
    Columnas: id_osm, area_m2 y geometría (EPSG:4326).
    """
    if not pbf.is_file():
        raise ErrorDatos(f"No existe {pbf}")
    ids: list[str] = []
    plantas: list[Polygon] = []
    filtro = osmium.filter.KeyFilter("building")
    for obj in osmium.FileProcessor(str(pbf)).with_locations().with_filter(filtro):
        if not isinstance(obj, osmium.osm.Way) or not obj.is_closed():
            continue
        if obj.tags.get("building") in EDIFICIOS_EXCLUIDOS:
            continue
        coords = [(n.location.lon, n.location.lat) for n in obj.nodes if n.location.valid()]
        if len(coords) < 4:
            continue
        ids.append(f"w{obj.id}")
        plantas.append(Polygon(coords))
    if not ids:
        raise ErrorDatos(f"{pbf.name}: no hay edificios")
    planta = gpd.GeoSeries(plantas, crs=CRS_GEOGRAFICO)
    return gpd.GeoDataFrame(
        {"id_osm": ids, "area_m2": planta.to_crs(CRS_METRICO_RM).area.to_numpy()},
        geometry=planta.representative_point(),
        crs=CRS_GEOGRAFICO,
    )


def extraer_referencias(pbf: Path) -> gpd.GeoDataFrame:
    """Líneas de referencia del visor: ríos con nombre "Río ..." (waterway=river) y autopistas
    (highway=motorway, sin enlaces). Solo sirven para orientarse en el mapa; no entran al análisis.

    Columnas: tipo ("rio" o "autopista"), nombre y geometría LineString (EPSG:4326).
    """
    if not pbf.is_file():
        raise ErrorDatos(f"No existe {pbf}")
    filas: list[tuple[str, str, LineString]] = []
    filtro = osmium.filter.KeyFilter("waterway", "highway")
    for obj in osmium.FileProcessor(str(pbf)).with_locations().with_filter(filtro):
        if not isinstance(obj, osmium.osm.Way):
            continue
        nombre = obj.tags.get("name") or ""
        if obj.tags.get("waterway") == "river" and nombre.startswith("Río "):
            tipo = "rio"
        elif obj.tags.get("highway") == "motorway":
            tipo = "autopista"
        else:
            continue
        coords = [(n.location.lon, n.location.lat) for n in obj.nodes if n.location.valid()]
        if len(coords) >= 2:
            filas.append((tipo, nombre, LineString(coords)))
    if not filas:
        raise ErrorDatos(f"{pbf.name}: no hay ríos ni autopistas")
    return gpd.GeoDataFrame(
        {"tipo": [f[0] for f in filas], "nombre": [f[1] for f in filas]},
        geometry=[f[2] for f in filas],
        crs=CRS_GEOGRAFICO,
    )


# Caja del recorte de la red para el ruteo: la región con unos 5 a 10 km de margen, para que las
# celdas de borde puedan llegar a puntos de la franja vecina.
CAJA_RECORTE = (-71.85, -34.45, -69.65, -32.75)


def recortar(
    origen: Path, destino: Path, caja: tuple[float, float, float, float]
) -> dict[str, int]:
    """Copia nodos dentro de la caja y ways con al menos un nodo dentro (con sus nodos completos).

    Sin relaciones: el ruteo de R5 usa ways y nodos; las restricciones de giro no se conservan.
    """
    if not origen.is_file():
        raise ErrorDatos(f"No existe el extracto {origen}")
    oeste, sur, este, norte = caja
    if not (oeste < este and sur < norte):
        raise ErrorDatos(f"Caja inválida: {caja}")

    def dentro(lon: float, lat: float) -> bool:
        return oeste <= lon <= este and sur <= lat <= norte

    nodos = ways = 0
    destino.parent.mkdir(parents=True, exist_ok=True)
    with osmium.BackReferenceWriter(str(destino), ref_src=str(origen), overwrite=True) as salida:
        for obj in osmium.FileProcessor(str(origen)).with_locations():
            if isinstance(obj, osmium.osm.Node):
                if obj.location.valid() and dentro(obj.location.lon, obj.location.lat):
                    salida.add_node(obj)
                    nodos += 1
            elif isinstance(obj, osmium.osm.Way) and any(
                n.location.valid() and dentro(n.location.lon, n.location.lat) for n in obj.nodes
            ):
                salida.add_way(obj)
                ways += 1
    return {"nodos": nodos, "ways": ways}
