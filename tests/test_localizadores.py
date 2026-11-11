from __future__ import annotations

import hashlib
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, box

from desiertos import CRS_GEOGRAFICO
from desiertos.completitud import (
    asignar_comuna,
    conteo_localizadores_por_comuna,
    evaluar_por_banco,
)
from desiertos.errores import ErrorDatos, ErrorProcedencia
from desiertos.ingesta.localizadores import (
    leer_bci,
    leer_falabella,
    leer_scotiabank,
    separar_numero,
)
from desiertos.puntos import es_marca_con_fuente, unir_puntos


def _registrar(carpeta: Path, nombres: list[str]) -> None:
    lineas = []
    for nombre in nombres:
        datos = (carpeta / nombre).read_bytes()
        lineas += [
            "[[archivo]]",
            f'nombre = "{nombre}"',
            f"bytes = {len(datos)}",
            f'sha256 = "{hashlib.sha256(datos).hexdigest()}"',
            "",
        ]
    (carpeta / "procedencia.toml").write_text("\n".join(lineas), encoding="utf-8")


def _entrada(
    uuid: str, lon: str, lat: str, region: str, campos: dict[str, object]
) -> dict[str, object]:
    ubicacion = {
        "location": {"lat": lat, "lon": lon},
        "location_street": "Antonio Varas 3, Providencia",
        "administrative_area_level_1": region,
        "administrative_area_level_3": "Providencia",
    }
    return {"meta": {"uuid": uuid}, "fields": {"Ubicación": [ubicacion], **campos}}


def test_leer_bci(tmp_path: Path) -> None:
    suc = {"entries": [_entrada("s1", "-70.61", "-33.42", "Región Metropolitana", {})]}
    caj = {
        "entries": [
            _entrada("c1", "-70.62", "-33.43", "Región Metropolitana", {"Número de Cajeros": "3"}),
            _entrada("c2", "-71.6", "-33.0", "Región de Valparaíso", {"Número de Cajeros": ""}),
            {"meta": {"uuid": "c3"}, "fields": {"Ubicación": [], "Número de Cajeros": "1"}},
        ]
    }
    (tmp_path / "bci_sucursal_p01.json").write_text(json.dumps(suc), encoding="utf-8")
    (tmp_path / "bci_cajero_p01.json").write_text(json.dumps(caj), encoding="utf-8")
    _registrar(tmp_path, ["bci_sucursal_p01.json", "bci_cajero_p01.json"])
    tabla = leer_bci(tmp_path).set_index("id_punto")
    assert list(tabla.index) == ["bci:s1", "bci:c1", "bci:c2"]
    assert tabla.loc["bci:c1", "n_cajeros"] == 3
    assert tabla.loc["bci:c2", "n_cajeros"] == 0
    assert not tabla.loc["bci:c2", "region_rm"]
    assert tabla.loc["bci:s1", "comuna"] == "PROVIDENCIA"


def test_leer_bci_rechaza_archivo_alterado(tmp_path: Path) -> None:
    for tipo in ("sucursal", "cajero"):
        (tmp_path / f"bci_{tipo}_p01.json").write_text('{"entries": []}', encoding="utf-8")
    _registrar(tmp_path, ["bci_sucursal_p01.json", "bci_cajero_p01.json"])
    (tmp_path / "bci_cajero_p01.json").write_text('{"entries": [ ]}', encoding="utf-8")
    with pytest.raises(ErrorProcedencia):
        leer_bci(tmp_path)


def _falabella_html(objetos: list[dict[str, object]]) -> str:
    carga = json.dumps(objetos, ensure_ascii=False, separators=(",", ":"))
    trozo = json.dumps(f"1:{carga}", ensure_ascii=False)
    return f"<html><script>self.__next_f.push([1,{trozo}])</script></html>"


def test_leer_falabella(tmp_path: Path) -> None:
    base = {
        "address": "Ahumada 302",
        "localidad": "Santiago",
        "divisionAdministrativa": "Región Metropolitana de Santiago",
        "estado": "disponible",
    }
    objetos = [
        {
            "id": "A1",
            "name": "Ahumada",
            **base,
            "coordinates": {"lon": -70.65, "lat": -33.44},
            "esCajero": False,
            "nota": 'texto con "comillas"',
        },
        {
            "id": "B2",
            "name": "Cajero",
            **base,
            "coordinates": {"lon": -70.6, "lat": -33.4},
            "esCajero": True,
        },
        {
            "id": "C3",
            "name": "Cerrada",
            **{**base, "estado": "cerrada"},
            "coordinates": {"lon": -70.6, "lat": -33.4},
            "esCajero": True,
        },
        {
            "id": "A1",
            "name": "Ahumada",
            **base,
            "coordinates": {"lon": -70.65, "lat": -33.44},
            "esCajero": False,
        },
    ]
    pagina = tmp_path / "falabella.html"
    pagina.write_text(_falabella_html(objetos), encoding="utf-8")
    _registrar(tmp_path, ["falabella.html"])
    tabla = leer_falabella(pagina).set_index("id_punto")
    assert list(tabla.index) == ["falabella:A1", "falabella:B2"]
    assert tabla.loc["falabella:A1", "tipo"] == "sucursal"
    assert tabla.loc["falabella:B2", "n_cajeros"] == 1
    assert tabla.loc["falabella:A1", "comuna"] == "SANTIAGO"


def test_leer_scotiabank_omite_comentadas_y_deshabilitadas(tmp_path: Path) -> None:
    ficha = (
        '<div class="sc-sucursal-card{clase}" data-region="{region}" data-comuna="{slug}">'
        '<div class="x"><img src="s.svg" /><div class="c"><span class="caption">{nombre}</span>'
        '<br />{direccion}</div>\n<div class="b">{comuna}</div></div></div>'
    )
    html_texto = "".join(
        [
            ficha.format(
                clase="",
                region="RM",
                slug="lo-barnechea",
                nombre="La Dehesa",
                direccion="El Rodeo 12699, Local 1",
                comuna="Lo Barnechea",
            ),
            "<!-- "
            + ficha.format(
                clase="",
                region="RM",
                slug="x",
                nombre="Vieja",
                direccion="Calle 1",
                comuna="Santiago",
            )
            + " -->",
            ficha.format(
                clase=" sc-card-disabled",
                region="RM",
                slug="y",
                nombre="Cerrada",
                direccion="Calle 2",
                comuna="Santiago",
            ),
            ficha.format(
                clase="",
                region="R5",
                slug="vina",
                nombre="Vi&ntilde;a",
                direccion="Valpara&iacute;so 100",
                comuna="Vi&ntilde;a del Mar",
            ),
        ]
    )
    pagina = tmp_path / "scotia.html"
    pagina.write_text(html_texto, encoding="utf-8")
    _registrar(tmp_path, ["scotia.html"])
    tabla = leer_scotiabank(pagina)
    assert list(tabla["comuna"]) == ["LOBARNECHEA", "VINADELMAR"]
    assert list(tabla["region_rm"]) == [True, False]
    assert tabla.geometry.isna().all()
    assert tabla["direccion"].iloc[1] == "Valparaíso 100"


@pytest.mark.parametrize(
    ("direccion", "esperado"),
    [
        ("El Rodeo 12699, Local 1", ("El Rodeo", "12699")),
        ("5 de Abril 98", ("5 de Abril", "98")),
        ("Vicuña Mackenna Oriente 7399-A", ("Vicuña Mackenna Oriente", "7399")),
        ("Av. Los Leones # 120", ("Av. Los Leones", "120")),
        ("Sin numero", ("Sin numero", None)),
    ],
)
def test_separar_numero(direccion: str, esperado: tuple[str, str | None]) -> None:
    assert separar_numero(direccion) == esperado


def _huellas() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"clave": ["A", "B"]},
        geometry=[box(0, 0, 1000, 1000), box(3000, 0, 4000, 1000)],
        crs="EPSG:32719",
    )


def test_asignar_comuna_por_cercania_con_tope() -> None:
    puntos = gpd.GeoDataFrame(
        {"id": [1, 2, 3]},
        geometry=[Point(500, 500), Point(1500, 500), Point(2000, 5000)],
        crs="EPSG:32719",
    )
    asignados = asignar_comuna(puntos, _huellas())
    assert list(asignados["id"]) == [1, 2]
    assert list(asignados["clave"]) == ["A", "A"]


def test_evaluar_por_banco() -> None:
    capa = gpd.GeoDataFrame(
        {
            "banco": ["bci", "bci", "bci", "falabella"],
            "tipo": ["sucursal", "cajero", "cajero", "sucursal"],
            "n_cajeros": [0, 2, 1, 0],
        },
        geometry=[Point(100, 100), Point(200, 200), Point(300, 300), Point(3500, 500)],
        crs="EPSG:32719",
    )
    conteo = conteo_localizadores_por_comuna(capa, _huellas())
    cmf = pd.DataFrame(
        {
            "comuna": ["A", "B", "A"],
            "institucion": ["Banco de Credito e Inversiones"] * 2 + ["Banco Falabella"],
            "cmf_sucursales": [1, 1, 0],
            "cmf_cajeros": [3, 0, 0],
        }
    )
    tabla = evaluar_por_banco(cmf, conteo).set_index(["banco", "comuna"])
    assert tabla.loc[("bci", "A"), "sucursales_en_rango"]
    assert tabla.loc[("bci", "A"), "cajeros_en_rango"]
    assert tabla.loc[("bci", "B"), "loc_sucursales"] == 0
    assert tabla["razon_sucursales"].isna()[("falabella", "B")]
    assert tabla.loc[("falabella", "B"), "loc_sucursales"] == 1


@pytest.mark.parametrize(
    ("operador", "esperado"),
    [
        ("BCI", True),
        ("Banco de Crédito e Inversiones", True),
        ("Banco Falabella", True),
        ("Scotiabank", True),
        ("BancoEstado", True),
        ("Banco Estado", True),
        ("Caja Vecina BancoEstado", True),
        ("Banco Santander", False),
        ("Banco de Chile", False),
        (None, False),
        (float("nan"), False),
    ],
)
def test_es_marca_con_fuente(operador: object, esperado: bool) -> None:
    assert es_marca_con_fuente(operador) is esperado


def test_unir_puntos_con_localizadores_filtra_osm() -> None:
    red = gpd.GeoDataFrame(
        {
            "id_punto": ["caja_vecina:1"],
            "tipo": ["caja_vecina"],
            "lectura_lat": ["original"],
            "lectura_lon": ["original"],
        },
        geometry=[Point(-70.66, -33.44)],
        crs=CRS_GEOGRAFICO,
    )
    cola = gpd.GeoDataFrame(
        {"id_punto": [], "tipo": [], "metodo": []}, geometry=[], crs=CRS_GEOGRAFICO
    )
    osm = gpd.GeoDataFrame(
        {
            "id_osm": ["n1", "n2", "n3"],
            "amenidad": ["atm", "bank", "atm"],
            "operador": ["Banco Santander", "BCI", None],
        },
        geometry=[Point(-70.6, -33.4)] * 3,
        crs=CRS_GEOGRAFICO,
    )
    loc = gpd.GeoDataFrame(
        {
            "id_punto": ["bci:s1"],
            "banco": ["bci"],
            "tipo": ["sucursal"],
            "origen_coordenada": ["original"],
        },
        geometry=[Point(-70.61, -33.42)],
        crs=CRS_GEOGRAFICO,
    )
    puntos = unir_puntos(red, cola, osm, localizadores=loc)
    assert list(puntos["id_punto"]) == ["caja_vecina:1", "osm:n1", "osm:n3", "bci:s1"]
    assert puntos["tipo"].iloc[-1] == "bci_sucursal"
    with pytest.raises(ErrorDatos):
        unir_puntos(red, cola, osm.drop(columns="operador"), localizadores=loc)
