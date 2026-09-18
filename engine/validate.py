"""Compliance check for a proposed concept against a computed envelope.

This is the guard rail that makes it safe to let a language model near the
design step. The model may propose; it may not decide. Anything it returns is
checked here against the envelope the engine computed, and a proposal that
exceeds a limit is reported as a violation rather than rendered as a plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shapely.geometry import Polygon

from engine.envelope import Envelope
from engine.program import Program


@dataclass(frozen=True)
class Violation:
    """A proposed value that exceeds what the envelope permits."""

    field: str
    proposed: float | str
    limit: float | str
    rule: str
    citation: str

    def __str__(self) -> str:
        return (
            f"{self.field}: proposed {self.proposed}, limit {self.limit} "
            f"({self.rule}; {self.citation})"
        )


def _number(concept: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key in concept and concept[key] is not None:
            try:
                return float(concept[key])
            except (TypeError, ValueError):
                return None
    return None


def validate_concept(
    concept: dict[str, Any],
    envelope: Envelope,
    program: Program | None = None,
    *,
    footprint_tolerance_ft: float = 0.5,
) -> list[Violation]:
    """Check a proposed concept against the envelope. Empty list means it fits."""
    violations: list[Violation] = []
    b = envelope.bundle

    floors = _number(concept, "floors", "stories")
    if floors is not None and envelope.stories is not None and floors > envelope.stories:
        violations.append(
            Violation(
                field="floors",
                proposed=int(floors),
                limit=envelope.stories,
                rule="height / story limit",
                citation=b.cite("max_height_ft"),
            )
        )

    area = _number(concept, "building_area_sft", "building_area_sf", "gross_floor_area_sf")
    if area is not None and program is not None and program.gross_floor_area_sf is not None:
        if area > program.gross_floor_area_sf + 1.0:
            det = program.determination("gross_floor_area")
            violations.append(
                Violation(
                    field="building_area_sft",
                    proposed=round(area),
                    limit=round(program.gross_floor_area_sf),
                    rule=det.driver if det else "floor area limit",
                    citation=det.citation if det else b.cite("max_far"),
                )
            )

    units = _number(concept, "total_units")
    if units is None:
        per_floor = _number(concept, "units_per_floor")
        if per_floor is not None and floors is not None:
            units = per_floor * floors
    if units is not None and program is not None and program.units is not None:
        if units > program.units:
            det = program.determination("units")
            violations.append(
                Violation(
                    field="units",
                    proposed=int(units),
                    limit=program.units,
                    rule=det.driver if det else "unit yield",
                    citation=det.citation if det else "",
                )
            )

    footprint = concept.get("layout", {}).get("footprint") if isinstance(
        concept.get("layout"), dict
    ) else None
    if footprint and len(footprint) >= 3:
        try:
            proposed = Polygon([(float(x), float(y)) for x, y in footprint])
        except (TypeError, ValueError):
            proposed = None
        if proposed is not None and proposed.is_valid and not proposed.is_empty:
            if proposed.area > envelope.max_footprint_sf + 1.0:
                det = envelope.determination("max_footprint")
                violations.append(
                    Violation(
                        field="footprint area",
                        proposed=round(proposed.area),
                        limit=round(envelope.max_footprint_sf),
                        rule=det.driver if det else "footprint limit",
                        citation=det.citation if det else "",
                    )
                )
            # The footprint must sit inside the buildable area, not merely be
            # the right size. A small tolerance absorbs rounding in coordinates.
            outside = proposed.difference(
                envelope.buildable.buffer(footprint_tolerance_ft)
            )
            if not outside.is_empty and outside.area > 1.0:
                violations.append(
                    Violation(
                        field="footprint placement",
                        proposed=f"{outside.area:,.0f} sf outside the buildable area",
                        limit="0 sf",
                        rule="setback encroachment",
                        citation="; ".join(
                            sorted(
                                {
                                    b.cite(kind.setback_rule_key)
                                    for _, kind in envelope.parcel.edges()
                                }
                            )
                        ),
                    )
                )

    return violations
