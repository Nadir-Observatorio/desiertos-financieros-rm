"""Excepciones propias del paquete."""


class ErrorDesiertos(Exception):
    """Base de todos los errores del paquete."""


class ErrorConfiguracion(ErrorDesiertos):
    """Falta una ruta o un valor de configuración."""


class ErrorProcedencia(ErrorDesiertos):
    """Un original no coincide con su procedencia registrada."""


class ErrorDatos(ErrorDesiertos):
    """Un archivo no tiene la estructura esperada."""
