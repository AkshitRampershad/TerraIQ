"""Machine-readable zoning rule bundles.

The central design constraint of TerraIQ: a number that cannot name the code
section it came from is not usable for anything downstream. Every value in a
bundle is a `RuleValue` carrying a citation and a provenance marker recording
how much trust it has earned:

    placeholder    -- a structural stand-in. Nobody has read the ordinance.
    llm_extracted  -- a model parsed it out of the ordinance text. Unreviewed.
    human_verified -- a person checked it against the published ordinance.

Only `human_verified` values may be used when the engine runs in strict mode.
Everything else is demo-grade and the report says so on every page.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class RuleError(ValueError):
    """Raised when a rule bundle is malformed or a required rule is missing."""


class Provenance(str, Enum):
    PLACEHOLDER = "placeholder"
    LLM_EXTRACTED = "llm_extracted"
    HUMAN_VERIFIED = "human_verified"

    @property
    def trusted(self) -> bool:
        return self is Provenance.HUMAN_VERIFIED

    @property
    def label(self) -> str:
        return {
            Provenance.PLACEHOLDER: "PLACEHOLDER - not checked against the ordinance",
            Provenance.LLM_EXTRACTED: "MACHINE-EXTRACTED - awaiting human review",
            Provenance.HUMAN_VERIFIED: "verified",
        }[self]


@dataclass(frozen=True)
class RuleValue:
    """One regulated quantity, traceable to the ordinance it came from.

    A `value` of None means the district does not regulate this quantity,
    which is materially different from regulating it at zero. The engine
    treats an unregulated maximum as "no cap" and an unregulated minimum as
    "no floor"; it never silently substitutes 0.
    """

    key: str
    value: float | None
    unit: str
    citation: str
    provenance: Provenance = Provenance.PLACEHOLDER
    source_url: str | None = None
    verified_by: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if not self.citation or not self.citation.strip():
            raise RuleError(
                f"rule {self.key!r} has no citation -- every regulated value must "
                f"name the code section it came from"
            )
        if self.value is not None and not isinstance(self.value, (int, float)):
            raise RuleError(f"rule {self.key!r} value must be numeric or null")
        if self.value is not None and self.value < 0:
            raise RuleError(f"rule {self.key!r} value must not be negative")

    @property
    def regulated(self) -> bool:
        return self.value is not None

    @property
    def trusted(self) -> bool:
        return self.provenance.trusted

    def __str__(self) -> str:
        if not self.regulated:
            return f"{self.key}: not regulated ({self.citation})"
        suffix = "" if self.trusted else f"  [{self.provenance.label}]"
        return f"{self.key}: {self.value:g} {self.unit}{suffix}"


@dataclass(frozen=True)
class RuleBundle:
    """The dimensional standards of one zoning district at one code version."""

    jurisdiction: str
    district: str
    district_name: str
    code_version: str
    effective_date: str
    source_url: str | None
    rules: dict[str, RuleValue]

    @classmethod
    def from_json(cls, path: str | Path) -> RuleBundle:
        path = Path(path)
        try:
            raw = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise RuleError(f"{path}: not valid JSON -- {exc}") from exc

        for required in ("jurisdiction", "district", "code_version", "effective_date"):
            if required not in raw:
                raise RuleError(f"{path}: rule bundle is missing required field {required!r}")

        rules: dict[str, RuleValue] = {}
        for key, spec in raw.get("rules", {}).items():
            if not isinstance(spec, dict):
                raise RuleError(f"{path}: rule {key!r} must be an object")
            try:
                provenance = Provenance(spec.get("provenance", "placeholder"))
            except ValueError as exc:
                raise RuleError(
                    f"{path}: rule {key!r} has unknown provenance "
                    f"{spec.get('provenance')!r}"
                ) from exc
            rules[key] = RuleValue(
                key=key,
                value=spec.get("value"),
                unit=spec.get("unit", ""),
                citation=spec.get("citation", ""),
                provenance=provenance,
                source_url=spec.get("source_url"),
                verified_by=spec.get("verified_by"),
                note=spec.get("note"),
            )

        return cls(
            jurisdiction=raw["jurisdiction"],
            district=raw["district"],
            district_name=raw.get("district_name", raw["district"]),
            code_version=raw["code_version"],
            effective_date=raw["effective_date"],
            source_url=raw.get("source_url"),
            rules=rules,
        )

    def require(self, key: str) -> RuleValue:
        """Fetch a rule the engine cannot proceed without."""
        if key not in self.rules:
            raise RuleError(
                f"{self.jurisdiction} {self.district}: rule {key!r} is absent from "
                f"the bundle. Add it with a citation, or record it explicitly as "
                f"unregulated (\"value\": null)."
            )
        return self.rules[key]

    def get(self, key: str) -> RuleValue | None:
        return self.rules.get(key)

    def number(self, key: str, default: float | None = None) -> float | None:
        """Numeric value of a rule, or `default` when absent or unregulated."""
        rule = self.rules.get(key)
        if rule is None or not rule.regulated:
            return default
        return float(rule.value)  # type: ignore[arg-type]

    def cite(self, key: str) -> str:
        rule = self.rules.get(key)
        return rule.citation if rule else "no citation on file"

    @property
    def untrusted(self) -> list[RuleValue]:
        """Every regulated value that no human has confirmed."""
        return [r for r in self.rules.values() if r.regulated and not r.trusted]

    @property
    def fully_verified(self) -> bool:
        return not self.untrusted

    def assert_verified(self) -> None:
        """Strict mode: refuse to proceed on unverified standards."""
        if self.fully_verified:
            return
        keys = ", ".join(sorted(r.key for r in self.untrusted))
        raise RuleError(
            f"{self.jurisdiction} {self.district}: strict mode requires every "
            f"standard to be human-verified against the ordinance. Unverified: {keys}"
        )
