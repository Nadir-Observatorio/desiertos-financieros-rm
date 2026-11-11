from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pytest

from desiertos.errores import ErrorDatos
from desiertos.ingesta.bancoestado import FUENTES, TipoPunto, leer_activos, leer_red

CABECERA_CV = (
    "numero_pos;region;comuna;localidad;direccion;numero;giro_rubro;estado;"
    "clusterizacion_txs;latitud;longitud;puntaje;categoria;score;estado"
)
CABECERA_SUC = (
    "codigo_sucursal;nombre_sucursal;region;comuna;localidad;direccion;numero;categoria;"
    "cantidad_atm;estado_reg;latitud;longitud;estado_proceso;certificado;h_apertura;h_cierre;"
    "accesibilidad;estado"
)
CABECERA_EXP = (
    "codigo_sucursal;nombre_sucursal;region;comuna;localidad;direccion;numero;estado_reg;"
    "latitud;longitud;estado_proceso;certificado;h_apertura;h_cierre;accesibilidad;estado;servicio"
)


def _escribir(carpeta: Path) -> None:
    (carpeta / "bancoestado_caja-vecina.csv").write_text(
        "\n".join(
            [
                CABECERA_CV,
                "1;13;Santiago;X;Calle;1;ALM;VIGENTE;A;-33,445;-70,655;9;C;7;",
                "2;13;Santiago;X;Calle;2;ALM;INACTIVO;A;-33,445;-70,655;9;C;7;",
                "3;13;Santiago;X;Calle;3;ALM;VIGENTE;A;-3,34E+11;-7,06E+11;9;C;7;",
                "4;5;Valparaíso;X;Calle;4;ALM;VIGENTE;A;-33,04;-71,6;9;C;7;",
                "5;13;Maipú;X;Calle;5;ALM;VIGENTE;A;-335200;-707700;9;C;7;",
            ]
        ),
        encoding="utf-8",
    )
    (carpeta / "bancoestado_sucursales.csv").write_text(
        "\n".join(
            [
                CABECERA_SUC,
                "10;Centro;13;SANTIAGO;X;Calle;1;A;3;2;-33,44;-70,65;1;1;09:00;14:00;1;VIG",
                "11;Otra;13;SANTIAGO;X;Calle;1;A;3;2;-33,44;-70,65;1;1;09:00;14:00;1;VIGENTE",
            ]
        ),
        encoding="utf-8",
    )
    (carpeta / "bancoestado_be-express.csv").write_text(
        "\n".join(
            [
                CABECERA_EXP,
                "20;Express;13;SANTIAGO;X;Calle;1;2;-33.45;-70.66;1;1;09:00;14:00;1;VIGENTE;x",
            ]
        ),
        encoding="utf-8",
    )


def test_leer_activos_filtra_estado_region_y_columnas(tmp_path: Path) -> None:
    _escribir(tmp_path)
    activos, filas = leer_activos(tmp_path, FUENTES[0], 13)
    assert filas == 5
    assert list(activos["id_punto"]) == ["caja_vecina:1", "caja_vecina:3", "caja_vecina:5"]
    for prohibida in ("puntaje", "score", "categoria", "clusterizacion_txs"):
        assert prohibida not in activos.columns


def test_estado_distinto_de_vigente_no_entra(tmp_path: Path) -> None:
    _escribir(tmp_path)
    activos, _ = leer_activos(tmp_path, FUENTES[1], 13)
    assert list(activos["id_punto"]) == ["sucursal_bancoestado:11"]


def test_red_aplica_regla_e3(tmp_path: Path, unidades_rm: gpd.GeoDataFrame) -> None:
    _escribir(tmp_path)
    red = leer_red(tmp_path, 13, unidades_rm)
    assert set(red.aceptados["id_punto"]) == {
        "caja_vecina:1",
        "caja_vecina:5",
        "sucursal_bancoestado:11",
        "bancoestado_express:20",
    }
    assert list(red.cola_geocodificacion["id_punto"]) == ["caja_vecina:3"]
    assert list(red.cola_geocodificacion["motivo"]) == ["coordenada_inutilizable"]
    cv = next(r for r in red.resumenes if r.tipo is TipoPunto.CAJA_VECINA)
    assert (cv.aceptadas_originales, cv.aceptadas_reparadas, cv.a_geocodificar) == (1, 1, 1)
    assert red.aceptados.crs is not None and red.aceptados.crs.to_epsg() == 4326


def test_falta_columna(tmp_path: Path) -> None:
    (tmp_path / "bancoestado_caja-vecina.csv").write_text("numero_pos;region\n1;13", "utf-8")
    with pytest.raises(ErrorDatos):
        leer_activos(tmp_path, FUENTES[0], 13)
