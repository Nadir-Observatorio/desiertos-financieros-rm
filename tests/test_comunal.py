from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from desiertos.comunal import leer_sae
from desiertos.errores import ErrorDatos


def _guardar(tmp_path: Path, filas: list[list[object]]) -> Path:
    ruta = tmp_path / "sae.xlsx"
    pd.DataFrame(filas).to_excel(ruta, header=False, index=False)
    datos = ruta.read_bytes()
    (tmp_path / "procedencia.toml").write_text(
        f'[[archivo]]\nnombre = "sae.xlsx"\nbytes = {len(datos)}\n'
        f'sha256 = "{hashlib.sha256(datos).hexdigest()}"\n',
        encoding="utf-8",
    )
    return ruta


def test_leer_sae(tmp_path: Path) -> None:
    filas: list[list[object]] = [
        ["Estimaciones", None, None, None, None, None, None, None, None, None],
        [None] * 10,
        ["Código", "Región", "Nombre comuna", "Pob", "N", "Tasa", "LI", "LS", "Casen", "Tipo"],
        [13101, "RM", "Santiago", 1000, 50, 0.05, 0.04, 0.06, "Sí", "Directa y Sintética"],
        [13102, "RM", "Cerrillos", 800, 80, 0.10, 0.08, 0.12, "No", "Sintética"],
        ["(*) nota al pie", None, None, None, None, None, None, None, None, None],
    ]
    tabla = leer_sae(_guardar(tmp_path, filas), "ing")
    assert tabla["cut"].tolist() == [13101, 13102]
    assert tabla["ing_tasa"].tolist() == [0.05, 0.10]
    assert tabla["ing_tipo"].iloc[1] == "Sintética"


def test_leer_sae_sin_titulos_falla(tmp_path: Path) -> None:
    with pytest.raises(ErrorDatos):
        leer_sae(_guardar(tmp_path, [["nada"]]), "ing")
