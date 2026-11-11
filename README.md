# Desiertos financieros de Chile

Estudio del acceso físico a sucursales bancarias, cajeros y puntos Caja Vecina en la Región
Metropolitana: dónde vive la población sin acceso razonable, quiénes son y dónde convendría abrir
puntos nuevos. Autor: Camilo López Barra, geógrafo (Universidad de Concepción).

El protocolo se selló antes de cruzar datos: [docs/protocolo.md](docs/protocolo.md)
(sha256 `83dde005a8aa61f75cfab7dbe211772fd364ffec706b7dc2a0c8d170d10cc344`). Los cambios
posteriores están en [docs/enmiendas.md](docs/enmiendas.md).

## Estado

En obtención de datos. La matriz de competencias con enlaces a su evidencia se completa a medida
que cada pieza exista; nada se declara logrado antes.

## Uso

```
python -m pip install -e .[dev]
copy configuracion.ejemplo.toml configuracion.toml
python -m desiertos poblacion
python -m desiertos red-bancoestado
```

Calidad: `ruff check .`, `ruff format --check .`, `mypy src tests` y `pytest`, todos en cero.

## Visor

`python -m desiertos visor` escribe `visor/` (index.html, datos.json y vendor/) desde los derivados,
lista para GitHub Pages. Ninguna cifra se escribe a mano: antes de escribir, la orden comprueba que
la población en desierto coincida con el registro de accesibilidad y que la diferencia rural menos
urbano reproduzca H1. Aplica la regla de publicación E-8 (celdas de resolución 9 con 50 personas o
más; el resto agregado a resolución 6 u oculto) y no publica puntos ni límites comunales. d3 7.8.5
(ISC) y h3-js 4.1.0 (Apache 2.0) van copiadas en `visor/vendor/` y fijadas por sha256.

## Datos y licencias

| Fuente | Licencia | Uso |
|---|---|---|
| INE, Censo de Población y Vivienda 2024, base manzana-entidad | CC BY-SA 4.0 | Población por celda H3 |
| BancoEstado, localizador público de la red de atención | No declarada | Solo agregados; no se publica la lista de puntos |
| OpenStreetMap | ODbL | Puntos y red vial |
| DTPM, GTFS | No declarada | No se redistribuye |

Código bajo licencia MIT.
