"""Cálculo de matrices con r5py (R5). Separado para que el resto no dependa de Java al probarse."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import geopandas as gpd
import pandas as pd
import r5py

from desiertos.accesibilidad import CalculoMatriz, Escenario
from desiertos.errores import ErrorDatos

_MODOS = {
    "a_pie": [r5py.TransportMode.WALK],
    "auto": [r5py.TransportMode.CAR],
    "transporte_publico": [r5py.TransportMode.TRANSIT, r5py.TransportMode.WALK],
}


def red_de_transporte(pbf: Path, gtfs: list[Path]) -> r5py.TransportNetwork:
    """Red vial y de transporte; allow_errors porque el GTFS de DTPM trae paradas sin nombre."""
    if not pbf.is_file():
        raise ErrorDatos(f"No existe el extracto {pbf}")
    return r5py.TransportNetwork(pbf, [str(g) for g in gtfs], allow_errors=True)


def calculador(red: r5py.TransportNetwork) -> CalculoMatriz:
    def calcular(
        origenes: gpd.GeoDataFrame, destinos: gpd.GeoDataFrame, escenario: Escenario
    ) -> pd.DataFrame:
        if escenario.modo not in _MODOS:
            raise ErrorDatos(f"Modo desconocido: {escenario.modo}")
        opciones: dict[str, object] = {
            "transport_modes": _MODOS[escenario.modo],
            "departure": escenario.salida,
            "max_time": dt.timedelta(minutes=escenario.tope_min),
            "speed_walking": escenario.velocidad_kmh,
        }
        if escenario.ventana_min > 0:
            opciones["departure_time_window"] = dt.timedelta(minutes=escenario.ventana_min)
            opciones["percentiles"] = [50]
        matriz = r5py.TravelTimeMatrix(red, origins=origenes, destinations=destinos, **opciones)
        tabla = pd.DataFrame(matriz)
        if "travel_time" not in tabla.columns:
            columnas = [c for c in tabla.columns if str(c).startswith("travel_time")]
            if len(columnas) != 1:
                raise ErrorDatos("La matriz de r5py no trae una columna de tiempo única")
            tabla = tabla.rename(columns={columnas[0]: "travel_time"})
        return tabla[["from_id", "to_id", "travel_time"]]

    return calcular
