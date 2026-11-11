"""Desiertos financieros de Chile: acceso físico a sucursales, cajeros y Caja Vecina."""

__all__ = ["CRS_GEOGRAFICO", "CRS_METRICO_RM", "RESOLUCION_ANALISIS"]

# Archivo en grados, medición en metros (regla del banco de datos).
CRS_GEOGRAFICO = "EPSG:4326"
# UTM 19 S cubre la Región Metropolitana completa.
CRS_METRICO_RM = "EPSG:32719"
# Protocolo sellado, sección 3: resolución 9 para el análisis.
RESOLUCION_ANALISIS = 9
