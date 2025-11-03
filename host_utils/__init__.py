# host_utils/__init__.py
from typing import Dict, Callable
from .host_dragonholic import DRAGONHOLIC_UTILS
from .host_mistmint import MISTMINT_UTILS

_REGISTRY: Dict[str, Dict[str, Callable]] = {
    "Dragonholic": DRAGONHOLIC_UTILS,
    "Mistmint Haven": MISTMINT_UTILS,
}

def get_host_utils(host: str) -> Dict[str, Callable]:
    try:
        return _REGISTRY[host]
    except KeyError:
        # clearer than returning {}
        raise KeyError(f"Unknown or unimplemented host: {host!r}")
