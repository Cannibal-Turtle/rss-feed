# host_utils/__init__.py
from .host_dragonholic import DRAGONHOLIC_UTILS
from .host_mistmint import MISTMINT_UTILS

# Compatibility: keep a default UA/headers for callers that import these
UA_STR = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
DEFAULT_HEADERS = {"User-Agent": UA_STR}

_REGISTRY = {
    "Dragonholic": DRAGONHOLIC_UTILS,
    "Mistmint Haven": MISTMINT_UTILS,
}

def get_host_utils(host: str):
    try:
        return _REGISTRY[host]
    except KeyError:
        raise KeyError(f"Unknown or unimplemented host: {host!r}")
