# host_utils/__init__.py
"""Host utility registry.

Host modules are loaded lazily so a script that only needs Mistmint does not
also need Dragonholic/TITV-only dependencies at import time.
"""

from importlib import import_module
from typing import Any

# Compatibility: keep a default UA/headers for callers that import these.
UA_STR = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
DEFAULT_HEADERS = {"User-Agent": UA_STR}

# host name -> (relative module path, exported utils name)
_HOST_LOADERS = {
    "Dragonholic": (".host_dragonholic", "DRAGONHOLIC_UTILS"),
    "Mistmint Haven": (".mistmint_haven", "MISTMINT_UTILS"),
    "Tales in the Valley": (".host_titv", "TALES_IN_THE_VALLEY_UTILS"),
}

# Optional aliases/case forgiveness for callers.
_HOST_ALIASES = {name.casefold(): name for name in _HOST_LOADERS}

_CACHE: dict[str, Any] = {}


def _canonical_host(host: str) -> str:
    raw = (host or "").strip()
    return _HOST_ALIASES.get(raw.casefold(), raw)


def get_host_utils(host: str):
    """Return the utility dictionary for one host, importing only that host."""
    host = _canonical_host(host)

    if host not in _HOST_LOADERS:
        known = ", ".join(sorted(_HOST_LOADERS))
        raise KeyError(f"Unknown or unimplemented host: {host!r}. Known hosts: {known}")

    if host not in _CACHE:
        module_path, attr_name = _HOST_LOADERS[host]
        module = import_module(module_path, __name__)
        _CACHE[host] = getattr(module, attr_name)

    return _CACHE[host]


def __getattr__(name: str):
    """Backwards-compatible lazy access for old imports.

    This keeps `from host_utils import MISTMINT_UTILS` working without eagerly
    importing every host module.
    """
    if name == "DRAGONHOLIC_UTILS":
        return get_host_utils("Dragonholic")
    if name == "MISTMINT_UTILS":
        return get_host_utils("Mistmint Haven")
    if name == "TALES_IN_THE_VALLEY_UTILS":
        return get_host_utils("Tales in the Valley")
    raise AttributeError(name)


__all__ = [
    "get_host_utils",
    "UA_STR",
    "DEFAULT_HEADERS",
    "DRAGONHOLIC_UTILS",
    "MISTMINT_UTILS",
    "TALES_IN_THE_VALLEY_UTILS",
]
