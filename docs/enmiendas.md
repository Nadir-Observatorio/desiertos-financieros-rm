# Enmiendas al protocolo sellado

Protocolo: docs/protocolo.md, sellado el 2026-11-09, sha256
83dde005a8aa61f75cfab7dbe211772fd364ffec706b7dc2a0c8d170d10cc344. El texto sellado no se edita;
cada enmienda se lee junto a él.

## E-1. Caja Vecina y red de BancoEstado en el indicador principal

- Fecha: 2026-11-10. Momento: antes de descargar y de cruzar cualquier dato.
- Motivo: la página pública del localizador de BancoEstado entrega a cualquier visitante tres CSV
  con coordenadas (Caja Vecina, sucursales y BancoEstado Express). Ya no depende de una solicitud
  escrita. Antes de esta enmienda solo se vieron las cabeceras y el número de filas de esos archivos;
  ninguna coordenada.
- Cambia la sección 2.1:
  - Indicador principal: cualquier punto, sea sucursal o cajero de OpenStreetMap, punto Caja Vecina
    activo, sucursal de BancoEstado o BancoEstado Express.
  - Indicador secundario: banca tradicional (sucursales y cajeros de OpenStreetMap, sucursales de
    BancoEstado), sin Caja Vecina. Le siguen sucursales solas y cajeros solos.
  - Caja Vecina deja de ser solo un escenario exploratorio.
  - "Activo" se define con la columna de estado del archivo; la regla exacta se registra al ingresar
    el original, antes de calcular distancias.
- Tratamiento del archivo de BancoEstado:
  - Se descarga una sola vez y se guarda el original con su procedencia.
  - Al ingresar se descartan las columnas comerciales internas (puntaje, score, categoría y
    agrupación por transacciones). No entran a ningún derivado.
  - Nunca se publica la lista de puntos; solo agregados por celda y tiempos de viaje.
  - Licencia: no declarada; se registra así.
- Completitud (sección 2.2): se mantiene para los puntos de OpenStreetMap. La red de BancoEstado es la
  fuente oficial y no se filtra.
- Hipótesis y corrección de Holm: sin cambios (H1, H2 y H3).

## E-2. Grupo de edad de H2 (condicional)

- Fecha: 2026-11-10. Momento: antes de descargar y de cruzar cualquier dato.
- Motivo: un análisis público de la base manzana-entidad del Censo 2024 solo muestra el grupo de
  60 años y más.
- Regla: si el diccionario de variables del INE confirma que la base no trae 65 años y más al nivel
  manzana-entidad, H2 usa 60 años y más con la misma prueba y el mismo umbral. Si el diccionario sí
  trae 65 años y más, rige el protocolo sellado y esta enmienda queda sin efecto. El resultado de la
  comprobación se anota aquí con el nombre exacto de la variable.

### E-2, comprobación (2026-11-10)

El diccionario del INE (diccionario_variables_glosas_censo2024.xlsx, sha256
4a73cf474a13b60078edf263808089a536212bb69ebc3858257f091c5f2d2080) trae los grupos n_edad_0_5,
n_edad_6_13, n_edad_14_17, n_edad_18_24, n_edad_25_44, n_edad_45_59 y n_edad_60_mas. No hay 65 años y
más. E-2 queda activa: H2 usa la variable n_edad_60_mas.

## E-3. Calidad de las coordenadas de BancoEstado

- Fecha: 2026-11-10. Momento: antes de cruzar cualquier punto con población. Hasta aquí solo se
  inspeccionaron los formatos de las coordenadas y se contaron las filas inválidas.
- Motivo: de los 13.138 puntos Caja Vecina vigentes en la Región Metropolitana, 3.857 (29 %) traen
  coordenadas que no se leen como latitud y longitud válidas. Los patrones son tres: separadores de
  miles insertados por una planilla (-3.367.901), separador decimal perdido (-33439664) y notación
  científica (-3,67E+11), que perdió precisión. Todas las filas traen dirección y comuna.
- Regla (código: src/desiertos/ingesta/coordenadas.py):
  1. Un valor con a lo sumo un separador y valor absoluto entre 17 y 110 es original.
  2. Si no, un valor de dígitos y separadores con al menos 5 dígitos se repara: se quitan los
     separadores y la coma decimal se reinserta después de los dos primeros dígitos.
  3. La notación científica no se repara.
  4. Todo punto, original o reparado, se acepta solo si cae en la caja de la región
     (longitud -71,8 a -69,7; latitud -34,4 a -32,8) y a 1 km o menos de una manzana o entidad
     censal de la comuna que declara la fila (nombres comparados sin tildes ni signos).
  5. Lo que no cumple pasa a una cola de geocodificación por dirección.
- Geocodificación: la sección 8 del protocolo se amplía. La calidad del geocodificador se mide
  también con los puntos aceptados con coordenada original, que tienen dirección y coordenada
  conocida; la muestra de OpenStreetMap queda como complemento. El geocodificador se elige y se
  registra antes de geocodificar la cola.
- Hasta que la cola se geocodifique, sus puntos no entran al indicador principal y se informa
  cuántos son. Como sensibilidad se informa el resultado sin los puntos reparados.

### E-3, aplicación (2026-11-10)

Caja Vecina RM: 9.153 aceptados con coordenada original, 3.289 aceptados reparados y 696 en la
cola (495 lejos de su comuna, de ellos 110 con coordenada original; 99 inutilizables; 97 fuera de
la región; 5 con comuna no reconocida). Sucursales de BancoEstado (122) y BancoEstado Express (61):
todas aceptadas con coordenada original.

### E-3, geocodificador elegido y medido (2026-11-10)

- Geocodificador propio (src/desiertos/geocodificacion.py) contra direcciones y calles de
  OpenStreetMap de la región: extracto de Geofabrik con datos hasta el 2026-11-08T21:21Z, MD5
  6f86e4a43d9031fe58d868cb92432e06 comprobado, recortado a la caja de la región (ways con al menos
  un nodo dentro; sin relaciones). Métodos en orden: exacta, interpolada, numero_cercano, calle.
- Muestra: los 9.153 puntos Caja Vecina aceptados con coordenada original, partidos al azar en dos
  mitades (semilla 2026). Las reglas de limpieza de nombres se ajustaron solo con la mitad de
  desarrollo. La mitad de prueba se midió una sola vez, con el código final.
- Primera medición, antes de cualquier ajuste y sobre toda la muestra: 68 % con resultado, 47 %
  a 100 m o menos, mediana 38 m.
- Resultado en la mitad de prueba (4.627 puntos): 84,5 % con resultado; 55,4 % a 100 m o menos
  (sobre el total, contando los sin resultado como fallo); mediana 44 m; p90 975 m.
  Por método (mediana y p90): exacta 10 y 73 m (470); interpolada 24 y 179 m (1.545);
  numero_cercano 97 y 459 m (282); calle 140 y 2.190 m (1.613).
- Cola de 696 puntos: 86 exacta, 180 interpolada, 42 numero_cercano, 141 calle, 247 sin resultado.
  Qué métodos se aceptan para el análisis se decide y se registra aquí antes de cruzar con
  población.
- Decisión (2026-11-10, aprobada por el dueño, antes de cruzar con población): para el análisis se
  aceptan solo los métodos exacta e interpolada (p90 de 73 y 179 m, frente a unos 900 m que se
  recorren en 15 minutos a 3,6 km/h). Entran 266 de los 696 puntos de la cola; los 430 restantes
  (3,3 % de la red Caja Vecina de la región) quedan fuera y se informan. Sensibilidad: agregar
  numero_cercano (42 puntos más).
- Capa unida de puntos (src/desiertos/puntos.py): 14.437 puntos (Caja Vecina 12.708, sucursales
  BancoEstado 122, BancoEstado Express 61, OSM bank 911, OSM atm 635); sensibilidad 14.479.
- Límite declarado: la red de BancoEstado se filtró por región 13, de modo que sus puntos en
  regiones vecinas no cuentan como destino para celdas de borde. Los puntos de OSM sí incluyen la
  franja vecina dentro de la caja del recorte.

## E-4. Banca tradicional desde los localizadores de cada banco

- Fecha: 2026-11-10. Momento: después de aplicar la regla P4 y antes de calcular cualquier tiempo de
  viaje o de cruzar puntos con población.
- Resultado de P4 (src/desiertos/completitud.py; CMF, sistema BEST, agosto 2026; tabla en
  derivados/desiertos/completitud_osm_cmf_rm.csv): ninguna de las 52 comunas es apta. En la región,
  OSM trae 693 oficinas bancarias frente a 500 sucursales de la CMF (razón 1,39) y 407 cajeros
  frente a 3.131 (razón 0,13). El exceso de oficinas incluye marcas que ya no existen (BBVA,
  Corpbanca, Edwards-Citi). Siete comunas no tienen ningún cajero en OSM.
- Efecto medido en el indicador principal, en línea recta y con 900 m como umbral: sacar los puntos
  de OSM deja a 23.004 personas más (0,3 % de la población) sobre el umbral. Es una medición
  exploratoria; no reemplaza el cálculo por red.
- Decisión (aprobada por el dueño): la capa de banca tradicional del indicador secundario se arma
  con los localizadores públicos de cada banco, no con OSM.
  - Bancos: BancoEstado (cajeros; sus sucursales ya están), Banco de Chile, BCI, Santander,
    Scotiabank, Itaú y Falabella. Según la CMF suman 458 de las 500 sucursales (91,6 %) y 3.103 de
    los 3.131 cajeros (99,1 %) de la región. Banco BICE (20 sucursales, 20 cajeros) se agrega si su
    localizador lo permite.
  - Antes de descargar se revisan el robots.txt y los términos de uso de cada sitio y se registran
    aquí. Un banco cuyo sitio lo prohíba queda fuera, y sus sucursales y cajeros se cuentan solo a
    nivel comunal con las cifras de la CMF.
  - Cada original entra al banco de datos con su procedencia. No se publica la lista de puntos, solo
    agregados por celda y tiempos de viaje, igual que con BancoEstado.
  - Validación: la regla P4 se aplica a la nueva capa, por comuna y además por banco en el total
    regional, con los mismos límites (0,8 a 1,25). Las comunas que no pasen se informan aparte.
  - Bancos menores no cubiertos (42 sucursales y 28 cajeros en la región): se informan como faltante
    declarado.
- El indicador principal no cambia con esta enmienda. Si también pasa a usar la capa de los
  localizadores se decide y se registra aquí cuando la capa esté validada, antes de calcular
  tiempos de viaje.

### E-4, revisión de robots.txt y decisión (2026-11-10)

- robots.txt bajado desde el PC con agente identificado (archivos y procedencia en
  bruto/bancos-localizadores/revision-robots). BancoEstado no publica robots.txt; BCI y Banco
  Falabella permiten todo (Falabella excluye los PDF); Scotiabank excluye rutas internas; Itaú
  excluye /api/ y /nextapi/. Banco de Chile y Santander responden 403 a clientes que no son un
  navegador; BICE cerró la conexión.
- Cobertura máxima de los bancos descargables según la CMF: 256 de 500 sucursales (51 %) y 1.456 de
  3.131 cajeros (46,5 %). No alcanza para un indicador por puntos.
- Decisión (aprobada por el dueño): el indicador secundario (banca tradicional) se calcula a nivel
  comunal con las cifras de la CMF por cada 10.000 habitantes. Los localizadores permitidos se
  descargan y forman una capa por banco, validada contra la CMF por comuna y en el total regional;
  se usa en análisis por banco y no como indicador. No se descarga ningún sitio que bloquee a
  clientes automáticos ni ninguna ruta excluida por su robots.txt.

### E-4, localizadores descargados (2026-11-10)

Originales y procedencia en bruto/bancos-localizadores/. Ninguno de los tres sitios publica
términos de uso del sitio; la licencia se registra como no declarada.

| Banco | Fuente | Región Metropolitana | CMF (agosto 2026) |
|---|---|---|---|
| BCI | servicio del localizador público (sucursal y cajero), con coordenadas | 72 sucursales; 225 lugares con 261 cajeros | 70 y 204 |
| Banco Falabella | página pública de oficinas, con coordenadas | 31 oficinas; 120 lugares con cajero | 28 y 177 |
| Scotiabank | página pública de sucursales, solo dirección | 41 sucursales (sin cajeros) | 41 y 67 |

- BancoEstado: la propia página del localizador pide el archivo de cajeros (tipo=atm) y el
  servidor responde 404; los cajeros no están publicados. Quedan solo con las cifras de la CMF.
  Desde el 2026-11-10 el sitio también responde con su página de error a clientes que no son un
  navegador, incluso para los archivos ya guardados.
- Itaú: su sitio bloquea clientes automáticos (página de Imperva). Queda solo con la CMF.
- Los lugares con cajero de Falabella no se comparan uno a uno con la CMF, que cuenta equipos; un
  lugar puede tener varios. BCI informa el número de cajeros por lugar.
- Scotiabank se geocodifica con el geocodificador propio, con los mismos métodos aceptados (exacta e
  interpolada) de E-3.

### E-4, asignación de comuna, capa por banco e indicador principal (2026-11-10)

- Corrección de método: las huellas comunales son la unión de manzanas y entidades y no cubren
  calles ni plazas, de modo que un punto sobre la calle quedaba fuera de toda comuna. Desde aquí
  cada punto se asigna a la huella más cercana a 1 km o menos (la tolerancia de E-3). Con esa regla,
  P4 sobre OSM da 699 oficinas frente a 500 (1,40) y 418 cajeros frente a 3.131 (0,13); sigue sin
  comunas aptas. Las cifras anteriores de esta enmienda (693 y 407) quedan reemplazadas.
- Scotiabank (41 sucursales en la región): 18 exacta, 15 interpolada, 2 calle y 6 sin resultado.
  Entran las 33 con método aceptado. Una de las que fallan declara "Chicureo", que no es comuna.
- Validación por banco (salida en derivados/desiertos/completitud_localizadores_rm.csv), totales
  de la región frente a la CMF: BCI 72 sucursales frente a 70 y 259 cajeros frente a 204;
  Falabella 31 frente a 28 y 120 lugares con cajero frente a 177 equipos; Scotiabank 33 frente a 41.
  Comunas en rango (0,8 a 1,25) sobre las que tienen sucursal en la CMF: BCI 30 de 35, Falabella 16
  de 18, Scotiabank 13 de 20.
- Decisión (aprobada por el dueño): el indicador principal usa la fuente propia de BCI, Falabella,
  Scotiabank y BancoEstado, y quita de OSM los puntos cuyo operador es uno de esos bancos (código:
  src/desiertos/puntos.py, es_marca_con_fuente). OSM conserva Banco de Chile, Santander, Itaú, los
  bancos menores y los puntos sin operador. Capa resultante: 14.277 puntos (sensibilidad 14.319).

## E-5. Parámetros del cálculo de accesibilidad

- Fecha: 2026-11-10. Momento: antes de calcular cualquier tiempo de viaje.
- Motivo: el protocolo fija el motor (R5 vía r5py) y las velocidades a pie, pero no el tope de
  tiempo, el horario del transporte público ni el punto de origen de cada celda.
- Tope a pie: 120 minutos. Una celda sin punto a 120 minutos o menos queda censurada en 120,
  cuenta como desierto con cualquier umbral y se rotula. H3 se repite sin las celdas censuradas
  como sensibilidad. En línea recta, unas 2.200 personas (0,03 %) quedan a más de 7,2 km.
- Transporte público: martes 2026-11-17 (dentro de la vigencia del GTFS, del 2026-10-03 al
  2026-12-31, día hábil sin feriado), salidas de 10:00 a 11:00, mediana del tiempo en esa ventana.
  Sensibilidad: 7:00 a 8:00. Auto: misma fecha y hora, sin ventana.
- Origen: centro de la celda H3 (resolución 9, unos 174 m de lado), el mismo que ya trae la tabla de
  población.
- Cálculo por tramos: primero con tope de 30 minutos para todas las celdas; las que no alcanzan
  ningún punto se recalculan con el tope de 120. El resultado es el mismo que con un solo tope de
  120 y evita guardar miles de pares origen-destino por celda urbana.

## E-6. Calles privadas, resolución de auto y transporte público, y sensibilidad dasimétrica

- Fecha: 2026-11-10. Momento: después de calcular la accesibilidad a pie y antes de probar
  cualquier hipótesis.
- Resultado a pie (resolución 9, 3,6 km/h, tope 120): 5,9 % de la población a más de 15 minutos;
  4.557 celdas censuradas con 19.642 personas.
- Calles privadas. De las celdas censuradas, 1.080 (12.315 personas) tienen un punto a menos de
  3 km en línea recta. Causa principal: R5 no permite caminar por vías con access o foot igual a
  private, customers o permit (92.577 vías en el recorte, sobre todo calles internas de
  condominios y parcelas). Abrir esas vías recuperó 78 de 150 celdas de muestra, pero en toda la
  región subió la población sobre 15 minutos de 5,9 % a 6,1 %, porque los portones (nodos)
  siguen cerrados y aparecen calles sin salida. Decisión (aprobada por el dueño): la red principal
  respeta el acceso declarado en OSM; las celdas censuradas se informan aparte y es un límite
  declarado.
- Auto y transporte público: se calculan a resolución 8 (11.688 celdas). En una muestra de 1.500
  celdas de resolución 9, cada escenario tardó unos 4 a 5 minutos (unas 2,5 horas para la región).
  Siguen siendo descriptivos y cota superior (30 puntos candidatos más cercanos por celda).
- Sensibilidad dasimétrica (aprobada por el dueño). Las entidades rurales cubren 14.302 km²
  (93 % de la región); el 10 % más grande reparte 40.345 personas en 11.578 km². Antes de probar
  H1 se agrega una versión en que la población de cada entidad rural se reparte en proporción al
  área de los edificios de OSM dentro de ella; las entidades sin edificios y todas las manzanas
  urbanas conservan la ponderación por área. El método sellado sigue siendo el principal; H1 se
  informa con ambas versiones.

## E-7. Alcance de las hipótesis (sección 2.2)

- Fecha: 2026-11-10. Momento: antes de calcular H1, H2 y H3. Ya se conocían los resultados
  descriptivos de accesibilidad (E-6), no los de las hipótesis.
- Motivo: la sección 2.2 limita las hipótesis a las comunas aptas por completitud de OSM y, desde
  E-4, ninguna lo es. La regla se diseñó cuando OSM era la única fuente de puntos; hoy aporta 907 de
  los 14.277 puntos del indicador principal. Sin ningún punto de OSM la población a más de 15
  minutos a pie sube de 5,90 % a 6,31 % (29.957 personas).
- Decisión (aprobada por el dueño): H1, H2 y H3 se prueban con las celdas de todas las comunas; es
  la sensibilidad que la sección 2.2 ya pedía y pasa a ser el resultado principal. Se agrega como
  sensibilidad la capa sin OSM, de modo que los resultados quedan entre dos cotas. Se declara que
  el indicador es una cota superior de los desiertos respecto de la banca tradicional, porque los
  cajeros de Banco de Chile y Santander están subrepresentados (E-4).
- Sensibilidad dasimétrica (E-6) en las tres hipótesis, sin corrección de Holm: Holm se aplica solo
  a los tres tests principales.

## E-8. Regla de publicación por celda

- Fecha: 2026-11-10. Momento: antes de publicar cualquier producto. Resuelve el asunto abierto fuera
  del sello (tabla de población por celda).
- Decisión (aprobada por el dueño): se publican en resolución 9 solo las celdas con 50 personas o
  más; el resto se agrega a su celda padre de resolución 6 (población, población en desierto y
  proporción). Es la misma regla del observatorio Nadir (OBS-0003, D-5). Las celdas de 1 a 5
  personas identifican hogares rurales aislados.
- No se publican la lista de puntos de acceso (E-1) ni cifras comunales atribuidas a celdas. La
  tabla comunal se publica como tabla, sin dibujar límites comunales.
