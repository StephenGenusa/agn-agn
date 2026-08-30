"""Exporter registry."""

from callsigns.errors import ValidationError
from callsigns.exporters.base import Exporter, ExportOptions

__all__ = [
    "ExportOptions",
    "Exporter",
    "exporter_names",
    "get_exporter",
    "register_exporter",
]

_REGISTRY: dict[str, type[Exporter]] = {}


def register_exporter(cls: type[Exporter]) -> type[Exporter]:
    """Register an exporter class under its ``name``.

    Usable as a class decorator.

    Args:
        cls: The exporter class to register.

    Returns:
        The class unchanged.
    """
    _REGISTRY[cls.name] = cls
    return cls


def exporter_names() -> tuple[str, ...]:
    """Return every registered exporter name, sorted."""
    return tuple(sorted(_REGISTRY))


def get_exporter(name: str) -> Exporter:
    """Instantiate the exporter registered under a name.

    Args:
        name: The format identifier given on the command line.

    Returns:
        A new exporter instance.

    Raises:
        ValidationError: No exporter is registered under this name.
    """
    try:
        cls = _REGISTRY[name]
    except KeyError:
        known = ", ".join(exporter_names()) or "none"
        raise ValidationError(
            f"unknown format {name!r}; available formats: {known}"
        ) from None
    return cls()
