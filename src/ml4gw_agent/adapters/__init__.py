from .aframe import AframeAdapter
from .amplfi import AmplfiAdapter
from .base import AdapterOutcome, ExecutionContext, SkillAdapter
from .builtin import BuiltinAdapter
from .buoy import BuoyCLIAdapter
from .gwosc import GWOSCFetchAdapter
from .mock import MockAdapter
from .strain import StrainInspectAdapter

# Entry points a ``python`` adapter manifest may name. Adding a real adapter
# means registering it here; the registry cannot instantiate arbitrary code.
PYTHON_ADAPTERS: dict[str, type[SkillAdapter]] = {
    "gwosc_fetch": GWOSCFetchAdapter,
    "strain_inspect": StrainInspectAdapter,
    "aframe_inference": AframeAdapter,
    "amplfi_inference": AmplfiAdapter,
}

__all__ = [
    "PYTHON_ADAPTERS",
    "AdapterOutcome",
    "AframeAdapter",
    "AmplfiAdapter",
    "BuoyCLIAdapter",
    "BuiltinAdapter",
    "ExecutionContext",
    "GWOSCFetchAdapter",
    "MockAdapter",
    "SkillAdapter",
    "StrainInspectAdapter",
]
