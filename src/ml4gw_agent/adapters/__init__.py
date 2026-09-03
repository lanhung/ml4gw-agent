from .aframe import AframeAdapter
from .amplfi import AmplfiAdapter
from .base import AdapterOutcome, ExecutionContext, SkillAdapter
from .builtin import BuiltinAdapter
from .buoy import BuoyCLIAdapter
from .deepclean import DeepCleanApplicabilityAdapter
from .gwak import GWAKAdapter
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
    "deepclean_applicability": DeepCleanApplicabilityAdapter,
    "gwak_snakemake": GWAKAdapter,
}

__all__ = [
    "PYTHON_ADAPTERS",
    "AdapterOutcome",
    "AframeAdapter",
    "AmplfiAdapter",
    "BuoyCLIAdapter",
    "BuiltinAdapter",
    "DeepCleanApplicabilityAdapter",
    "ExecutionContext",
    "GWAKAdapter",
    "GWOSCFetchAdapter",
    "MockAdapter",
    "SkillAdapter",
    "StrainInspectAdapter",
]
