from __future__ import annotations

from pathlib import Path

import osmium
import pytest

from desiertos.errores import ErrorDatos
from desiertos.ingesta.osm import extraer


def _escribir_pbf(ruta: Path) -> None:
    with osmium.SimpleWriter(str(ruta)) as w:
        w.add_node(
            osmium.osm.mutable.Node(
                id=1, location=(-70.66, -33.44), tags={"amenity": "bank", "operator": "Banco X"}
            )
        )
        w.add_node(
            osmium.osm.mutable.Node(
                id=2, location=(-70.65, -33.44), tags={"amenity": "atm", "disused:amenity": "atm"}
            )
        )
        w.add_node(
            osmium.osm.mutable.Node(
                id=3,
                location=(-70.64, -33.44),
                tags={"amenity": "atm", "end_date": "2020-01-01"},
            )
        )
        w.add_node(
            osmium.osm.mutable.Node(
                id=4,
                location=(-70.63, -33.44),
                tags={"addr:street": "Calle Uno", "addr:housenumber": "10"},
            )
        )
        w.add_node(osmium.osm.mutable.Node(id=10, location=(-70.60, -33.40), tags={}))
        w.add_node(osmium.osm.mutable.Node(id=11, location=(-70.59, -33.40), tags={}))
        w.add_way(
            osmium.osm.mutable.Way(
                id=100, nodes=[10, 11], tags={"highway": "residential", "name": "Calle Uno"}
            )
        )


def test_extraer(tmp_path: Path) -> None:
    pbf = tmp_path / "mini.osm.pbf"
    _escribir_pbf(pbf)
    ex = extraer(pbf, "2026-11-08")
    assert list(ex.puntos_financieros["id_osm"]) == ["n1"]
    assert ex.puntos_financieros.iloc[0]["operador"] == "Banco X"
    assert list(ex.direcciones["numero"]) == ["10"]
    assert list(ex.calles["calle"]) == ["Calle Uno"]
    assert ex.calles.geometry.iloc[0].geom_type == "LineString"
    assert ex.direcciones.crs is not None and ex.direcciones.crs.to_epsg() == 4326


def test_extraer_sin_archivo(tmp_path: Path) -> None:
    with pytest.raises(ErrorDatos):
        extraer(tmp_path / "no.pbf")
