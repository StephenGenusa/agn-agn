"""Provider registry."""

from callsigns.errors import ValidationError
from callsigns.providers.base import Column, Mode, ModeKind, ModeSpec, Provider

__all__ = [
    "Column",
    "Mode",
    "ModeKind",
    "ModeSpec",
    "Provider",
    "all_providers",
    "get_provider",
    "provider_keys",
    "register",
]

_REGISTRY: dict[str, type[Provider]] = {}


def register(cls: type[Provider]) -> type[Provider]:
    """Register a provider class under its ``key``.

    Usable as a class decorator.

    Args:
        cls: The provider class to register.

    Returns:
        The class unchanged.

    Raises:
        ValueError: Something is already registered under this key.
    """
    if cls.key in _REGISTRY:
        raise ValueError(f"provider key {cls.key!r} is already registered")
    _REGISTRY[cls.key] = cls
    return cls


def provider_keys() -> tuple[str, ...]:
    """Return every registered provider key, sorted."""
    return tuple(sorted(_REGISTRY))


def get_provider(key: str) -> Provider:
    """Instantiate the provider registered under a key.

    Args:
        key: The provider identifier given on the command line.

    Returns:
        A new provider instance.

    Raises:
        ValidationError: No provider is registered under this key.
    """
    try:
        cls = _REGISTRY[key]
    except KeyError:
        known = ", ".join(provider_keys()) or "none"
        raise ValidationError(
            f"unknown provider {key!r}; registered providers: {known}"
        ) from None
    return cls()


def all_providers() -> tuple[Provider, ...]:
    """Instantiate every registered provider, in key order."""
    return tuple(_REGISTRY[key]() for key in provider_keys())
