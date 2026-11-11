from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import h3
import pandas as pd
import pytest
from shapely.geometry import LineString

from desiertos.errores import ErrorDatos
from desiertos.modelos import ORIENTE, PERIURBANA, POPULAR
from desiertos.visor import (
    MARCA,
    MIN_PERSONAS,
    VENDOR,
    celdas_publicables,
    centros_comunales,
    construir_datos,
    curva_mclp,
    escribir_visor,
    lineas_referencia,
    nombre_visible,
    pagina,
    sitios_mclp,
)

UMBRAL = 15.0
CENTRO = h3.latlng_to_cell(-33.45, -70.65, 9)
LEJOS = h3.latlng_to_cell(-33.80, -70.30, 9)
# Las 7 hijas de un hexágono r8 comparten padre r6.
RURALES = sorted(h3.cell_to_children(h3.cell_to_parent(LEJOS, 8), 9))


def _celdas() -> pd.DataFrame:
    """Diez celdas urbanas grandes junto al centro y un grupo rural de celdas chicas lejos."""
    urbanas = [CENTRO, *h3.grid_ring(CENTRO, 1), *h3.grid_ring(CENTRO, 2)[:3]]
    rurales = RURALES
    filas: list[dict[str, Any]] = []
    for i, c in enumerate(urbanas):
        filas.append(
            {"h3": c, "cut": 13101, "n_per": 400.0 + i, "rural": False, "minutos": 4.0 + i * 0.1}
        )
    # Una urbana grande en desierto, con minutos que se redondean al umbral (15,4 -> 15).
    filas[-1]["minutos"] = 15.4
    for i, c in enumerate(rurales):
        filas.append({"h3": c, "cut": 13401, "n_per": 3.0 + i, "rural": True, "minutos": 40.0})
    tabla = pd.DataFrame(filas)
    tabla["censurada"] = False
    centros = [h3.cell_to_latlng(c) for c in tabla["h3"]]
    tabla["lat"] = [c[0] for c in centros]
    tabla["lon"] = [c[1] for c in centros]
    tabla["gi_clase"] = ["caliente" if r else "ninguno" for r in tabla["rural"]]
    tabla["lisa"] = "no_significativo"
    return tabla


def test_e8_ninguna_celda_r9_bajo_el_minimo() -> None:
    r9, r6, conteo = celdas_publicables(_celdas(), UMBRAL)
    assert all(fila[1] >= MIN_PERSONAS for fila in r9)
    assert {fila[0] for fila in r9}.isdisjoint(RURALES)
    assert conteo == {"celdas_r9": 10, "celdas_r6": 1, "r6_ocultas": 1, "personas_en_r6": 42}
    # El grupo rural suma 42 personas: el agregado r6 se oculta sin cifras.
    assert r6 == [[h3.cell_to_parent(LEJOS, 6), None, None, None]]


def test_r6_publica_agregado_suficiente() -> None:
    tabla = _celdas()
    tabla.loc[tabla["rural"], "n_per"] = 20.0  # 7 celdas x 20 = 140 personas en desierto
    _, r6, conteo = celdas_publicables(tabla, UMBRAL)
    assert r6 == [[h3.cell_to_parent(LEJOS, 6), 140, 1.0, 40]]
    assert conteo["r6_ocultas"] == 0


def test_marca_de_desierto_usa_minutos_sin_redondear() -> None:
    r9, _, _ = celdas_publicables(_celdas(), UMBRAL)
    fila = next(f for f in r9 if f[2] == 15)
    assert fila[6] == 1


def test_r9_lleva_la_comuna() -> None:
    r9, _, _ = celdas_publicables(_celdas(), UMBRAL)
    assert {fila[7] for fila in r9} == {13101}


def test_centro_comunal_ponderado_por_poblacion() -> None:
    celdas = pd.DataFrame(
        {
            "cut": [1, 1, 2],
            "n_per": [300.0, 100.0, 0.0],
            "lat": [-33.0, -34.0, -35.0],
            "lon": [-70.0, -71.0, -72.0],
        }
    )
    centros = centros_comunales(celdas)
    assert list(centros.index) == [1]  # la comuna 2 no tiene población: sin rótulo
    assert centros.loc[1, "lat"] == pytest.approx(-33.25)
    assert centros.loc[1, "lon"] == pytest.approx(-70.25)


def _referencias() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"tipo": ["rio", "rio", "autopista"], "nombre": ["Río A", "Río A", ""]},
        geometry=[
            LineString([(-70.70, -33.40), (-70.65, -33.40)]),
            LineString([(-70.65, -33.40), (-70.60, -33.40)]),
            LineString([(-70.70, -33.50), (-69.00, -33.50)]),  # sale de la caja
        ],
        crs="EPSG:4326",
    )


def test_lineas_se_unen_recortan_y_redondean() -> None:
    lineas = lineas_referencia(_referencias(), (-70.75, -33.60, -70.55, -33.35))
    assert [linea["t"] for linea in lineas] == ["rio", "autopista"]
    rio, autopista = lineas
    assert rio["c"] == [[[-70.7, -33.4], [-70.6, -33.4]]]  # dos tramos unidos y simplificados
    assert max(x for x, _ in autopista["c"][0]) == pytest.approx(-70.55)


def test_celdas_repetidas_fallan() -> None:
    tabla = _celdas()
    with pytest.raises(ErrorDatos):
        celdas_publicables(pd.concat([tabla, tabla.head(1)]), UMBRAL)


def test_nombre_visible() -> None:
    assert nombre_visible("SAN JOSÉ DE MAIPO") == "San José de Maipo"
    assert nombre_visible("LA FLORIDA") == "La Florida"
    assert nombre_visible("PEDRO AGUIRRE CERDA") == "Pedro Aguirre Cerda"
    with pytest.raises(ErrorDatos):
        nombre_visible("  ")


def test_sitios_al_hexagono_r8_y_sin_repetir() -> None:
    hijo_a, hijo_b = h3.cell_to_children(h3.cell_to_parent(CENTRO, 8), 9)[:2]
    elegidos = pd.DataFrame(
        {
            "modelo": ["mclp", "mclp", "p_mediana"],
            "k": [5, 5, 5],
            "h3": [hijo_a, hijo_b, LEJOS],
        }
    )
    assert sitios_mclp(elegidos) == {"5": [h3.cell_to_parent(CENTRO, 8)]}


def test_curva_solo_highs() -> None:
    curva = pd.DataFrame(
        {
            "modelo": ["mclp", "mclp", "mclp"],
            "metodo": ["highs", "voraz", "highs"],
            "k": [100, 100, 1],
            "poblacion_cubierta": [500, 400, 10],
            "proporcion_region_en_desierto": [0.038, 0.04, 0.058],
        }
    )
    assert curva_mclp(curva) == [[1, 10, 5.8], [100, 500, 3.8]]


def test_pagina_reemplaza_una_vez_y_escapa_cierre_de_script() -> None:
    datos: Any = {"comunas": [{"comuna": "</script><b>"}]}
    html = pagina(datos, f"<script>const DATOS = {MARCA};</script>")
    assert html.count("</script>") == 1
    assert "<\\/script>" in html
    with pytest.raises(ErrorDatos):
        pagina(datos, "sin marca")


# Banco sintético completo para construir_datos y escribir_visor.


def _hipotesis(h1_efecto: float) -> pd.DataFrame:
    filas = [
        ("H1", h1_efecto, h1_efecto - 3, h1_efecto + 3, 0.0, True),
        ("H2", 0.84, 0.78, 0.93, 1.0, False),
        ("H3", 0.897, None, None, 0.002, True),
    ]
    return pd.DataFrame(
        [
            {
                "caso": "principal",
                "umbral_min": UMBRAL,
                "bloque": 6,
                "hipotesis": h,
                "efecto": e,
                "ic_inf": li,
                "ic_sup": ls,
                "p": 0.0,
                "nulo": 0.0,
                "p_holm": p,
                "se_sostiene": s,
            }
            for h, e, li, ls, p, s in filas
        ]
    )


def _banco(tmp_path: Path, h1_efecto: float | None = None, con_nombres: bool = True) -> Path:
    d = tmp_path / "derivados"
    for sub in ("accesibilidad", "localizacion", "exploratorio"):
        (d / sub).mkdir(parents=True)
    celdas = _celdas()
    # Una celda rural en desierto para Las Condes, para que toda comuna tenga dónde rotularse.
    otra = h3.latlng_to_cell(-33.30, -70.40, 9)
    lat, lon = h3.cell_to_latlng(otra)
    extra = {"h3": otra, "cut": 13114, "n_per": 60.0, "rural": True, "minutos": 40.0}
    extra |= {"censurada": False, "gi_clase": "ninguno", "lisa": "no_significativo"}
    celdas = pd.concat(
        [celdas, pd.DataFrame([extra | {"lat": lat, "lon": lon}])], ignore_index=True
    )
    celdas[["h3", "cut", "n_per", "rural", "lat", "lon"]].to_parquet(d / "poblacion_h3_r9.parquet")
    celdas[["h3", "minutos", "censurada"]].to_parquet(d / "accesibilidad" / "a_pie_r9.parquet")
    celdas[["h3", "cut", "gi_clase", "lisa"]].to_parquet(d / "agrupamientos_r9.parquet")
    des = float(celdas.loc[celdas["minutos"] > UMBRAL, "n_per"].sum())
    (d / "accesibilidad_registro.json").write_text(
        json.dumps(
            {"tope_min": 120, "escenarios": {"a_pie_r9": {"poblacion_sobre_15_min": round(des)}}}
        ),
        encoding="utf-8",
    )
    rural = 100.0
    urbano = 409.0 / sum(400.0 + i for i in range(10)) * 100
    efecto = rural - urbano if h1_efecto is None else h1_efecto
    _hipotesis(efecto).to_csv(d / "hipotesis_resultados.csv", index=False)
    (d / "hipotesis_registro.json").write_text(
        json.dumps({"replicas_bootstrap": 2000}), encoding="utf-8"
    )
    pd.DataFrame(
        {
            "modelo": ["mclp", "mclp"],
            "metodo": ["highs", "highs"],
            "k": [10, 100],
            "poblacion_cubierta": [30, 39],
            "proporcion_region_en_desierto": [0.05, 0.0],
        }
    ).to_csv(d / "localizacion" / "curva.csv", index=False)
    pd.DataFrame({"modelo": ["mclp", "mclp"], "k": [10, 100], "h3": [LEJOS, LEJOS]}).to_csv(
        d / "localizacion" / "elegidos.csv", index=False
    )
    comunas = pd.DataFrame(
        {
            "cut": [13101, 13401, 13114],
            "nombre": ["SANTIAGO", "SAN BERNARDO", "LAS CONDES"],
            "perfil_nombre": [POPULAR, PERIURBANA, ORIENTE],
            "poblacion": [4045.0, 39.0, 10.0],
            "prop_desierto": [0.1, 1.0, 0.0],
            "minutos_medios": [5.0, 40.0, 3.0],
            "prop_rural": [0.0, 1.0, 0.0],
            "puntos_10k": [20.0, 0.0, 30.0],
            "caja_vecina_10k": [15.0, 0.0, 10.0],
            "sucursales_10k": [1.5, 0.0, 3.0],
            "cajeros_10k": [8.0, 0.0, 12.0],
            "ing_tasa": [0.10, 0.17, 0.02],
            "mul_tasa": [0.18, 0.25, 0.05],
        }
    )
    if not con_nombres:
        comunas = comunas.drop(columns=["perfil_nombre"])
    comunas.to_csv(d / "exploratorio" / "comunas.csv", index=False)
    return d


def test_construir_datos_lee_todo_de_los_derivados(tmp_path: Path) -> None:
    datos = construir_datos(_banco(tmp_path), UMBRAL, _referencias())
    r = datos["resumen"]
    assert r["rural"] == 100.0
    assert r["des_rural"] == pytest.approx(102 / 511 * 100, abs=0.05)
    assert r["sostiene"] == {"H1": True, "H2": False, "H3": True}
    assert r["p_holm"]["H3"] == 0.002
    assert r["replicas"] == 2000 and r["tope_min"] == 120 and r["min_personas"] == MIN_PERSONAS
    assert [c["comuna"] for c in datos["comunas"]] == ["Santiago", "San Bernardo", "Las Condes"]
    assert [c["pc"] for c in datos["comunas"]] == [0, 1, 2]
    assert datos["sitios"] == {
        "10": [h3.cell_to_parent(LEJOS, 8)],
        "100": [h3.cell_to_parent(LEJOS, 8)],
    }


def test_resumen_que_no_reproduce_h1_falla(tmp_path: Path) -> None:
    with pytest.raises(ErrorDatos, match="H1"):
        construir_datos(_banco(tmp_path, h1_efecto=50.0), UMBRAL, _referencias())


def test_comunas_sin_nombre_de_perfil_piden_el_exploratorio(tmp_path: Path) -> None:
    with pytest.raises(ErrorDatos, match="exploratorio"):
        construir_datos(_banco(tmp_path, con_nombres=False), UMBRAL, _referencias())


def test_escribir_visor_es_determinista_y_sin_cdn(tmp_path: Path) -> None:
    datos = construir_datos(_banco(tmp_path), UMBRAL, _referencias())
    a = escribir_visor(datos, tmp_path / "a")
    b = escribir_visor(datos, tmp_path / "b")
    assert a == b
    assert set(a) == {"index.html", "datos.json", *(f"vendor/{n}" for n in VENDOR)}
    html = (tmp_path / "a" / "index.html").read_text(encoding="utf-8")
    assert MARCA not in html
    assert "cdnjs" not in html and "jsdelivr" not in html and "googleapis" not in html
    assert 'src="vendor/d3.min.js"' in html and 'src="vendor/h3-js.umd.js"' in html
    for nombre in ("d3.min.js", "h3-js.umd.js"):
        cuerpo = (tmp_path / "a" / "vendor" / nombre).read_bytes()
        sri = "sha384-" + base64.b64encode(hashlib.sha384(cuerpo).digest()).decode()
        assert f'src="vendor/{nombre}" integrity="{sri}"' in html
    for nombre, huella in VENDOR.items():
        cuerpo = (tmp_path / "a" / "vendor" / nombre).read_bytes()
        assert hashlib.sha256(cuerpo).hexdigest() == huella
    incrustado = json.loads((tmp_path / "a" / "datos.json").read_text(encoding="utf-8"))
    assert incrustado["resumen"]["umbral_min"] == UMBRAL
