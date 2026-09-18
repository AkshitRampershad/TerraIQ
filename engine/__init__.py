"""TerraIQ deterministic zoning envelope engine.

Nothing in this package calls a language model. Everything here is
computed, reproducible, and traceable to a cited code section -- which is
what makes the result defensible to a plan reviewer, and what makes any
downstream compliance proof mean something.
"""

from engine.rules import Provenance, RuleBundle, RuleError, RuleValue
from engine.parcel import EdgeKind, Overlay, Parcel
from engine.envelope import Envelope, compute_envelope
from engine.program import Program, compute_program
from engine.report import render_report
from engine.validate import Violation, validate_concept

__all__ = [
    "Provenance",
    "RuleBundle",
    "RuleError",
    "RuleValue",
    "EdgeKind",
    "Overlay",
    "Parcel",
    "Envelope",
    "compute_envelope",
    "Program",
    "compute_program",
    "render_report",
    "Violation",
    "validate_concept",
]
