from __future__ import annotations

from pathlib import Path

import pytest

from desiertos.errores import ErrorConfiguracion, ErrorProcedencia
from desiertos.procedencia import sha256_archivo, verificar
from desiertos.rutas import VARIABLE_ENTORNO, cargar_rutas


def _registrar(carpeta: Path, nombre: str, huella: str) -> None:
    (carpeta / "procedencia.toml").write_text(
        f'[[archivo]]\nnombre = "{nombre}"\nsha256 = "{huella}"\n', encoding="utf-8"
    )


def test_verificar_ok(tmp_path: Path) -> None:
    archivo = tmp_path / "dato.bin"
    archivo.write_bytes(b"abc")
    _registrar(tmp_path, "dato.bin", sha256_archivo(archivo))
    assert verificar(archivo) == sha256_archivo(archivo)


def test_verificar_detecta_cambio(tmp_path: Path) -> None:
    archivo = tmp_path / "dato.bin"
    archivo.write_bytes(b"abc")
    _registrar(tmp_path, "dato.bin", "0" * 64)
    with pytest.raises(ErrorProcedencia):
        verificar(archivo)


def test_verificar_sin_registro(tmp_path: Path) -> None:
    archivo = tmp_path / "dato.bin"
    archivo.write_bytes(b"abc")
    _registrar(tmp_path, "otro.bin", "0" * 64)
    with pytest.raises(ErrorProcedencia):
        verificar(archivo)


def test_rutas_desde_entorno(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(VARIABLE_ENTORNO, str(tmp_path))
    rutas = cargar_rutas()
    assert rutas.derivados == tmp_path / "derivados" / "desiertos"


def test_rutas_desde_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(VARIABLE_ENTORNO, raising=False)
    config = tmp_path / "configuracion.toml"
    config.write_text(f'[rutas]\nbanco = "{tmp_path.as_posix()}"\n', encoding="utf-8")
    assert cargar_rutas(config).banco == tmp_path


def test_rutas_banco_inexistente(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(VARIABLE_ENTORNO, str(tmp_path / "no-existe"))
    with pytest.raises(ErrorConfiguracion):
        cargar_rutas()
