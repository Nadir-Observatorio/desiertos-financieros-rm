# Desiertos financieros de la Región Metropolitana

Línea de exclusión financiera de [Nadir](https://nadir-observatorio.github.io/), observatorio de
riesgo y exposición. Caso 1: Región Metropolitana.

¿Quién vive lejos de una sucursal bancaria, un cajero o un punto Caja Vecina, y qué tanto se
arreglaría con puntos nuevos bien ubicados? Estudio de la Región Metropolitana con datos públicos,
protocolo sellado antes de cruzar los datos y código reproducible.

**[Ver el visor](https://nadir-observatorio.github.io/desiertos-financieros-rm/visor/)**

Hecho por Camilo López Barra, geógrafo (Universidad de Concepción).

## Resultados

Una celda hexagonal poblada (H3, resolución 9) es desierto si el punto de acceso físico más
cercano está a más de 15 minutos caminando a 3,6 km/h por la red vial.

- **5,9 % de la población de la región, unas 429.400 personas, vive en desierto.**
- **H1 se sostiene.** El riesgo es mucho mayor en el campo: 70,5 % de la población de celdas
  rurales está en desierto, frente a 3,5 % de la urbana (diferencia de 67,0 puntos, IC 95 % 63,5
  a 70,1; p de Holm < 0,001). Aun así, por volumen la mayoría de las personas en desierto (58 %)
  vive en celdas urbanas.
- **H2 no se sostiene.** Las personas de 60 años y más no están sobrerrepresentadas en los
  desiertos; están subrepresentadas (razón 0,84, IC 95 % 0,78 a 0,93).
- **H3 se sostiene.** El tiempo a pie se agrupa en el espacio (I de Moran 0,897, p de Holm 0,002).
- **Exploratorio:** con 100 puntos nuevos ubicados por un modelo de cobertura máxima, la población
  en desierto bajaría de 5,9 % a 3,8 %. Con la definición de la Reserva Federal de EE. UU. (en línea
  recta, 3,2 km urbano y 16,1 km rural) la cifra cae a 0,02 %: el resultado depende de medir por
  la red y a pie.

## Competencias demostradas

| Competencia | Evidencia |
|---|---|
| Protocolo preregistrado e inferencia | [docs/protocolo.md](docs/protocolo.md), [docs/enmiendas.md](docs/enmiendas.md), [hipotesis.py](src/desiertos/hipotesis.py): bootstrap por bloques espaciales, corrección de Holm |
| Isócronas y accesibilidad por red | [accesibilidad.py](src/desiertos/accesibilidad.py), [motor_r5.py](src/desiertos/motor_r5.py): tiempos a pie, en auto y en transporte público (R5, GTFS) |
| Población en grilla H3 y dasimetría | [grilla.py](src/desiertos/grilla.py): reparto por área y sensibilidad con edificios de OpenStreetMap |
| Modelos de localización | [localizacion.py](src/desiertos/localizacion.py): cobertura máxima (MCLP) y p-mediana exactos con HiGHS |
| Hot spots y autocorrelación espacial | [exploratorio.py](src/desiertos/exploratorio.py): Getis-Ord Gi*, LISA, I de Moran |
| Regresión espacial y aprendizaje automático | [modelos.py](src/desiertos/modelos.py): modelos lag y error, perfiles comunales con k-medias, clasificación con validación cruzada por bloques |
| Geocodificación y control de calidad | [geocodificacion.py](src/desiertos/geocodificacion.py), [completitud.py](src/desiertos/completitud.py): reparación de coordenadas y completitud de OpenStreetMap contra la CMF |
| Extracción reproducible de datos | [ingesta/](src/desiertos/ingesta/): Censo, CMF, BancoEstado, localizadores de bancos, OpenStreetMap; cada original con su huella sha256 |
| Visualización web | [visor/](visor/) y [visor.py](src/desiertos/visor.py): visor estático sin cifras escritas a mano |
| Ingeniería de software | 123 pruebas (pytest), ruff y mypy estricto en cero |
| ArcGIS | No demostrado (sin licencia; la cartografía se hace en QGIS) |
| Power BI | No demostrado |

## Reproducir

```
python -m pip install -e .[dev]
copy configuracion.ejemplo.toml configuracion.toml
python -m desiertos poblacion
python -m desiertos red-bancoestado
python -m desiertos localizadores
python -m desiertos puntos
python -m desiertos completitud
python -m desiertos recorte-osm
python -m desiertos poblacion-dasimetrica
python -m desiertos accesibilidad
python -m desiertos hipotesis
python -m desiertos localizacion
python -m desiertos agrupamientos
python -m desiertos exploratorio
python -m desiertos visor
```

Los originales no están en el repositorio: cada orden los lee desde la carpeta indicada en
`configuracion.toml` y verifica su huella antes de usarlos. Calidad: `ruff check .`,
`ruff format --check .`, `mypy src tests` y `pytest`, todos en cero.

## Visor

`python -m desiertos visor` escribe `visor/` desde los derivados. Antes de escribir comprueba que
la población en desierto coincida con el registro de accesibilidad y que la diferencia rural menos
urbano reproduzca H1. Aplica la regla de publicación E-8: celdas de resolución 9 con 50 personas o
más; el resto se agrega a resolución 6 o se oculta. No publica puntos ni límites comunales: cada
comuna se rotula en su centro poblado. d3 7.8.5 (ISC) y h3-js 4.1.0 (Apache 2.0) van copiadas en
`visor/vendor/` y fijadas por sha256, junto con la tipografía Jost de Nadir (SIL Open Font
License 1.1). La página no carga nada de otros dominios.

## Datos y licencias

| Fuente | Licencia | Uso |
|---|---|---|
| INE, Censo de Población y Vivienda 2024, base manzana-entidad | CC BY-SA 4.0 | Población por celda H3 |
| BancoEstado, localizador público de la red de atención | No declarada | Solo agregados; no se publica la lista de puntos |
| Localizadores públicos de otros bancos | No declarada | Solo agregados |
| CMF, sistema BEST (sucursales y cajeros por comuna, agosto 2026) | Reproducción autorizada citando la fuente | Completitud y tasas comunales |
| Ministerio de Desarrollo Social y Familia, estimaciones SAE 2024 | No declarada | Pobreza comunal (exploratorio) |
| OpenStreetMap | ODbL | Puntos, red vial, edificios, ríos y autopistas del visor |
| DTPM, GTFS | No declarada | Escenarios de transporte público; no se redistribuye |

## Siguiente en esta línea

Exclusión financiera y digital: distancia al efectivo junto con conectividad, edad y pobreza, a
escala nacional, con su propio protocolo sellado antes de cruzar los datos.

Código bajo licencia MIT.
