"""``gwak.scan`` placeholder that fails closed with the reason.

The upstream GWAK repository (reviewed 2026-09-03, see
``docs/UPSTREAM_REVIEW.md``) is a Snakemake training pipeline: it publishes
no inference entry point, no packaged release, and no pretrained weights at
an immutable revision. Without those, a real adapter cannot satisfy the
contract's ``immutable_model`` and ``compatible_preprocessing``
preconditions. Rather than invent an interface, this adapter reports the
gap so that plans requesting GWAK stop before execution.
"""

from __future__ import annotations

from typing import Any

from ..errors import AdapterUnavailableError
from .base import AdapterOutcome, ExecutionContext, SkillAdapter

BLOCKER = (
    "GWAK has no reviewed inference interface: upstream ML4GW/gwak ships a "
    "Snakemake training workflow without a packaged scan entry point or "
    "published model weights at an immutable revision; the gwak.scan adapter "
    "stays fail-closed until those exist (docs/UPSTREAM_REVIEW.md)"
)


class GWAKAdapter(SkillAdapter):
    name = "gwak-fail-closed-v0.3"

    def probe(self) -> str:
        return "missing: reviewed GWAK inference interface"

    def preflight(self, context: ExecutionContext) -> list[str]:
        raise AdapterUnavailableError(BLOCKER)

    def describe_invocation(
        self, context: ExecutionContext
    ) -> tuple[list[str] | None, dict[str, Any]]:
        return None, {"adapter": self.name, "blocker": BLOCKER}

    def execute(self, context: ExecutionContext) -> AdapterOutcome:
        raise AdapterUnavailableError(BLOCKER)
