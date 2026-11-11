"""Línea de comandos: python -m desiertos <orden>."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from desiertos import CRS_METRICO_RM, RESOLUCION_ANALISIS
from desiertos.accesibilidad import Escenario, pares_a_pie, por_tramos
from desiertos.completitud import (
    asignar_comuna,
    conteo_localizadores_por_comuna,
    conteo_osm_por_comuna,
    evaluar_completitud,
    evaluar_por_banco,
)
from desiertos.comunal import leer_sae, tabla_comunal
from desiertos.errores import ErrorDatos, ErrorDesiertos
from desiertos.exploratorio import agrupamientos
from desiertos.geocodificacion import Geocodificador
from desiertos.grilla import pesos_dasimetricos, poblacion_por_celda
from desiertos.hipotesis import (
    REPLICAS,
    SEMILLA,
    bootstrap_por_bloques,
    holm,
    moran_log_tiempo,
    moran_valores,
    residuos,
)
from desiertos.ingesta.bancoestado import FUENTES, leer_red
from desiertos.ingesta.censo import leer_unidades
from desiertos.ingesta.cmf import leer_conteos_por_institucion_rm, leer_conteos_rm
from desiertos.ingesta.coordenadas import huellas_comunales
from desiertos.ingesta.localizadores import (
    leer_bci,
    leer_falabella,
    leer_scotiabank,
    separar_numero,
)
from desiertos.ingesta.osm import CAJA_RECORTE, extraer_edificios, extraer_referencias, recortar
from desiertos.localizacion import mclp, mclp_voraz, p_mediana
from desiertos.modelos import (
    clasificacion,
    densidad_kernel,
    nombrar_perfiles,
    perfiles,
    regresion_espacial,
    reserva_federal,
)
from desiertos.procedencia import sha256_archivo, verificar
from desiertos.puntos import METODOS_ACEPTADOS, METODOS_SENSIBILIDAD, unir_puntos
from desiertos.rutas import Rutas, cargar_rutas, raiz_repositorio
from desiertos.visor import ARCHIVOS_ENTRADA, construir_datos, escribir_visor

REGION_RM = 13
RESOLUCION_SENSIBILIDAD = 8


def _escribir_registro(destino: Path, contenido: dict[str, Any]) -> None:
    contenido = {"generado": datetime.now(UTC).isoformat(timespec="seconds"), **contenido}
    destino.write_text(json.dumps(contenido, ensure_ascii=False, indent=2), encoding="utf-8")


def orden_poblacion(rutas: Rutas) -> dict[str, Any]:
    huella = verificar(rutas.censo_zip)
    unidades = leer_unidades(rutas.censo_zip)
    rutas.derivados.mkdir(parents=True, exist_ok=True)
    registro: dict[str, Any] = {
        "original": {"archivo": rutas.censo_zip.name, "sha256": huella},
        "unidades": len(unidades),
        "unidades_rurales": int((unidades["area"] == "RURAL").sum()),
        "unidades_sin_60_mas": int(unidades["n_60_mas"].isna().sum()),
        "poblacion_unidades": float(unidades["n_per"].sum()),
        "resoluciones": {},
    }
    for res in (RESOLUCION_ANALISIS, RESOLUCION_SENSIBILIDAD):
        celdas = poblacion_por_celda(unidades, res)
        salida = rutas.derivados / f"poblacion_h3_r{res}.parquet"
        celdas.to_parquet(salida, index=False)
        registro["resoluciones"][str(res)] = {
            "archivo": salida.name,
            "sha256": sha256_archivo(salida),
            "celdas_pobladas": len(celdas),
            "celdas_rurales": int(celdas["rural"].sum()),
            "poblacion_en_celdas_pobladas": float(celdas["n_per"].sum()),
            "poblacion_60_mas": float(celdas["n_60_mas"].sum()),
        }
    _escribir_registro(rutas.derivados / "poblacion_registro.json", registro)
    return registro


def orden_red_bancoestado(rutas: Rutas) -> dict[str, Any]:
    huellas = {f.archivo: verificar(rutas.bancoestado / f.archivo) for f in FUENTES}
    huella_censo = verificar(rutas.censo_zip)
    unidades = leer_unidades(rutas.censo_zip)
    red = leer_red(rutas.bancoestado, REGION_RM, unidades)
    rutas.derivados.mkdir(parents=True, exist_ok=True)
    salida = rutas.derivados / "red_bancoestado_rm.parquet"
    cola = rutas.derivados / "red_bancoestado_rm_a_geocodificar.parquet"
    red.aceptados.to_parquet(salida, index=False)
    red.cola_geocodificacion.to_parquet(cola, index=False)
    registro: dict[str, Any] = {
        "uso": "interno; no se publica la lista de puntos (enmienda E-1)",
        "regla_coordenadas": "enmienda E-3",
        "originales": {**huellas, rutas.censo_zip.name: huella_censo},
        "region": REGION_RM,
        "resumen": [{**asdict(r), "tipo": r.tipo.value} for r in red.resumenes],
        "motivos_cola": red.cola_geocodificacion["motivo"].value_counts().to_dict(),
        "aceptados": {
            "archivo": salida.name,
            "sha256": sha256_archivo(salida),
            "puntos": len(red.aceptados),
        },
        "a_geocodificar": {
            "archivo": cola.name,
            "sha256": sha256_archivo(cola),
            "puntos": len(red.cola_geocodificacion),
        },
    }
    _escribir_registro(rutas.derivados / "red_bancoestado_registro.json", registro)
    return registro


PERIODO_CMF = (2026, "Ago")


def orden_completitud(rutas: Rutas) -> dict[str, Any]:
    huella_cmf = verificar(rutas.cmf_zip)
    huella_censo = verificar(rutas.censo_zip)
    if not rutas.osm_financieros.is_file():
        raise ErrorDatos(f"Falta el derivado {rutas.osm_financieros}")
    cmf = leer_conteos_rm(rutas.cmf_zip, *PERIODO_CMF)
    huellas = huellas_comunales(leer_unidades(rutas.censo_zip))
    osm = conteo_osm_por_comuna(gpd.read_parquet(rutas.osm_financieros), huellas)
    tabla = evaluar_completitud(cmf, osm)
    rutas.derivados.mkdir(parents=True, exist_ok=True)
    salida = rutas.derivados / "completitud_osm_cmf_rm.csv"
    tabla.to_csv(salida, index=False, encoding="utf-8")
    registro: dict[str, Any] = {
        "regla": "P4 del protocolo",
        "periodo_cmf": f"{PERIODO_CMF[0]}-{PERIODO_CMF[1]}",
        "originales": {
            rutas.cmf_zip.name: huella_cmf,
            rutas.censo_zip.name: huella_censo,
            rutas.osm_financieros.name: sha256_archivo(rutas.osm_financieros),
        },
        "comunas": len(tabla),
        "comunas_aptas": int(tabla["apta"].sum()),
        "totales": {
            c: int(tabla[c].sum()) for c in ("cmf_sucursales", "osm_bank", "cmf_cajeros", "osm_atm")
        },
        "salida": {"archivo": salida.name, "sha256": sha256_archivo(salida)},
    }
    _escribir_registro(rutas.derivados / "completitud_registro.json", registro)
    return registro


PAGINA_FALABELLA = "falabella/falabella_oficinas_20261110.html"
PAGINA_SCOTIABANK = "scotiabank/scotiabank_sucursales_20261110.html"


def _derivado(ruta: Path) -> str:
    if not ruta.is_file():
        raise ErrorDatos(f"Falta el derivado {ruta}")
    return sha256_archivo(ruta)


def orden_localizadores(rutas: Rutas) -> dict[str, Any]:
    huella_cmf = verificar(rutas.cmf_zip)
    huella_censo = verificar(rutas.censo_zip)
    huellas_osm = {r.name: _derivado(r) for r in (rutas.osm_direcciones, rutas.osm_calles)}
    huellas = huellas_comunales(leer_unidades(rutas.censo_zip))
    bci = leer_bci(rutas.localizadores / "bci")
    falabella = leer_falabella(rutas.localizadores / PAGINA_FALABELLA)
    scotia = leer_scotiabank(rutas.localizadores / PAGINA_SCOTIABANK)
    scotia = scotia[scotia["region_rm"]].copy()
    geo = Geocodificador(
        gpd.read_parquet(rutas.osm_direcciones), gpd.read_parquet(rutas.osm_calles), huellas
    )
    metodos = []
    puntos = []
    for direccion, comuna in zip(scotia["direccion"], scotia["comuna"], strict=True):
        calle, numero = separar_numero(direccion)
        r = geo.geocodificar(calle, numero, comuna)
        metodos.append(r.metodo.value)
        puntos.append((r.lon, r.lat))
    scotia["metodo"] = metodos
    scotia = scotia.set_geometry(gpd.points_from_xy(*zip(*puntos, strict=True)), crs=bci.crs)
    scotia["origen_coordenada"] = "geocodificada_" + scotia["metodo"]
    for capa in (bci, falabella):
        capa["metodo"] = "original"
        capa["origen_coordenada"] = "original"
    aceptada = scotia["metodo"].isin(METODOS_ACEPTADOS)
    capa = gpd.GeoDataFrame(
        pd.concat([bci, falabella, scotia[aceptada]], ignore_index=True), crs=bci.crs
    )
    capa = capa[capa.geometry.notna() & ~capa.geometry.is_empty]
    dentro = asignar_comuna(capa, huellas)
    capa = capa.loc[sorted(set(dentro.index))].reset_index(drop=True)
    conteo = conteo_localizadores_por_comuna(capa, huellas)
    cmf = leer_conteos_por_institucion_rm(rutas.cmf_zip, *PERIODO_CMF)
    por_banco = evaluar_por_banco(cmf, conteo)
    rutas.derivados.mkdir(parents=True, exist_ok=True)
    salida = rutas.derivados / "localizadores_rm.parquet"
    tabla = rutas.derivados / "completitud_localizadores_rm.csv"
    capa.to_parquet(salida, index=False)
    por_banco.to_csv(tabla, index=False, encoding="utf-8")
    totales = por_banco.groupby("banco")[
        ["cmf_sucursales", "loc_sucursales", "cmf_cajeros", "loc_cajeros"]
    ].sum()
    registro: dict[str, Any] = {
        "uso": "interno; no se publica la lista de puntos (enmienda E-4)",
        "originales": {rutas.cmf_zip.name: huella_cmf, rutas.censo_zip.name: huella_censo},
        "derivados_usados": huellas_osm,
        "scotiabank_metodos": scotia["metodo"].value_counts().to_dict(),
        "scotiabank_aceptadas": int(aceptada.sum()),
        "puntos_en_rm": capa.groupby(["banco", "tipo"])
        .size()
        .rename("n")
        .reset_index()
        .to_dict("records"),
        "totales_rm": {b: {k: int(v) for k, v in fila.items()} for b, fila in totales.iterrows()},
        "comunas_en_rango": {
            b: {
                "sucursales": int(g["sucursales_en_rango"].sum()),
                "cajeros": int(g["cajeros_en_rango"].sum()),
                "con_sucursal_cmf": int((g["cmf_sucursales"] > 0).sum()),
                "con_cajero_cmf": int((g["cmf_cajeros"] > 0).sum()),
            }
            for b, g in por_banco.groupby("banco")
        },
        "salidas": {
            salida.name: sha256_archivo(salida),
            tabla.name: sha256_archivo(tabla),
        },
    }
    _escribir_registro(rutas.derivados / "localizadores_registro.json", registro)
    return registro


def orden_puntos(rutas: Rutas) -> dict[str, Any]:
    entradas = {
        "red": rutas.derivados / "red_bancoestado_rm.parquet",
        "cola": rutas.derivados / "cola_geocodificada.parquet",
        "osm": rutas.osm_financieros,
        "localizadores": rutas.derivados / "localizadores_rm.parquet",
    }
    huellas_entrada = {r.name: _derivado(r) for r in entradas.values()}
    capas = {k: gpd.read_parquet(r) for k, r in entradas.items()}
    registro: dict[str, Any] = {
        "regla": "enmiendas E-1, E-3 y E-4",
        "entradas": huellas_entrada,
        "salidas": {},
    }
    for nombre, metodos in (
        ("puntos_rm", METODOS_ACEPTADOS),
        ("puntos_rm_sensibilidad", METODOS_SENSIBILIDAD),
    ):
        puntos = unir_puntos(
            capas["red"], capas["cola"], capas["osm"], metodos, capas["localizadores"]
        )
        salida = rutas.derivados / f"{nombre}.parquet"
        puntos.to_parquet(salida, index=False)
        registro["salidas"][salida.name] = {
            "sha256": sha256_archivo(salida),
            "puntos": len(puntos),
            "por_tipo": puntos["tipo"].value_counts().to_dict(),
        }
    _escribir_registro(rutas.derivados / "puntos_registro.json", registro)
    return registro


def orden_poblacion_dasimetrica(rutas: Rutas) -> dict[str, Any]:
    """Sensibilidad de la enmienda E-6: población rural repartida según edificios de OSM."""
    huella_censo = verificar(rutas.censo_zip)
    huella_osm = _derivado(rutas.osm_rm)
    unidades = leer_unidades(rutas.censo_zip)
    edificios = extraer_edificios(rutas.osm_rm)
    pesos = pesos_dasimetricos(unidades, edificios, RESOLUCION_ANALISIS)
    celdas = poblacion_por_celda(unidades, RESOLUCION_ANALISIS, pesos)
    salida = rutas.derivados / f"poblacion_h3_r{RESOLUCION_ANALISIS}_dasimetrica.parquet"
    celdas.to_parquet(salida, index=False)
    rurales = unidades[unidades["area"] == "RURAL"]
    dentro = gpd.sjoin(
        edificios[["geometry"]],
        rurales[["manzent", "geometry"]].to_crs(edificios.crs),
        how="inner",
        predicate="within",
    )
    con_edificios = rurales["manzent"].isin(set(dentro["manzent"]))
    registro: dict[str, Any] = {
        "regla": "enmienda E-6 (sensibilidad; el método principal es el sellado)",
        "originales": {rutas.censo_zip.name: huella_censo},
        "derivados_usados": {rutas.osm_rm.name: huella_osm},
        "edificios_osm": len(edificios),
        "edificios_en_entidades_rurales": len(dentro),
        "entidades_rurales": len(rurales),
        "entidades_rurales_con_edificios": int(con_edificios.sum()),
        "poblacion_rural_en_entidades_con_edificios": round(
            float(rurales.loc[con_edificios, "n_per"].sum())
        ),
        "poblacion_rural": round(float(rurales["n_per"].sum())),
        "celdas_pobladas": len(celdas),
        "salida": {"archivo": salida.name, "sha256": sha256_archivo(salida)},
    }
    _escribir_registro(rutas.derivados / "poblacion_dasimetrica_registro.json", registro)
    return registro


def orden_recorte_osm(rutas: Rutas) -> dict[str, Any]:
    huella = verificar(rutas.osm_chile)
    conteo = recortar(rutas.osm_chile, rutas.osm_rm, CAJA_RECORTE)
    registro: dict[str, Any] = {
        "original": {"archivo": rutas.osm_chile.name, "sha256": huella},
        "caja": list(CAJA_RECORTE),
        "regla": "nodos dentro de la caja y ways con al menos un nodo dentro; sin relaciones",
        **conteo,
        "salida": {"archivo": rutas.osm_rm.name, "sha256": sha256_archivo(rutas.osm_rm)},
    }
    _escribir_registro(rutas.derivados / "osm" / "recorte_registro.json", registro)
    return registro


# Enmienda E-5. Martes hábil dentro de la vigencia del GTFS (2026-10-03 a 2026-12-31).
DIA_CALCULO = dt.date(2026, 11, 17)
TOPE_MIN = 120
TOPE_CORTO_MIN = 30
UMBRALES_MIN = (10, 15, 20)


def _escenarios() -> list[tuple[Escenario, str, str]]:
    """(escenario, archivo de puntos, resolución) en el orden de cálculo."""
    diez = dt.datetime.combine(DIA_CALCULO, dt.time(10, 0))
    siete = dt.datetime.combine(DIA_CALCULO, dt.time(7, 0))
    return [
        (Escenario("a_pie", "a_pie", TOPE_MIN, 3.6, diez), "puntos_rm", "r9"),
        (Escenario("a_pie_48", "a_pie", TOPE_MIN, 4.8, diez), "puntos_rm", "r9"),
        (
            Escenario("a_pie_sens_puntos", "a_pie", TOPE_MIN, 3.6, diez),
            "puntos_rm_sensibilidad",
            "r9",
        ),
        (Escenario("a_pie", "a_pie", TOPE_MIN, 3.6, diez), "puntos_rm", "r8"),
        # Enmienda E-6: sensibilidad dasimétrica (grilla r9d) y auto y transporte público en r8.
        (Escenario("a_pie", "a_pie", TOPE_MIN, 3.6, diez), "puntos_rm", "r9d"),
        # Evidencia para aplicar la sección 2.2 del protocolo: el indicador sin puntos de OSM.
        (Escenario("a_pie_sin_osm", "a_pie", TOPE_MIN, 3.6, diez), "puntos_rm_sin_osm", "r9"),
        (Escenario("auto", "auto", TOPE_MIN, 3.6, diez), "puntos_rm", "r8"),
        (Escenario("tp_10", "transporte_publico", TOPE_MIN, 3.6, diez, 60), "puntos_rm", "r8"),
        (Escenario("tp_07", "transporte_publico", TOPE_MIN, 3.6, siete, 60), "puntos_rm", "r8"),
    ]


def _resumen(celdas: pd.DataFrame, tiempos: pd.DataFrame) -> dict[str, Any]:
    tabla = celdas[["h3", "n_per", "rural"]].merge(tiempos, on="h3")
    total = float(tabla["n_per"].sum())
    salida: dict[str, Any] = {
        "celdas": len(tabla),
        "censuradas": int(tabla["censurada"].sum()),
        "poblacion_censurada": round(float(tabla.loc[tabla["censurada"], "n_per"].sum())),
        "mediana_ponderada_min": float(
            tabla.sort_values("minutos")
            .assign(acum=lambda t: t["n_per"].cumsum() / total)
            .query("acum >= 0.5")["minutos"]
            .iloc[0]
        ),
    }
    for umbral in UMBRALES_MIN:
        desierto = tabla["minutos"] > umbral
        salida[f"poblacion_sobre_{umbral}_min"] = round(float(tabla.loc[desierto, "n_per"].sum()))
        salida[f"proporcion_sobre_{umbral}_min"] = round(
            float(tabla.loc[desierto, "n_per"].sum()) / total, 4
        )
    return salida


def orden_accesibilidad(rutas: Rutas, solo: set[str] | None = None) -> dict[str, Any]:
    """Calcula los escenarios que falten (o los de `solo`), uno por archivo, y luego los une.

    Cada escenario se guarda apenas termina en derivados/desiertos/accesibilidad/, de modo que una
    interrupción no pierde lo ya calculado y la orden se puede repetir.
    """
    from desiertos.motor_r5 import calculador, red_de_transporte

    huella_gtfs = verificar(rutas.gtfs_zip)
    entradas = {
        "osm_rm": rutas.osm_rm,
        "r9": rutas.derivados / "poblacion_h3_r9.parquet",
        "r8": rutas.derivados / "poblacion_h3_r8.parquet",
        "r9d": rutas.derivados / "poblacion_h3_r9_dasimetrica.parquet",
        "puntos_rm": rutas.derivados / "puntos_rm.parquet",
        "puntos_rm_sensibilidad": rutas.derivados / "puntos_rm_sensibilidad.parquet",
    }
    huellas = {k: _derivado(r) for k, r in entradas.items()}
    carpeta = rutas.derivados / "accesibilidad"
    carpeta.mkdir(parents=True, exist_ok=True)
    escenarios = _escenarios()
    conocidos = {f"{e.nombre}_{res}" for e, _, res in escenarios}
    if solo is not None and solo - conocidos:
        raise ErrorDatos(f"Escenarios desconocidos: {sorted(solo - conocidos)}")
    pendientes = [
        (e, capa, res)
        for e, capa, res in escenarios
        if (solo is None or f"{e.nombre}_{res}" in solo)
        and not (carpeta / f"{e.nombre}_{res}.parquet").is_file()
    ]
    celdas = {r: pd.read_parquet(entradas[r]) for r in ("r9", "r8", "r9d")}
    if pendientes:
        puntos = {p: gpd.read_parquet(entradas[p]) for p in ("puntos_rm", "puntos_rm_sensibilidad")}
        puntos["puntos_rm_sin_osm"] = puntos["puntos_rm"][puntos["puntos_rm"]["fuente"] != "osm"]
        calcular = calculador(red_de_transporte(rutas.osm_rm, [rutas.gtfs_zip]))
        for escenario, capa, res in pendientes:
            inicio = datetime.now(UTC)
            tiempos = por_tramos(celdas[res], puntos[capa], escenario, calcular, TOPE_CORTO_MIN)
            tiempos["segundos"] = round((datetime.now(UTC) - inicio).total_seconds())
            tiempos["puntos"] = capa
            tiempos.to_parquet(carpeta / f"{escenario.nombre}_{res}.parquet", index=False)
            print(f"{escenario.nombre}_{res} listo", flush=True)
    resumenes: dict[str, Any] = {}
    salidas: dict[str, str] = {}
    for res in ("r9", "r8", "r9d"):
        tabla = pd.DataFrame({"h3": celdas[res]["h3"]})
        for escenario, _, r in escenarios:
            archivo = carpeta / f"{escenario.nombre}_{r}.parquet"
            if r != res or not archivo.is_file():
                continue
            tiempos = pd.read_parquet(archivo)
            resumen = _resumen(celdas[res], tiempos[["h3", "minutos", "censurada"]])
            resumen["segundos"] = int(tiempos["segundos"].iloc[0])
            resumen["puntos"] = str(tiempos["puntos"].iloc[0])
            resumen["cota_superior"] = escenario.modo != "a_pie"
            resumen["archivo"] = {"nombre": archivo.name, "sha256": sha256_archivo(archivo)}
            resumenes[f"{escenario.nombre}_{res}"] = resumen
            tabla = tabla.merge(
                tiempos[["h3", "minutos", "censurada"]].rename(
                    columns={
                        "minutos": escenario.nombre,
                        "censurada": f"{escenario.nombre}_censurada",
                    }
                ),
                on="h3",
            )
        salida = rutas.derivados / f"accesibilidad_{res}.parquet"
        tabla.to_parquet(salida, index=False)
        salidas[salida.name] = sha256_archivo(salida)
    registro: dict[str, Any] = {
        "regla": "protocolo y enmienda E-5",
        "dia": DIA_CALCULO.isoformat(),
        "tope_min": TOPE_MIN,
        "entradas": {**huellas, rutas.gtfs_zip.name: huella_gtfs},
        "escenarios": resumenes,
        "faltan": sorted(conocidos - set(resumenes)),
        "salidas": salidas,
    }
    _escribir_registro(rutas.derivados / "accesibilidad_registro.json", registro)
    return registro


# Protocolo, secciones 5 y 6, y enmiendas E-2, E-6 y E-7.
UMBRAL_PRINCIPAL = 15.0
BLOQUE_PRINCIPAL = 6
# (nombre, archivo de población, archivo de tiempos, umbral, resolución del bloque)
CASOS_HIPOTESIS: list[tuple[str, str, str, float, int]] = [
    ("principal", "poblacion_h3_r9.parquet", "a_pie_r9.parquet", 15.0, 6),
    ("umbral_10", "poblacion_h3_r9.parquet", "a_pie_r9.parquet", 10.0, 6),
    ("umbral_20", "poblacion_h3_r9.parquet", "a_pie_r9.parquet", 20.0, 6),
    ("bloque_r5", "poblacion_h3_r9.parquet", "a_pie_r9.parquet", 15.0, 5),
    ("a_pie_48", "poblacion_h3_r9.parquet", "a_pie_48_r9.parquet", 15.0, 6),
    ("puntos_sensibilidad", "poblacion_h3_r9.parquet", "a_pie_sens_puntos_r9.parquet", 15.0, 6),
    ("sin_osm", "poblacion_h3_r9.parquet", "a_pie_sin_osm_r9.parquet", 15.0, 6),
    ("resolucion_8", "poblacion_h3_r8.parquet", "a_pie_r8.parquet", 15.0, 6),
    ("dasimetrica", "poblacion_h3_r9_dasimetrica.parquet", "a_pie_r9d.parquet", 15.0, 6),
]


def orden_hipotesis(rutas: Rutas) -> dict[str, Any]:
    filas: list[dict[str, Any]] = []
    huellas: dict[str, str] = {}
    principal: pd.DataFrame | None = None
    for nombre, poblacion, tiempos, umbral, bloque in CASOS_HIPOTESIS:
        ruta_p = rutas.derivados / poblacion
        ruta_t = rutas.derivados / "accesibilidad" / tiempos
        huellas[ruta_p.name] = _derivado(ruta_p)
        huellas[ruta_t.name] = _derivado(ruta_t)
        tabla = pd.read_parquet(ruta_p).merge(pd.read_parquet(ruta_t), on="h3", validate="1:1")
        h1, h2 = bootstrap_por_bloques(tabla, umbral, bloque)
        h3r = moran_log_tiempo(tabla)
        for r in (h1, h2, h3r):
            filas.append({"caso": nombre, "umbral_min": umbral, "bloque": bloque, **asdict(r)})
        if nombre == "principal":
            principal = tabla
            sin_censura = tabla[~tabla["censurada"]]
            r = moran_log_tiempo(sin_censura)
            filas.append(
                {"caso": "sin_censuradas", "umbral_min": umbral, "bloque": bloque, **asdict(r)}
            )
        print(f"{nombre} listo", flush=True)
    resultados = pd.DataFrame(filas)
    es_principal = resultados["caso"] == "principal"
    ajuste = holm(
        dict(
            zip(
                resultados.loc[es_principal, "hipotesis"],
                resultados.loc[es_principal, "p"],
                strict=True,
            )
        )
    )
    resultados["p_holm"] = [
        ajuste[h][0] if c == "principal" else float("nan")
        for c, h in zip(resultados["caso"], resultados["hipotesis"], strict=True)
    ]
    resultados["se_sostiene"] = [
        (ajuste[h][1] and (e > n)) if c == "principal" else None
        for c, h, e, n in zip(
            resultados["caso"],
            resultados["hipotesis"],
            resultados["efecto"],
            resultados["nulo"],
            strict=True,
        )
    ]
    if principal is None:
        raise ErrorDatos("Falta el caso principal")
    r1, r2 = residuos(principal, UMBRAL_PRINCIPAL)
    salida = rutas.derivados / "hipotesis_resultados.csv"
    resultados.to_csv(salida, index=False, encoding="utf-8")
    registro: dict[str, Any] = {
        "regla": "protocolo, secciones 5 y 6; enmiendas E-2, E-6 y E-7",
        "semilla": SEMILLA,
        "replicas_bootstrap": REPLICAS,
        "entradas": huellas,
        "holm": {h: {"p_ajustado": a, "rechaza_nulo": d} for h, (a, d) in ajuste.items()},
        "diagnostico_moran_residuos": {
            "H1": moran_valores(principal, r1),
            "H2": moran_valores(principal, r2),
        },
        "salida": {"archivo": salida.name, "sha256": sha256_archivo(salida)},
    }
    _escribir_registro(rutas.derivados / "hipotesis_registro.json", registro)
    return registro


# Escenarios de localización (sección 7; exploratorio).
K_COBERTURA = (1, 5, 10, 25, 50, 100, 200, 400)
K_MEDIANA = (10, 25, 50, 100)
POBLACION_MINIMA_CANDIDATO = 10.0
TOPE_PARES_MIN = 60


def orden_localizacion(rutas: Rutas) -> dict[str, Any]:
    """MCLP exacto y voraz, y p-mediana, sobre la demanda en desierto del caso principal."""
    ruta_p = rutas.derivados / "poblacion_h3_r9.parquet"
    ruta_t = rutas.derivados / "accesibilidad" / "a_pie_r9.parquet"
    huellas = {r.name: _derivado(r) for r in (ruta_p, ruta_t, rutas.osm_rm)}
    tabla = pd.read_parquet(ruta_p).merge(pd.read_parquet(ruta_t), on="h3", validate="1:1")
    total = float(tabla["n_per"].sum())
    demanda = tabla[tabla["minutos"] > UMBRAL_PRINCIPAL].reset_index(drop=True)
    candidatos = demanda[demanda["n_per"] >= POBLACION_MINIMA_CANDIDATO].reset_index(drop=True)
    carpeta = rutas.derivados / "localizacion"
    carpeta.mkdir(parents=True, exist_ok=True)
    archivo_pares = carpeta / f"pares_a_pie_{TOPE_PARES_MIN}.parquet"
    if not archivo_pares.is_file():
        from desiertos.motor_r5 import calculador, red_de_transporte

        calcular = calculador(red_de_transporte(rutas.osm_rm, [rutas.gtfs_zip]))
        escenario = Escenario(
            "pares", "a_pie", TOPE_PARES_MIN, 3.6, dt.datetime.combine(DIA_CALCULO, dt.time(10))
        )
        pares_a_pie(demanda, candidatos, escenario, calcular).to_parquet(archivo_pares, index=False)
        print("pares listos", flush=True)
    pares = pd.read_parquet(archivo_pares)
    pesos = demanda.set_index("h3")["n_per"]
    poblacion_desierto = float(pesos.sum())
    curva: list[dict[str, Any]] = []
    elegidos: list[dict[str, Any]] = []
    for k in K_COBERTURA:
        exacta = mclp(pesos, pares, k, UMBRAL_PRINCIPAL)
        voraz = mclp_voraz(pesos, pares, k, UMBRAL_PRINCIPAL)
        for sol in (exacta, voraz):
            curva.append(
                {
                    "modelo": "mclp",
                    "metodo": sol.metodo,
                    "k": k,
                    "poblacion_cubierta": round(sol.cubierta),
                    "proporcion_desierto_cubierta": sol.cubierta / poblacion_desierto,
                    "proporcion_region_en_desierto": (poblacion_desierto - sol.cubierta) / total,
                    "brecha": sol.brecha,
                }
            )
        elegidos += [{"modelo": "mclp", "k": k, "h3": h} for h in exacta.elegidos]
        print(f"mclp k={k} listo", flush=True)
    actual = pesos.index.to_series().map(demanda.set_index("h3")["minutos"])
    base = float((pesos * actual).sum())
    for k in K_MEDIANA:
        lista, valor = p_mediana(pesos, actual, pares, k)
        nuevo = actual.copy()
        for h in lista:
            sub = pares[pares["h3_candidato"] == h].set_index("h3_origen")["minutos"]
            nuevo.loc[sub.index] = np.minimum(nuevo.loc[sub.index], sub)
        sigue = float(pesos[nuevo > UMBRAL_PRINCIPAL].sum())
        curva.append(
            {
                "modelo": "p_mediana",
                "metodo": "voraz_intercambio",
                "k": k,
                "minutos_medios_antes": base / poblacion_desierto,
                "minutos_medios_despues": valor / poblacion_desierto,
                "poblacion_cubierta": round(poblacion_desierto - sigue),
                "proporcion_region_en_desierto": sigue / total,
            }
        )
        elegidos += [{"modelo": "p_mediana", "k": k, "h3": h} for h in lista]
        print(f"p-mediana k={k} listo", flush=True)
    salida_curva = carpeta / "curva.csv"
    salida_elegidos = carpeta / "elegidos.csv"
    pd.DataFrame(curva).to_csv(salida_curva, index=False, encoding="utf-8")
    pd.DataFrame(elegidos).to_csv(salida_elegidos, index=False, encoding="utf-8")
    registro: dict[str, Any] = {
        "regla": "protocolo, sección 7 (exploratorio); demanda y tiempos del caso principal",
        "entradas": huellas,
        "celdas_demanda": len(demanda),
        "poblacion_demanda": round(poblacion_desierto),
        "candidatos": len(candidatos),
        "criterio_candidato": f"celda desierto con {POBLACION_MINIMA_CANDIDATO:g} o más personas",
        "pares": {"archivo": archivo_pares.name, "filas": len(pares), "tope_min": TOPE_PARES_MIN},
        "salidas": {
            salida_curva.name: sha256_archivo(salida_curva),
            salida_elegidos.name: sha256_archivo(salida_elegidos),
        },
    }
    _escribir_registro(carpeta / "localizacion_registro.json", registro)
    return registro


def orden_agrupamientos(rutas: Rutas) -> dict[str, Any]:
    """Gi* con Benjamini-Hochberg y LISA sobre el caso principal (exploratorio)."""
    ruta_p = rutas.derivados / "poblacion_h3_r9.parquet"
    ruta_t = rutas.derivados / "accesibilidad" / "a_pie_r9.parquet"
    huellas = {r.name: _derivado(r) for r in (ruta_p, ruta_t)}
    tabla = pd.read_parquet(ruta_p).merge(pd.read_parquet(ruta_t), on="h3", validate="1:1")
    clases = agrupamientos(tabla)
    unida = tabla.merge(clases, on="h3", how="left")
    unida[["gi_clase", "lisa"]] = unida[["gi_clase", "lisa"]].fillna("sin_vecinos")
    salida = rutas.derivados / "agrupamientos_r9.parquet"
    unida[["h3", "cut", "gi_z", "gi_clase", "lisa"]].to_parquet(salida, index=False)
    total = float(unida["n_per"].sum())

    def resumen(columna: str) -> dict[str, Any]:
        g = unida.groupby(columna)
        return {
            str(k): {
                "celdas": len(v),
                "poblacion": round(float(v["n_per"].sum())),
                "proporcion_poblacion": round(float(v["n_per"].sum()) / total, 4),
                "proporcion_rural": round(
                    float(v.loc[v["rural"], "n_per"].sum()) / max(float(v["n_per"].sum()), 1e-9), 4
                ),
                "mediana_minutos": float(v["minutos"].median()),
            }
            for k, v in g
        }

    calientes = unida[unida["gi_clase"] == "caliente"]
    por_comuna = (
        calientes.groupby("cut")["n_per"].sum().sort_values(ascending=False).head(10).round()
    )
    registro: dict[str, Any] = {
        "regla": (
            "protocolo, sección 7 (exploratorio): Gi* con BH q=0,05; LISA p<0,05 sin corrección"
        ),
        "entradas": huellas,
        "gi": resumen("gi_clase"),
        "lisa": resumen("lisa"),
        "comunas_con_mas_poblacion_en_focos_calientes": {
            str(k): int(v) for k, v in por_comuna.items()
        },
        "salida": {"archivo": salida.name, "sha256": sha256_archivo(salida)},
    }
    _escribir_registro(rutas.derivados / "agrupamientos_registro.json", registro)
    return registro


PLAZA_DE_ARMAS = (-70.6505, -33.4378)  # lon, lat
VARIABLES_PERFIL = [
    "prop_desierto",
    "minutos_medios",
    "prop_rural",
    "prop_60",
    "log_densidad",
    "puntos_10k",
    "sucursales_10k",
    "cajeros_10k",
    "ing_tasa",
    "mul_tasa",
]
VARIABLES_CELDA = [
    "log_poblacion",
    "prop_rural",
    "prop_60",
    "log_edificios_m2",
    "log_calles_m",
    "distancia_centro_km",
]


def _variables_de_celda(tabla: pd.DataFrame, rutas: Rutas) -> pd.DataFrame:
    """Variables de entorno construido por celda; ninguna usa la distancia a los puntos."""
    edificios = extraer_edificios(rutas.osm_rm)
    edificios["h3"] = [h3.latlng_to_cell(p.y, p.x, RESOLUCION_ANALISIS) for p in edificios.geometry]
    area_edif = edificios.groupby("h3")["area_m2"].sum()
    calles = gpd.read_parquet(rutas.osm_calles)
    metricas = calles.to_crs(CRS_METRICO_RM).geometry
    largo = metricas.length.to_numpy()
    medios = metricas.interpolate(0.5, normalized=True).to_crs(4326)
    celda_calle = [h3.latlng_to_cell(p.y, p.x, RESOLUCION_ANALISIS) for p in medios]
    largo_calles = pd.Series(largo).groupby(np.asarray(celda_calle)).sum()
    centro = gpd.GeoSeries(gpd.points_from_xy([PLAZA_DE_ARMAS[0]], [PLAZA_DE_ARMAS[1]]), crs=4326)
    xy_c = centro.to_crs(CRS_METRICO_RM).iloc[0]
    xy = gpd.GeoSeries(gpd.points_from_xy(tabla["lon"], tabla["lat"]), crs=4326).to_crs(
        CRS_METRICO_RM
    )
    salida = tabla.copy()
    salida["x_m"] = xy.x.to_numpy()
    salida["y_m"] = xy.y.to_numpy()
    salida["distancia_centro_km"] = np.hypot(salida["x_m"] - xy_c.x, salida["y_m"] - xy_c.y) / 1e3
    salida["log_poblacion"] = np.log1p(salida["n_per"])
    salida["prop_rural"] = salida["n_per_rural"] / salida["n_per"]
    with np.errstate(divide="ignore", invalid="ignore"):
        salida["prop_60"] = np.where(
            salida["n_per_con_60"] > 0, salida["n_60_mas"] / salida["n_per_con_60"], 0.0
        )
    salida["log_edificios_m2"] = np.log1p(salida["h3"].map(area_edif).fillna(0.0))
    salida["log_calles_m"] = np.log1p(salida["h3"].map(largo_calles).fillna(0.0))
    return salida


def orden_exploratorio(rutas: Rutas) -> dict[str, Any]:
    """Tabla comunal, perfiles, regresiones, clasificación, kernel y Reserva Federal."""
    ruta_p = rutas.derivados / "poblacion_h3_r9.parquet"
    ruta_t = rutas.derivados / "accesibilidad" / "a_pie_r9.parquet"
    ruta_pt = rutas.derivados / "puntos_rm.parquet"
    sae_ing = rutas.bruto / "mdsf-sae" / "SAE_ingresos_2024.xlsx"
    sae_mul = rutas.bruto / "mdsf-sae" / "SAE_multidimensional_2024.xlsx"
    huellas_entrada = {r.name: _derivado(r) for r in (ruta_p, ruta_t, ruta_pt, rutas.osm_rm)}
    huellas_entrada.update({r.name: verificar(r) for r in (sae_ing, sae_mul, rutas.cmf_zip)})
    tabla = pd.read_parquet(ruta_p).merge(pd.read_parquet(ruta_t), on="h3", validate="1:1")
    unidades = leer_unidades(rutas.censo_zip)
    huellas = huellas_comunales(unidades)
    puntos = gpd.read_parquet(ruta_pt)
    nombres = pd.DataFrame(unidades[["cut", "comuna"]])
    comunas = tabla_comunal(
        tabla,
        nombres,
        huellas,
        puntos,
        leer_conteos_rm(rutas.cmf_zip, *PERIODO_CMF),
        [leer_sae(sae_ing, "ing"), leer_sae(sae_mul, "mul")],
        UMBRAL_PRINCIPAL,
    )
    comunas["log_densidad"] = np.log(comunas["densidad_hab_km2"])
    centroides = huellas.set_index("clave").geometry.centroid
    comunas["x_m"] = comunas["clave"].map(centroides.x)
    comunas["y_m"] = comunas["clave"].map(centroides.y)
    grupos = perfiles(comunas, VARIABLES_PERFIL)
    comunas["perfil"] = grupos["etiquetas"]
    nombres_perfil = nombrar_perfiles(grupos["centros"])
    comunas["perfil_nombre"] = comunas["perfil"].map(nombres_perfil)
    nombre_censo = nombres.drop_duplicates("cut").set_index("cut")["comuna"]
    comunas["nombre"] = comunas["cut"].map(nombre_censo)
    if comunas["nombre"].isna().any():
        raise ErrorDatos("Hay comunas sin nombre del Censo")
    reg_desierto = regresion_espacial(
        comunas.assign(pp_desierto=100 * comunas["prop_desierto"]),
        "pp_desierto",
        ["prop_rural", "log_densidad", "ing_tasa", "prop_60"],
        "x_m",
        "y_m",
    )
    reg_cajeros = regresion_espacial(
        comunas, "cajeros_10k", ["ing_tasa", "log_densidad", "prop_rural"], "x_m", "y_m"
    )
    celdas = _variables_de_celda(tabla, rutas)
    celdas["desierto"] = (celdas["minutos"] > UMBRAL_PRINCIPAL).astype(int)
    modelo_celdas = clasificacion(celdas, VARIABLES_CELDA, "desierto")
    xy = celdas[["x_m", "y_m"]].to_numpy()
    celdas["kde_desierto_hab_km2"] = densidad_kernel(
        xy, np.where(celdas["desierto"] == 1, celdas["n_per"], 0.0)
    )
    p = gpd.read_parquet(ruta_pt).to_crs(CRS_METRICO_RM)
    recta, _ = cKDTree(np.column_stack([p.geometry.x, p.geometry.y])).query(xy)
    celdas["recta_m"] = recta
    celdas["desierto_fed"] = reserva_federal(recta, celdas["rural"].to_numpy(dtype=bool))
    total = float(celdas["n_per"].sum())
    ambos = pd.crosstab(
        celdas["desierto"], celdas["desierto_fed"], values=celdas["n_per"], aggfunc="sum"
    ).fillna(0.0)
    carpeta = rutas.derivados / "exploratorio"
    carpeta.mkdir(parents=True, exist_ok=True)
    salida_comunas = carpeta / "comunas.csv"
    salida_celdas = carpeta / "celdas_exploratorio.parquet"
    comunas.drop(columns=["x_m", "y_m"]).to_csv(salida_comunas, index=False, encoding="utf-8")
    celdas[
        ["h3", *VARIABLES_CELDA, "desierto", "kde_desierto_hab_km2", "recta_m", "desierto_fed"]
    ].to_parquet(salida_celdas, index=False)
    registro: dict[str, Any] = {
        "regla": "protocolo, sección 7 (exploratorio)",
        "entradas": huellas_entrada,
        "perfiles": {
            "k": grupos["k"],
            "siluetas": grupos["siluetas"],
            "centros": grupos["centros"].round(4).to_dict(orient="index"),
            "nombres": {str(k): v for k, v in sorted(nombres_perfil.items())},
            "comunas": comunas.groupby("perfil")["clave"].apply(list).to_dict(),
        },
        "regresion_desierto_pp": reg_desierto,
        "regresion_cajeros_10k": reg_cajeros,
        "clasificacion_celdas": {"variables": VARIABLES_CELDA, **modelo_celdas},
        "kernel": {"ancho_m": 2000, "maximo_hab_km2": float(celdas["kde_desierto_hab_km2"].max())},
        "reserva_federal": {
            "proporcion_desierto_fed": float(
                celdas.loc[celdas["desierto_fed"], "n_per"].sum() / total
            ),
            "proporcion_desierto_15min": float(
                celdas.loc[celdas["desierto"] == 1, "n_per"].sum() / total
            ),
            "poblacion_cruzada": {
                f"ours_{int(i)}_fed_{bool(j)}": round(float(ambos.loc[i, j]))
                for i in ambos.index
                for j in ambos.columns
            },
        },
        "salidas": {
            salida_comunas.name: sha256_archivo(salida_comunas),
            salida_celdas.name: sha256_archivo(salida_celdas),
        },
    }
    _escribir_registro(carpeta / "exploratorio_registro.json", registro)
    return registro


def orden_visor(rutas: Rutas, destino: Path | None = None) -> dict[str, Any]:
    """Visor estático (enmienda E-8) en visor/ del repositorio, listo para GitHub Pages."""
    carpeta = destino if destino is not None else raiz_repositorio() / "visor"
    entradas = {a: sha256_archivo(rutas.derivados / a) for a in ARCHIVOS_ENTRADA}
    entradas["osm/rm.osm.pbf"] = sha256_archivo(rutas.osm_rm)
    datos = construir_datos(rutas.derivados, UMBRAL_PRINCIPAL, extraer_referencias(rutas.osm_rm))
    salidas = escribir_visor(datos, carpeta)
    registro: dict[str, Any] = {
        "regla": "enmienda E-8 (publicación por celda)",
        "destino": carpeta.resolve().relative_to(raiz_repositorio()).as_posix()
        if carpeta.resolve().is_relative_to(raiz_repositorio())
        else carpeta.name,
        "entradas": entradas,
        "conteo": datos["conteo"],
        "resumen": datos["resumen"],
        "salidas": salidas,
    }
    _escribir_registro(rutas.derivados / "visor_registro.json", registro)
    return registro


ORDENES: dict[str, Callable[[Rutas], dict[str, Any]]] = {
    "visor": orden_visor,
    "accesibilidad": orden_accesibilidad,
    "exploratorio": orden_exploratorio,
    "agrupamientos": orden_agrupamientos,
    "localizacion": orden_localizacion,
    "hipotesis": orden_hipotesis,
    "poblacion-dasimetrica": orden_poblacion_dasimetrica,
    "recorte-osm": orden_recorte_osm,
    "completitud": orden_completitud,
    "localizadores": orden_localizadores,
    "puntos": orden_puntos,
    "poblacion": orden_poblacion,
    "red-bancoestado": orden_red_bancoestado,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="desiertos")
    parser.add_argument("orden", choices=sorted(ORDENES))
    parser.add_argument("--configuracion", type=Path, default=None)
    parser.add_argument(
        "--escenarios", default=None, help="solo para accesibilidad: lista separada por comas"
    )
    parser.add_argument(
        "--destino", type=Path, default=None, help="solo para visor: carpeta de salida"
    )
    args = parser.parse_args(argv)
    try:
        rutas = cargar_rutas(args.configuracion)
        if args.orden == "accesibilidad" and args.escenarios:
            registro = orden_accesibilidad(rutas, set(args.escenarios.split(",")))
        elif args.orden == "visor":
            registro = orden_visor(rutas, args.destino)
        else:
            registro = ORDENES[args.orden](rutas)
    except ErrorDesiertos as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(registro, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
