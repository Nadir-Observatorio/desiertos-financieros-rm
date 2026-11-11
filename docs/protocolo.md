# Protocolo del estudio: Desiertos financieros de Chile, Región Metropolitana

Autor: Camilo López Barra, geógrafo (Universidad de Concepción).
Redactado y sellado el 2026-11-09, antes de cruzar ningún dato. Ningún resultado de este estudio se
había calculado a esa fecha.

## 1. Pregunta y alcance

- Pregunta: dónde vive población sin acceso razonable a puntos financieros físicos en la Región
  Metropolitana, quiénes son (edad, ruralidad, vulnerabilidad) y dónde convendría abrir puntos nuevos.
- Alcance: Región Metropolitana. Chile rural queda para un protocolo posterior.
- Corte temporal: población del Censo 2024; puntos de un extracto de OpenStreetMap con fecha
  registrada; conteos de la CMF del mes más cercano al extracto. Las fechas reales se anotan en la
  procedencia de cada original y en el registro de corridas.

## 2. Datos y preparación

### 2.1 Puntos de acceso

- OpenStreetMap: amenity=bank (sucursal) y amenity=atm (cajero), nodos y áreas (para un área se usa
  su punto representativo). Se excluyen los objetos con prefijos disused: o abandoned: y los que
  tengan end_date anterior a la fecha del extracto.
- Duplicados: dos objetos del mismo tipo y del mismo operador a 25 m o menos cuentan como uno.
- Indicador principal: cualquier punto (sucursal o cajero). Secundarios: sucursales solas y cajeros
  solos.
- Caja Vecina: solo si BancoEstado la entrega por escrito. Entra como escenario exploratorio, nunca
  en las hipótesis, y se publica solo con su permiso.
- La capa de puntos se usa completa, sin recortar por comuna: una celda puede tener su punto más
  cercano en otra comuna.

### 2.2 Completitud de OpenStreetMap

- Por comuna: r_suc = sucursales en OSM / sucursales según la CMF; r_atm = cajeros en OSM / cajeros
  según la CMF.
- Una comuna es apta si 0,8 ≤ r_suc ≤ 1,25 y 0,8 ≤ r_atm ≤ 1,25. Si la CMF informa 0 de un tipo, la
  comuna es apta para ese tipo solo si OSM también tiene 0.
- Las hipótesis se contrastan solo con las celdas de origen de las comunas aptas. Las demás se
  informan aparte, rotuladas como "completitud insuficiente". Como sensibilidad se informan las
  hipótesis con todas las comunas.

### 2.3 Población

- Fuente: base manzana-entidad del Censo de Población y Vivienda 2024 (INE). El original se guarda
  en el banco de datos con su procedencia (origen, fecha, tamaño, sha256).
- Paso a H3: ponderación por área, con densidad uniforme dentro de cada manzana o entidad.
- Celdas pobladas: población asignada mayor o igual a 1. Solo ellas entran en el análisis.

### 2.4 Ruralidad

Campo AREA_C del Censo. Una celda es rural si más del 50 % de su población asignada proviene de
entidades rurales.

### 2.5 Edad

Población de 65 años y más desde la misma base. Si la base no la trae al nivel manzana-entidad, H2
se suspende y se registra una enmienda. No se sustituye por un dato comunal.

### 2.6 Vulnerabilidad

Pobreza por ingresos y multidimensional, estimaciones de áreas pequeñas (SAE) del Ministerio de
Desarrollo Social y Familia, nivel comunal. Solo en análisis exploratorio.

## 3. Unidad espacial

- Grilla H3 de resolución 9 para el análisis; resolución 8 como sensibilidad.
- Tablas por comuna con el código comunal del Censo. No se dibujan límites comunales.

## 4. Accesibilidad

- Motor: R5 mediante r5py, una sola red (extracto OSM de la región y GTFS de DTPM).
- Origen: centro de cada celda poblada, ajustado a la red.
- A pie: 3,6 km/h; sensibilidad 4,8 km/h.
- Auto y transporte público: descriptivos. Salida un martes hábil a las 10:00 dentro de la vigencia
  del GTFS, ventana de 60 minutos, mediana.
- Variable continua: tiempo a pie al punto más cercano, en minutos, con tope de 120.

### 4.1 Definición de desierto

- Una celda poblada es desierto si el tiempo a pie al punto más cercano es mayor que 15 minutos.
- Sensibilidad: umbrales de 10 y 20 minutos.
- Comparación externa (exploratoria): definición de la Reserva Federal de Estados Unidos por radio
  en línea recta desde el centro de la celda, 3,2 km para celdas urbanas y 16,1 km para celdas
  rurales.

## 5. Hipótesis confirmatorias

Unidad de inferencia: celdas pobladas, ponderadas por población.

- H1. Proporción de población en desierto en celdas rurales menos la proporción en celdas urbanas,
  en puntos porcentuales. Se sostiene si el efecto es mayor que 0 y su p ajustado es menor que 0,05.
- H2. Razón entre la proporción de personas de 65 años y más dentro de las celdas desierto y esa
  proporción en toda el área analizada. Se sostiene si la razón es mayor que 1 y su p ajustado es
  menor que 0,05.
- H3. I de Moran del logaritmo de (1 + tiempo a pie al punto más cercano), con vecindad de anillo 1
  de H3 entre celdas pobladas y 999 permutaciones. Se sostiene si I es mayor que 0 y su p ajustado
  es menor que 0,05.

Corrección por comparaciones múltiples: Holm, alfa familiar 0,05, sobre H1, H2 y H3.

La localización de puntos nuevos no es una hipótesis: un modelo de optimización no puede perder
contra una heurística dentro de su propio modelo. Va como escenarios exploratorios (sección 7).

## 6. Intervalos y autocorrelación

- Bootstrap por bloques: el bloque es la celda H3 de resolución 6. Si hay menos de 30 bloques con
  población rural, se usa la resolución 7. La resolución 5 se informa como sensibilidad.
- 2.000 réplicas, semilla fijada en el código y publicada. IC 95 % por percentiles.
- p unilateral: fracción de réplicas con efecto menor o igual que el valor nulo (0 en H1, 1 en H2).
- H3 usa su prueba de permutaciones, no el bootstrap.
- Diagnóstico: I de Moran de los residuos por celda de H1 y H2, informado.

## 7. Análisis exploratorio

Rotulado "exploratorio" en todo producto: densidad kernel; Gi* con Benjamini-Hochberg (q = 0,05);
LISA con 999 permutaciones; auto y transporte público; perfiles comunales por clustering; regresión
lineal frente a modelos espaciales (rezago y error) y GWR; clasificación de celdas en desierto o no
con validación cruzada por bloques espaciales; escenarios de localización con cobertura máxima
(MCLP) y p-mediana para varios valores de k, con su curva de cobertura; escenario con Caja Vecina.

## 8. Calidad de geocodificación

- Muestra: objetos financieros de OSM con dirección completa (addr:street y addr:housenumber) y
  coordenada propia.
- Se geocodifica la dirección y se compara con la coordenada de OSM.
- Métricas: tasa de acierto (resultado a 100 m o menos), error en metros (mediana y percentil 90) y
  tasa sin resultado.
- El geocodificador se elige en la etapa de obtención y se registra por enmienda. No se usa el
  servidor público de Nominatim para volumen.

## 9. Límites declarados

- Las celdas no son personas: un resultado por celda no dice nada de un individuo (falacia
  ecológica).
- Las cifras comunales (SAE, CMF) no se atribuyen a celdas.
- Sin Caja Vecina, el estudio mide el acceso a la banca tradicional.
- OSM puede omitir puntos o mantener puntos cerrados; se mide en 2.2 y se declara.
- La densidad uniforme dentro de las entidades rurales grandes es un supuesto.
- El filtro de completitud puede sesgar la muestra de comunas; por eso se informa la sensibilidad
  con todas.

## 10. Licencias por variable

| Variable | Fuente | Licencia |
|---|---|---|
| Puntos, red vial y tiempos derivados | OpenStreetMap | ODbL |
| Población, edad, ruralidad | INE, Censo 2024 | CC BY-SA 4.0 |
| Horarios de transporte | DTPM, GTFS | Sin licencia declarada; no se redistribuye |
| Conteos comunales | CMF | Por verificar |
| Pobreza comunal | MDSF, SAE | Por verificar |

Productos: tabla de accesibilidad por celda (ODbL); tabla de población y perfil por celda
(CC BY-SA 4.0), unibles por el identificador H3; mapas como obra producida con atribución a
OpenStreetMap, bajo CC BY-SA 4.0. Código bajo MIT.

## 11. Enmiendas

Todo cambio posterior a este sello es una enmienda E-n, con fecha, motivo y si ocurre antes o después
de ver resultados. El texto sellado no se edita.
