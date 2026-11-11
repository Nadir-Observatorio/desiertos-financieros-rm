"""Visor estático del estudio (enmienda E-8, regla de publicación por celda).

Ninguna cifra del visor se escribe a mano: todas se leen de los derivados, y antes de escribir la
página se comprueba que el resumen reproduzca el registro de accesibilidad y el efecto de H1. La
página sale de la plantilla empaquetada; d3 y h3-js se copian junto a ella y se verifican por
sha256 (sin CDN).

Para orientarse, el mapa lleva el nombre de cada comuna en su centro ponderado por población
(un punto, no un límite) y, en gris, ríos y autopistas de OpenStreetMap simplificados.

Regla E-8: se publican en resolución 9 solo las celdas con 50 personas o más; el resto se agrega a
su celda padre de resolución 6 y, si el agregado no llega a 50, se oculta. Los sitios de
localización se publican al hexágono de resolución 8. No se publican puntos ni límites comunales.
"""

from __future__ import annotations

import hashlib
import json
from importlib import resources
from pathlib import Path
from typing import Any, TypedDict, cast

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
from shapely import box
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge, unary_union

from desiertos import CRS_GEOGRAFICO, CRS_METRICO_RM
from desiertos.errores import ErrorDatos
from desiertos.modelos import ORIENTE, PERIURBANA

MIN_PERSONAS = 50
RESOLUCION_AGREGADA = 6
RESOLUCION_SITIOS = 8
TOLERANCIA_H1_PP = 0.05
TOLERANCIA_LINEAS_M = 60.0
MARGEN_CAJA_GRADOS = 0.02
MARCA = "__DATOS__"

CODIGO_GI = {"caliente": 1, "frio": -1}
CODIGO_LISA = {"alto_alto": 1, "bajo_bajo": 2, "alto_bajo": 3, "bajo_alto": 4}
CLASE_PERFIL = {PERIURBANA: 1, ORIENTE: 2}
PARTICULAS = frozenset({"de", "del", "la", "las", "los", "y"})

# Bibliotecas copiadas de npm (d3 7.8.5, licencia ISC; h3-js 4.1.0, licencia Apache 2.0).
VENDOR: dict[str, str] = {
    "d3.min.js": "d6b03aefc9f6c44c7bc78713679c78c295028fa914319119e5cc4b4954855b1c",
    "h3-js.umd.js": "0870d94de38503bdf6b63dce8c4812a42dc43565f15ae35694aedf4f97eaf548",
    "LICENSE-d3.txt": "3e6849627f74ff73c257a3ae1efb574015d94fc1035c05ec3c15805165efcbc4",
    "LICENSE-h3-js.txt": "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
}

ARCHIVOS_ENTRADA = (
    "poblacion_h3_r9.parquet",
    "accesibilidad/a_pie_r9.parquet",
    "agrupamientos_r9.parquet",
    "accesibilidad_registro.json",
    "hipotesis_resultados.csv",
    "hipotesis_registro.json",
    "localizacion/curva.csv",
    "localizacion/elegidos.csv",
    "exploratorio/comunas.csv",
)


class Resumen(TypedDict):
    pob: int
    des: int
    pct: float
    rural: float
    urbano: float
    umbral_min: float
    tope_min: int
    min_personas: int
    replicas: int
    h1: list[float]
    h2: list[float]
    h3: float
    sostiene: dict[str, bool]
    p_holm: dict[str, float]


class Comuna(TypedDict):
    cut: int
    comuna: str
    perfil: str
    pc: int
    pob: int
    des: float
    min: float
    rural: float
    pts: float
    cv: float
    suc: float
    caj: float
    ing: float
    mul: float
    lat: float
    lon: float


class Linea(TypedDict):
    t: str
    c: list[list[list[float]]]


class Conteo(TypedDict):
    celdas_r9: int
    celdas_r6: int
    r6_ocultas: int
    personas_en_r6: int


class DatosVisor(TypedDict):
    r9: list[list[Any]]
    r6: list[list[Any]]
    sitios: dict[str, list[str]]
    curva: list[list[float]]
    comunas: list[Comuna]
    referencias: list[Linea]
    resumen: Resumen
    conteo: Conteo


def _faltan(tabla: pd.DataFrame, columnas: set[str], nombre: str) -> None:
    faltan = columnas - set(tabla.columns)
    if faltan:
        raise ErrorDatos(f"{nombre}: faltan columnas {sorted(faltan)}")


def _filas(tabla: pd.DataFrame) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], tabla.to_dict(orient="records"))


def nombre_visible(nombre: str) -> str:
    """'SAN JOSÉ DE MAIPO' -> 'San José de Maipo' (partículas en minúscula salvo al inicio)."""
    palabras = nombre.strip().lower().split()
    if not palabras:
        raise ErrorDatos("Nombre de comuna vacío")
    return " ".join(
        p if i > 0 and p in PARTICULAS else p[:1].upper() + p[1:] for i, p in enumerate(palabras)
    )


def celdas_publicables(
    celdas: pd.DataFrame, umbral: float
) -> tuple[list[list[Any]], list[list[Any]], Conteo]:
    """Aplica E-8.

    r9: [h3, personas, minutos, censurada, gi, lisa, desierto, cut]. r6: [h3, personas, proporción
    en desierto, minutos medios], o [h3, None, None, None] si el agregado se oculta.

    Personas a la decena y minutos al entero; la marca de desierto se calcula con los minutos sin
    redondear, para que el redondeo no cambie la clase de una celda cerca del umbral.
    """
    _faltan(celdas, {"h3", "cut", "n_per", "minutos", "censurada", "gi_clase", "lisa"}, "celdas")
    if celdas["h3"].duplicated().any():
        raise ErrorDatos("celdas: h3 repetidos")
    if (celdas["n_per"] < 0).any():
        raise ErrorDatos("celdas: población negativa")
    tabla = celdas.sort_values("h3", kind="stable")
    publicas = tabla[tabla["n_per"] >= MIN_PERSONAS]
    r9: list[list[Any]] = [
        [
            str(f["h3"]),
            int(round(float(f["n_per"]), -1)),
            round(float(f["minutos"])),
            int(bool(f["censurada"])),
            CODIGO_GI.get(str(f["gi_clase"]), 0),
            CODIGO_LISA.get(str(f["lisa"]), 0),
            int(float(f["minutos"]) > umbral),
            int(f["cut"]),
        ]
        for f in _filas(publicas)
    ]
    resto = tabla[tabla["n_per"] < MIN_PERSONAS]
    r6: list[list[Any]] = []
    ocultas = 0
    if not resto.empty:
        agregado = (
            resto.assign(
                padre=[h3.cell_to_parent(c, RESOLUCION_AGREGADA) for c in resto["h3"]],
                des=np.where(resto["minutos"] > umbral, resto["n_per"], 0.0),
                min_pond=resto["minutos"] * resto["n_per"],
            )
            .groupby("padre", sort=True)
            .agg(pob=("n_per", "sum"), des=("des", "sum"), min_pond=("min_pond", "sum"))
        )
        for f in _filas(agregado.reset_index()):
            padre = f["padre"]
            pob = float(f["pob"])
            if pob >= MIN_PERSONAS:
                r6.append(
                    [
                        str(padre),
                        int(round(pob, -1)),
                        round(float(f["des"]) / pob, 3),
                        round(float(f["min_pond"]) / pob),
                    ]
                )
            else:
                r6.append([str(padre), None, None, None])
                ocultas += 1
    conteo: Conteo = {
        "celdas_r9": len(r9),
        "celdas_r6": len(r6),
        "r6_ocultas": ocultas,
        "personas_en_r6": round(float(resto["n_per"].sum())),
    }
    return r9, r6, conteo


def sitios_mclp(elegidos: pd.DataFrame) -> dict[str, list[str]]:
    """Sitios del modelo de cobertura máxima por k, generalizados al hexágono de resolución 8."""
    _faltan(elegidos, {"modelo", "k", "h3"}, "elegidos.csv")
    mclp = elegidos[elegidos["modelo"] == "mclp"]
    if mclp.empty:
        raise ErrorDatos("elegidos.csv: no hay sitios del modelo mclp")
    return {
        str(k): sorted(
            {h3.cell_to_parent(str(c), RESOLUCION_SITIOS) for c in mclp.loc[mclp["k"] == k, "h3"]}
        )
        for k in sorted({int(v) for v in mclp["k"].tolist()})
    }


def curva_mclp(curva: pd.DataFrame) -> list[list[float]]:
    """[k, población cubierta, % de la región en desierto] del MCLP exacto (HiGHS)."""
    _faltan(
        curva,
        {"modelo", "metodo", "k", "poblacion_cubierta", "proporcion_region_en_desierto"},
        "curva.csv",
    )
    exacta = curva[(curva["modelo"] == "mclp") & (curva["metodo"] == "highs")].sort_values("k")
    if exacta.empty:
        raise ErrorDatos("curva.csv: no hay filas mclp con HiGHS")
    return [
        [
            int(f["k"]),
            int(f["poblacion_cubierta"]),
            round(float(f["proporcion_region_en_desierto"]) * 100, 2),
        ]
        for f in _filas(exacta)
    ]


def centros_comunales(celdas: pd.DataFrame) -> pd.DataFrame:
    """Centro de cada comuna ponderado por población (índice cut; columnas lat y lon).

    Sirve para rotular el mapa: cae donde vive la gente y no dibuja límites (E-8).
    """
    _faltan(celdas, {"cut", "n_per", "lat", "lon"}, "celdas")
    pesos = celdas[celdas["n_per"] > 0]
    if pesos.empty:
        raise ErrorDatos("celdas: sin población para ubicar las comunas")
    sumas = (
        pesos.assign(wlat=pesos["lat"] * pesos["n_per"], wlon=pesos["lon"] * pesos["n_per"])
        .groupby("cut")[["wlat", "wlon", "n_per"]]
        .sum()
    )
    return pd.DataFrame(
        {"lat": sumas["wlat"] / sumas["n_per"], "lon": sumas["wlon"] / sumas["n_per"]},
        index=sumas.index,
    )


def lineas_referencia(
    referencias: gpd.GeoDataFrame, caja: tuple[float, float, float, float]
) -> list[Linea]:
    """Ríos y autopistas unidos por tipo, recortados a la caja (lon0, lat0, lon1, lat1) y
    simplificados a TOLERANCIA_LINEAS_M. Coordenadas [lon, lat] con 4 decimales (unos 10 m)."""
    _faltan(referencias, {"tipo", "geometry"}, "referencias")
    if referencias.crs is None:
        raise ErrorDatos("referencias sin sistema de referencia")
    recorte = box(*caja)
    salida: list[Linea] = []
    for tipo in ("rio", "autopista"):
        grupo = referencias[referencias["tipo"] == tipo].to_crs(CRS_GEOGRAFICO)
        if grupo.empty:
            continue
        unidas = unary_union(list(grupo.geometry)).intersection(recorte)
        if unidas.is_empty:
            continue
        if isinstance(unidas, MultiLineString | LineString):
            unidas = linemerge(unidas) if isinstance(unidas, MultiLineString) else unidas
        simples = (
            gpd.GeoSeries([unidas], crs=CRS_GEOGRAFICO)
            .to_crs(CRS_METRICO_RM)
            .simplify(TOLERANCIA_LINEAS_M)
            .to_crs(CRS_GEOGRAFICO)
            .iloc[0]
        )
        partes = getattr(simples, "geoms", [simples])
        trazos = [
            [[round(x, 4), round(y, 4)] for x, y in parte.coords]
            for parte in partes
            if isinstance(parte, LineString) and len(parte.coords) >= 2
        ]
        if trazos:
            salida.append({"t": tipo, "c": sorted(trazos)})
    return salida


def tabla_comunas(comunas: pd.DataFrame, centros: pd.DataFrame) -> list[Comuna]:
    """Filas de la tabla comunal, de mayor a menor población, con el centro para el rótulo."""
    columnas = {
        "cut",
        "nombre",
        "perfil_nombre",
        "poblacion",
        "prop_desierto",
        "minutos_medios",
        "prop_rural",
        "puntos_10k",
        "caja_vecina_10k",
        "sucursales_10k",
        "cajeros_10k",
        "ing_tasa",
        "mul_tasa",
    }
    faltan = columnas - set(comunas.columns)
    if faltan:
        raise ErrorDatos(
            f"comunas.csv: faltan columnas {sorted(faltan)}; "
            "vuelva a ejecutar python -m desiertos exploratorio"
        )
    sin_centro = set(comunas["cut"].astype(int)) - {int(c) for c in centros.index}
    if sin_centro:
        raise ErrorDatos(f"Comunas sin celdas pobladas para el rótulo: {sorted(sin_centro)}")
    ubicacion = {
        int(c["cut"]): (float(c["lat"]), float(c["lon"]))
        for c in _filas(centros.rename_axis("cut").reset_index())
    }
    filas: list[Comuna] = []
    for f in _filas(comunas.sort_values(["poblacion", "cut"], ascending=[False, True])):
        perfil = str(f["perfil_nombre"])
        filas.append(
            {
                "cut": int(f["cut"]),
                "comuna": nombre_visible(str(f["nombre"])),
                "perfil": perfil,
                "pc": CLASE_PERFIL.get(perfil, 0),
                "pob": int(round(float(f["poblacion"]), -2)),
                "des": round(float(f["prop_desierto"]) * 100, 1),
                "min": round(float(f["minutos_medios"]), 1),
                "rural": round(float(f["prop_rural"]) * 100, 1),
                "pts": round(float(f["puntos_10k"]), 1),
                "cv": round(float(f["caja_vecina_10k"]), 1),
                "suc": round(float(f["sucursales_10k"]), 2),
                "caj": round(float(f["cajeros_10k"]), 1),
                "ing": round(float(f["ing_tasa"]) * 100, 1),
                "mul": round(float(f["mul_tasa"]) * 100, 1),
                "lat": round(ubicacion[int(f["cut"])][0], 4),
                "lon": round(ubicacion[int(f["cut"])][1], 4),
            }
        )
    return filas


def _principal(hipotesis: pd.DataFrame, nombre: str) -> pd.Series:
    fila = hipotesis[(hipotesis["caso"] == "principal") & (hipotesis["hipotesis"] == nombre)]
    if len(fila) != 1:
        raise ErrorDatos(f"hipotesis_resultados.csv: se esperaba una fila principal de {nombre}")
    return fila.iloc[0]


def _verdadero(valor: object) -> bool:
    if isinstance(valor, bool | np.bool_):
        return bool(valor)
    texto = str(valor).strip().lower()
    if texto in {"true", "1"}:
        return True
    if texto in {"false", "0"}:
        return False
    raise ErrorDatos(f"Valor de se_sostiene no reconocido: {valor!r}")


def resumen_estudio(
    celdas: pd.DataFrame,
    hipotesis: pd.DataFrame,
    registro_hipotesis: dict[str, Any],
    registro_accesibilidad: dict[str, Any],
    umbral: float,
) -> Resumen:
    """Cifras de cabecera e hipótesis, con dos comprobaciones contra los registros."""
    _faltan(celdas, {"n_per", "minutos", "rural"}, "celdas")
    _faltan(
        hipotesis,
        {"caso", "hipotesis", "umbral_min", "efecto", "ic_inf", "ic_sup", "p_holm", "se_sostiene"},
        "hipotesis_resultados.csv",
    )
    total = float(celdas["n_per"].sum())
    if total <= 0:
        raise ErrorDatos("celdas: población total cero")
    desierto = celdas["minutos"] > umbral
    des = float(celdas.loc[desierto, "n_per"].sum())

    def proporcion(mascara: pd.Series) -> float:
        base = float(celdas.loc[mascara, "n_per"].sum())
        if base <= 0:
            raise ErrorDatos("celdas: un grupo rural o urbano sin población")
        return float(celdas.loc[mascara & desierto, "n_per"].sum()) / base

    es_rural = celdas["rural"].astype(bool)
    rural = proporcion(es_rural) * 100
    urbano = proporcion(~es_rural) * 100

    clave = "a_pie_r9"
    escenario = registro_accesibilidad.get("escenarios", {}).get(clave)
    if escenario is None:
        raise ErrorDatos(f"accesibilidad_registro.json: falta el escenario {clave}")
    esperado = escenario.get(f"poblacion_sobre_{int(umbral)}_min")
    if esperado is None or abs(round(des) - int(esperado)) > 1:
        raise ErrorDatos(
            f"La población en desierto ({round(des)}) no coincide con el registro ({esperado})"
        )

    h1, h2, h3r = (_principal(hipotesis, h) for h in ("H1", "H2", "H3"))
    for fila in (h1, h2, h3r):
        if float(fila["umbral_min"]) != umbral:
            raise ErrorDatos("hipotesis_resultados.csv: el caso principal usa otro umbral")
    if abs((rural - urbano) - float(h1["efecto"])) > TOLERANCIA_H1_PP:
        raise ErrorDatos(
            f"La diferencia rural menos urbano ({rural - urbano:.2f} pp) no reproduce H1 "
            f"({float(h1['efecto']):.2f} pp)"
        )
    replicas = registro_hipotesis.get("replicas_bootstrap")
    tope = registro_accesibilidad.get("tope_min")
    if not isinstance(replicas, int) or not isinstance(tope, int):
        raise ErrorDatos("Faltan replicas_bootstrap o tope_min en los registros")
    return {
        "pob": int(round(total, -3)),
        "des": int(round(des, -2)),
        "pct": round(des / total * 100, 1),
        "rural": round(rural, 1),
        "urbano": round(urbano, 1),
        "umbral_min": umbral,
        "tope_min": tope,
        "min_personas": MIN_PERSONAS,
        "replicas": replicas,
        "h1": [round(float(h1[c]), 1) for c in ("efecto", "ic_inf", "ic_sup")],
        "h2": [round(float(h2[c]), 2) for c in ("efecto", "ic_inf", "ic_sup")],
        "h3": round(float(h3r["efecto"]), 3),
        "sostiene": {
            h: _verdadero(f["se_sostiene"]) for h, f in (("H1", h1), ("H2", h2), ("H3", h3r))
        },
        "p_holm": {h: float(f["p_holm"]) for h, f in (("H1", h1), ("H2", h2), ("H3", h3r))},
    }


def _leer_json(ruta: Path) -> dict[str, Any]:
    try:
        contenido = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ErrorDatos(f"No se pudo leer {ruta}: {exc}") from exc
    if not isinstance(contenido, dict):
        raise ErrorDatos(f"{ruta} no es un objeto JSON")
    return contenido


def construir_datos(derivados: Path, umbral: float, referencias: gpd.GeoDataFrame) -> DatosVisor:
    """Lee los derivados y arma los datos del visor. No escribe nada.

    referencias: ríos y autopistas (ingesta.osm.extraer_referencias) para orientarse.
    """
    faltan = [a for a in ARCHIVOS_ENTRADA if not (derivados / a).is_file()]
    if faltan:
        raise ErrorDatos(f"Faltan derivados en {derivados}: {faltan}")
    celdas = (
        pd.read_parquet(derivados / "poblacion_h3_r9.parquet")
        .merge(
            pd.read_parquet(derivados / "accesibilidad" / "a_pie_r9.parquet")[
                ["h3", "minutos", "censurada"]
            ],
            on="h3",
            validate="1:1",
        )
        .merge(
            pd.read_parquet(derivados / "agrupamientos_r9.parquet")[["h3", "gi_clase", "lisa"]],
            on="h3",
            how="left",
            validate="1:1",
        )
    )
    celdas[["gi_clase", "lisa"]] = celdas[["gi_clase", "lisa"]].fillna("sin_vecinos")
    r9, r6, conteo = celdas_publicables(celdas, umbral)
    resumen = resumen_estudio(
        celdas,
        pd.read_csv(derivados / "hipotesis_resultados.csv"),
        _leer_json(derivados / "hipotesis_registro.json"),
        _leer_json(derivados / "accesibilidad_registro.json"),
        umbral,
    )
    curva = curva_mclp(pd.read_csv(derivados / "localizacion" / "curva.csv"))
    if not any(int(c[0]) == 100 for c in curva):
        raise ErrorDatos("curva.csv: falta el escenario de 100 puntos que muestra la cabecera")
    return {
        "r9": r9,
        "r6": r6,
        "sitios": sitios_mclp(pd.read_csv(derivados / "localizacion" / "elegidos.csv")),
        "curva": curva,
        "comunas": tabla_comunas(
            pd.read_csv(derivados / "exploratorio" / "comunas.csv"), centros_comunales(celdas)
        ),
        "referencias": lineas_referencia(
            referencias,
            (
                float(celdas["lon"].min()) - MARGEN_CAJA_GRADOS,
                float(celdas["lat"].min()) - MARGEN_CAJA_GRADOS,
                float(celdas["lon"].max()) + MARGEN_CAJA_GRADOS,
                float(celdas["lat"].max()) + MARGEN_CAJA_GRADOS,
            ),
        ),
        "resumen": resumen,
        "conteo": conteo,
    }


def json_datos(datos: DatosVisor) -> str:
    """JSON compacto y estable (mismo contenido, mismos bytes)."""
    return json.dumps(datos, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def pagina(datos: DatosVisor, plantilla: str) -> str:
    """Incrusta los datos en la plantilla. Escapa '</' para que no cierre el <script>."""
    if plantilla.count(MARCA) != 1:
        raise ErrorDatos(f"La plantilla debe contener {MARCA} exactamente una vez")
    return plantilla.replace(MARCA, json_datos(datos).replace("</", "<\\/"))


def _recurso(nombre: str) -> bytes:
    return resources.files("desiertos").joinpath("plantillas", nombre).read_bytes()


def plantilla_empaquetada() -> str:
    return _recurso("visor.html").decode("utf-8")


def escribir_visor(datos: DatosVisor, destino: Path) -> dict[str, str]:
    """Escribe index.html, datos.json y vendor/ en destino. Devuelve el sha256 de cada archivo."""
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "vendor").mkdir(exist_ok=True)
    contenidos: dict[str, bytes] = {
        "index.html": pagina(datos, plantilla_empaquetada()).encode("utf-8"),
        "datos.json": json_datos(datos).encode("utf-8"),
    }
    for nombre, huella in VENDOR.items():
        cuerpo = _recurso(f"vendor/{nombre}")
        if hashlib.sha256(cuerpo).hexdigest() != huella:
            raise ErrorDatos(f"vendor/{nombre} no coincide con su sha256 fijado")
        contenidos[f"vendor/{nombre}"] = cuerpo
    huellas: dict[str, str] = {}
    for relativo, cuerpo in sorted(contenidos.items()):
        (destino / relativo).write_bytes(cuerpo)
        huellas[relativo] = hashlib.sha256(cuerpo).hexdigest()
    return huellas
