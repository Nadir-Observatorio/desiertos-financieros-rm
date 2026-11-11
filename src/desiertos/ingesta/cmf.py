"""Reportes por comuna de la CMF (sistema BEST): sucursales y cajeros bancarios.

Los dos libros traen una hoja por región. La de la Región Metropolitana se reconoce
por su título, no por su posición. Los guiones del reporte significan cero.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd

from desiertos.errores import ErrorDatos
from desiertos.ingesta.coordenadas import normalizar_comuna

MIEMBRO_SUCURSALES = "SucursalesPersonasComunaBancoNumero.xlsx"
MIEMBRO_CAJEROS = "CMF_CajerosNroCajerosComunaRegInst.xlsx"
TITULO_RM = "Región Metropolitana"
MESES = ("Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic")


def _leer_miembro(zip_cmf: Path, sufijo: str) -> dict[str, pd.DataFrame]:
    try:
        with zipfile.ZipFile(zip_cmf) as zf:
            nombres = [n for n in zf.namelist() if n.endswith(sufijo)]
            if len(nombres) != 1:
                raise ErrorDatos(f"{zip_cmf.name}: se esperaba un miembro *{sufijo}")
            contenido = zf.read(nombres[0])
    except zipfile.BadZipFile as exc:
        raise ErrorDatos(f"{zip_cmf} no es un zip válido") from exc
    hojas: dict[str, pd.DataFrame] = pd.read_excel(
        io.BytesIO(contenido), sheet_name=None, header=None
    )
    return hojas


def hoja_de_region(hojas: dict[str, pd.DataFrame], titulo: str = TITULO_RM) -> pd.DataFrame:
    """Hoja cuyas primeras filas contienen el título de la región."""
    for hoja in hojas.values():
        cabecera = hoja.head(6).astype(str)
        if cabecera.apply(lambda s: s.str.strip().eq(titulo)).any().any():
            return hoja
    raise ErrorDatos(f"Ninguna hoja corresponde a {titulo}")


def _numero(valor: object) -> float:
    if isinstance(valor, str) and valor.strip() == "-":
        return 0.0
    convertido = pd.to_numeric(pd.Series([valor]), errors="coerce").iloc[0]
    return float(convertido) if pd.notna(convertido) else 0.0


def sucursales_por_comuna(hoja: pd.DataFrame) -> pd.Series:
    """Total de sucursales por comuna: filas con comuna (col. 5) y total (col. 7)."""
    filas = hoja[hoja[5].notna() & pd.to_numeric(hoja[7], errors="coerce").notna()]
    if filas.empty:
        raise ErrorDatos("La hoja de sucursales no trae filas de comuna")
    serie = pd.Series(
        pd.to_numeric(filas[7]).astype(int).to_numpy(),
        index=[normalizar_comuna(str(c)) for c in filas[5]],
        name="cmf_sucursales",
    )
    if serie.index.duplicated().any():
        raise ErrorDatos("Comunas repetidas en la hoja de sucursales")
    return serie


def cajeros_por_comuna(hoja: pd.DataFrame, anio: int, mes: str) -> pd.Series:
    """Cajeros por comuna en un mes: suma de las columnas de institución de cada comuna."""
    if mes not in MESES:
        raise ErrorDatos(f"Mes desconocido: {mes}")
    filas_titulo = hoja.index[hoja[4].astype(str).str.strip().eq("Periodo")]
    if len(filas_titulo) != 1:
        raise ErrorDatos("La hoja de cajeros no trae una fila 'Periodo'")
    f_comuna = int(filas_titulo[0])
    f_institucion = f_comuna + 1
    anios = pd.to_numeric(hoja[4], errors="coerce").ffill()
    coincide = hoja.index[(anios == anio) & hoja[5].astype(str).str.strip().eq(mes)]
    if len(coincide) != 1:
        raise ErrorDatos(f"El periodo {anio}-{mes} no está en la hoja de cajeros")
    fila = int(coincide[0])
    comunas = hoja.iloc[f_comuna]
    instituciones = hoja.iloc[f_institucion]
    inicios = [j for j in range(6, hoja.shape[1]) if pd.notna(comunas.iloc[j])]
    totales: dict[str, int] = {}
    for k, inicio in enumerate(inicios):
        fin = inicios[k + 1] if k + 1 < len(inicios) else hoja.shape[1]
        columnas = [j for j in range(inicio, fin) if pd.notna(instituciones.iloc[j])]
        total = sum(_numero(hoja.iat[fila, j]) for j in columnas)
        totales[normalizar_comuna(str(comunas.iloc[inicio]))] = int(total)
    return pd.Series(totales, name="cmf_cajeros")


def leer_conteos_rm(zip_cmf: Path, anio: int, mes: str) -> pd.DataFrame:
    """Sucursales y cajeros de la RM por comuna normalizada."""
    suc = sucursales_por_comuna(hoja_de_region(_leer_miembro(zip_cmf, MIEMBRO_SUCURSALES)))
    caj = cajeros_por_comuna(hoja_de_region(_leer_miembro(zip_cmf, MIEMBRO_CAJEROS)), anio, mes)
    if set(suc.index) != set(caj.index):
        raise ErrorDatos("Los dos reportes no cubren las mismas comunas")
    return pd.concat([suc, caj], axis=1).rename_axis("comuna").reset_index()


def _institucion(valor: object) -> str:
    """Nombre de institución sin espacios duros ni espacios repetidos."""
    return " ".join(str(valor).replace("\xa0", " ").split())


def sucursales_por_institucion(hoja: pd.DataFrame) -> pd.DataFrame:
    """Sucursales por comuna e institución: filas con institución (col. 6) bajo cada comuna."""
    filas: list[dict[str, object]] = []
    comuna: str | None = None
    for _, fila in hoja.iterrows():
        if pd.notna(fila[5]) and pd.notna(pd.to_numeric(fila[7], errors="coerce")):
            comuna = normalizar_comuna(str(fila[5]))
        elif comuna is not None and pd.notna(fila[6]):
            valor = pd.to_numeric(fila[7], errors="coerce")
            if pd.notna(valor):
                filas.append(
                    {
                        "comuna": comuna,
                        "institucion": _institucion(fila[6]),
                        "cmf_sucursales": int(valor),
                    }
                )
    if not filas:
        raise ErrorDatos("La hoja de sucursales no trae filas por institución")
    return pd.DataFrame(filas)


def cajeros_por_institucion(hoja: pd.DataFrame, anio: int, mes: str) -> pd.DataFrame:
    """Cajeros por comuna e institución en un mes."""
    if mes not in MESES:
        raise ErrorDatos(f"Mes desconocido: {mes}")
    filas_titulo = hoja.index[hoja[4].astype(str).str.strip().eq("Periodo")]
    if len(filas_titulo) != 1:
        raise ErrorDatos("La hoja de cajeros no trae una fila 'Periodo'")
    f_comuna = int(filas_titulo[0])
    anios = pd.to_numeric(hoja[4], errors="coerce").ffill()
    coincide = hoja.index[(anios == anio) & hoja[5].astype(str).str.strip().eq(mes)]
    if len(coincide) != 1:
        raise ErrorDatos(f"El periodo {anio}-{mes} no está en la hoja de cajeros")
    fila = int(coincide[0])
    comunas = hoja.iloc[f_comuna]
    instituciones = hoja.iloc[f_comuna + 1]
    filas: list[dict[str, object]] = []
    comuna: str | None = None
    for j in range(6, hoja.shape[1]):
        if pd.notna(comunas.iloc[j]):
            comuna = normalizar_comuna(str(comunas.iloc[j]))
        if comuna is not None and pd.notna(instituciones.iloc[j]):
            filas.append(
                {
                    "comuna": comuna,
                    "institucion": _institucion(instituciones.iloc[j]),
                    "cmf_cajeros": int(_numero(hoja.iat[fila, j])),
                }
            )
    return pd.DataFrame(filas)


def leer_conteos_por_institucion_rm(zip_cmf: Path, anio: int, mes: str) -> pd.DataFrame:
    """Sucursales y cajeros de la RM por comuna normalizada e institución (ceros incluidos)."""
    suc = sucursales_por_institucion(hoja_de_region(_leer_miembro(zip_cmf, MIEMBRO_SUCURSALES)))
    caj = cajeros_por_institucion(
        hoja_de_region(_leer_miembro(zip_cmf, MIEMBRO_CAJEROS)), anio, mes
    )
    tabla = suc.merge(caj, on=["comuna", "institucion"], how="outer")
    tabla[["cmf_sucursales", "cmf_cajeros"]] = (
        tabla[["cmf_sucursales", "cmf_cajeros"]].fillna(0).astype(int)
    )
    return tabla
