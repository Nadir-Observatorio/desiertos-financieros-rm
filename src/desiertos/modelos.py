"""Modelos exploratorios (protocolo, sección 7). Todo resultado de aquí se rotula exploratorio.

- Perfiles comunales: k-medias sobre variables estandarizadas; k por silueta.
- Regresión comunal: MCO frente a rezago espacial y error espacial (spreg, máxima verosimilitud)
  y GWR (mgwr, ancho de banda por AICc). Vecindad por 4 vecinos más cercanos entre centroides.
- Clasificación de celdas desierto con validación cruzada por bloques espaciales (H3 resolución 5):
  regresión logística de referencia y gradient boosting. Sin variables de distancia a puntos.
- Densidad kernel de la población en desierto evaluada en los centros de celda.
- Comparación con la definición de la Reserva Federal (radio en línea recta).
"""

from __future__ import annotations

from typing import Any, cast

import h3
import numpy as np
import pandas as pd
from libpysal.weights import KNN
from mgwr.gwr import GWR
from mgwr.sel_bw import Sel_BW
from sklearn.cluster import KMeans
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score, roc_auc_score, silhouette_score
from sklearn.model_selection import GroupKFold
from sklearn.neighbors import KernelDensity
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from spreg import OLS, ML_Error, ML_Lag

from desiertos.errores import ErrorDatos
from desiertos.hipotesis import SEMILLA

RADIO_FED_URBANO_M = 3200.0
RADIO_FED_RURAL_M = 16100.0
ANCHO_KERNEL_M = 2000.0


def perfiles(tabla: pd.DataFrame, variables: list[str], ks: range = range(2, 7)) -> dict[str, Any]:
    """k-medias con k por mayor silueta: etiquetas, k, siluetas y centros en escala original."""
    datos = tabla[variables].to_numpy(dtype=float)
    if np.isnan(datos).any():
        raise ErrorDatos("Hay valores faltantes en las variables del perfil")
    z = StandardScaler().fit_transform(datos)
    siluetas: dict[int, float] = {}
    modelos: dict[int, KMeans] = {}
    for k in ks:
        modelo = KMeans(n_clusters=k, n_init=20, random_state=SEMILLA).fit(z)
        siluetas[k] = float(silhouette_score(z, modelo.labels_))
        modelos[k] = modelo
    mejor = max(siluetas, key=lambda k: siluetas[k])
    etiquetas = modelos[mejor].labels_
    centros = tabla.assign(perfil=etiquetas).groupby("perfil")[variables].mean()
    return {"k": mejor, "siluetas": siluetas, "etiquetas": etiquetas, "centros": centros}


PERIURBANA = "Periurbana y rural"
ORIENTE = "Oriente y centro"
POPULAR = "Urbana popular"


def nombrar_perfiles(centros: pd.DataFrame) -> dict[int, str]:
    """Nombre de cada perfil según su centro (variables en escala original).

    Con tres perfiles: el de mayor proporción rural es "Periurbana y rural"; de los otros dos, el
    de menor pobreza por ingresos es "Oriente y centro" y el restante "Urbana popular". Con otro
    número de perfiles no hay nombres sustantivos: "Perfil 1" a "Perfil k", de menor a mayor
    proporción de población en desierto.
    """
    faltan = {"prop_rural", "ing_tasa", "prop_desierto"} - set(centros.columns)
    if faltan:
        raise ErrorDatos(f"Faltan variables en los centros de perfil: {sorted(faltan)}")
    if centros.empty:
        raise ErrorDatos("No hay perfiles que nombrar")
    ids = [int(i) for i in centros.index]
    if len(ids) != 3:
        orden = centros["prop_desierto"].sort_values(kind="stable").index
        return {int(cast(Any, p)): f"Perfil {n}" for n, p in enumerate(orden, start=1)}
    rural = int(cast(Any, centros["prop_rural"].idxmax()))
    resto = centros.drop(index=rural)
    oriente = int(cast(Any, resto["ing_tasa"].idxmin()))
    popular = next(i for i in ids if i not in (rural, oriente))
    return {rural: PERIURBANA, oriente: ORIENTE, popular: POPULAR}


def regresion_espacial(
    tabla: pd.DataFrame, y: str, x: list[str], lon: str, lat: str
) -> dict[str, Any]:
    """MCO con diagnósticos LM, rezago y error espacial (ML), y GWR. Coordenadas en metros."""
    datos = tabla[[y, *x, lon, lat]].dropna()
    if len(datos) < len(x) + 10:
        raise ErrorDatos("Muy pocas observaciones para la regresión")
    coords = datos[[lon, lat]].to_numpy(dtype=float)
    pesos = KNN.from_array(coords, k=4)
    pesos.transform = "r"
    yv = datos[[y]].to_numpy(dtype=float)
    xv = datos[x].to_numpy(dtype=float)
    mco = OLS(yv, xv, w=pesos, spat_diag=True, moran=True, name_y=y, name_x=x)
    rezago = ML_Lag(yv, xv, w=pesos, name_y=y, name_x=x)
    error = ML_Error(yv, xv, w=pesos, name_y=y, name_x=x)
    xz = StandardScaler().fit_transform(xv)
    yz = (yv - yv.mean()) / yv.std()
    ancho = Sel_BW(coords, yz, xz, fixed=False).search(criterion="AICc")
    gwr = GWR(coords, yz, xz, ancho, fixed=False).fit()
    nombres = ["constante", *x]
    return {
        "n": len(datos),
        "mco": {
            "coeficientes": dict(zip(nombres, mco.betas.ravel().tolist(), strict=True)),
            "p": dict(zip(nombres, [float(t[1]) for t in mco.t_stat], strict=True)),
            "r2": float(mco.r2),
            "aic": float(mco.aic),
            "moran_residuos": [float(v) for v in mco.moran_res],
            "lm_rezago": [float(v) for v in mco.lm_lag],
            "lm_error": [float(v) for v in mco.lm_error],
        },
        "rezago": {
            "rho": float(rezago.rho),
            "coeficientes": dict(zip(nombres, rezago.betas.ravel()[:-1].tolist(), strict=True)),
            "aic": float(rezago.aic),
        },
        "error": {
            "lambda": float(error.lam),
            "coeficientes": dict(zip(nombres, error.betas.ravel()[:-1].tolist(), strict=True)),
            "aic": float(error.aic),
        },
        "gwr": {
            "ancho_vecinos": float(ancho),
            "aicc": float(gwr.aicc),
            "r2": float(gwr.R2),
            "coeficientes_locales": pd.DataFrame(gwr.params, columns=nombres)
            .describe()
            .loc[["min", "50%", "max"]]
            .to_dict(),
        },
    }


def clasificacion(
    celdas: pd.DataFrame, variables: list[str], objetivo: str, resolucion_bloque: int = 5
) -> dict[str, Any]:
    """AUC y exactitud balanceada con validación cruzada por bloques H3 (5 pliegues)."""
    x = celdas[variables].to_numpy(dtype=float)
    y = celdas[objetivo].to_numpy(dtype=int)
    if len(np.unique(y)) < 2:
        raise ErrorDatos("El objetivo tiene una sola clase")
    grupos = np.array([h3.cell_to_parent(c, resolucion_bloque) for c in celdas["h3"]])
    pliegues = GroupKFold(n_splits=5)

    def logistica() -> Any:
        return make_pipeline(
            StandardScaler(), LogisticRegression(max_iter=2000, class_weight="balanced")
        )

    def boosting() -> Any:
        return HistGradientBoostingClassifier(random_state=SEMILLA, class_weight="balanced")

    modelos: dict[str, Any] = {"logistica": logistica, "gradient_boosting": boosting}
    salida: dict[str, Any] = {}
    for nombre, crear in modelos.items():
        prob = np.zeros(len(y))
        for entrena, prueba in pliegues.split(x, y, grupos):
            modelo = crear().fit(x[entrena], y[entrena])
            prob[prueba] = modelo.predict_proba(x[prueba])[:, 1]
        salida[nombre] = {
            "auc": float(roc_auc_score(y, prob)),
            "exactitud_balanceada": float(balanced_accuracy_score(y, prob >= 0.5)),
        }
    salida["prevalencia"] = float(y.mean())
    salida["bloques"] = len(np.unique(grupos))
    return salida


def densidad_kernel(
    xy: np.ndarray, pesos: np.ndarray, ancho_m: float = ANCHO_KERNEL_M
) -> np.ndarray:
    """Densidad kernel gaussiana ponderada (personas por km²) evaluada en los mismos puntos."""
    con_peso = pesos > 0
    if not con_peso.any():
        raise ErrorDatos("No hay pesos positivos para la densidad kernel")
    kde = KernelDensity(bandwidth=ancho_m, kernel="gaussian")
    kde.fit(xy[con_peso], sample_weight=pesos[con_peso])
    densidad = np.exp(kde.score_samples(xy)) * pesos[con_peso].sum()
    return np.asarray(densidad * 1e6, dtype=float)


def reserva_federal(recta_m: np.ndarray, rural: np.ndarray) -> np.ndarray:
    """Desierto según la Reserva Federal: más de 3,2 km urbano o 16,1 km rural en línea recta."""
    return np.where(rural, recta_m > RADIO_FED_RURAL_M, recta_m > RADIO_FED_URBANO_M)
