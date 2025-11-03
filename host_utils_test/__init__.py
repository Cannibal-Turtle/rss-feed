# host_utils/__init__.py
from typing import Dict, Callable
from .dragonholic import DRAGONHOLIC_UTILS
from .mistmint import MISTMINT_UTILS

_REGISTRY: Dict[str, Dict[str, Callable]] = {
    "Dragonholic": DRAGONHOLIC_UTILS,
    "Mistmint Haven": MISTMINT_UTILS,
}

def get_host_utils(host: str) -> Dict[str, Callable]:
    return _REGISTRY.get(host, {})
