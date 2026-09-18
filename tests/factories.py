"""Helpers for building rule bundles and parcels in tests."""

from __future__ import annotations

from engine.parcel import EdgeKind, Parcel
from engine.rules import Provenance, RuleBundle, RuleValue

UNITS = {
    "min_lot_area_sf": "sf",
    "min_lot_width_ft": "ft",
    "setback_front": "ft",
    "setback_rear": "ft",
    "setback_side_interior": "ft",
    "setback_side_street": "ft",
    "max_lot_coverage_pct": "%",
    "max_far": "ratio",
    "max_height_ft": "ft",
    "max_stories": "stories",
    "max_density_units_per_acre": "units/acre",
    "min_lot_area_per_unit_sf": "sf/unit",
    "min_open_space_pct": "%",
    "parking_spaces_per_unit": "spaces/unit",
}


def bundle(provenance: Provenance = Provenance.HUMAN_VERIFIED, **overrides) -> RuleBundle:
    """A rule bundle with every key present; pass values to override."""
    values: dict[str, float | None] = {key: None for key in UNITS}
    values.update(overrides)
    return RuleBundle(
        jurisdiction="Testville",
        district="T-1",
        district_name="Test District",
        code_version="test-1",
        effective_date="2026-01-01",
        source_url=None,
        rules={
            key: RuleValue(
                key=key,
                value=value,
                unit=UNITS[key],
                citation=f"Testville Code sec. {i + 1}",
                provenance=provenance,
                verified_by=(
                    "Test Reviewer"
                    if provenance is Provenance.HUMAN_VERIFIED
                    else None
                ),
            )
            for i, (key, value) in enumerate(values.items())
        },
    )


def rect(width: float, depth: float, **kwargs) -> Parcel:
    """A rectangular lot with the street on the `width` side."""
    kwargs.setdefault("parcel_id", "TEST-1")
    return Parcel(
        coords=[(0.0, 0.0), (width, 0.0), (width, depth), (0.0, depth)],
        edge_kinds=[
            EdgeKind.FRONT,
            EdgeKind.SIDE_INTERIOR,
            EdgeKind.REAR,
            EdgeKind.SIDE_INTERIOR,
        ],
        **kwargs,
    )


def corner_rect(width: float, depth: float, **kwargs) -> Parcel:
    """A corner lot: street on the front and on one side."""
    kwargs.setdefault("parcel_id", "TEST-CORNER")
    return Parcel(
        coords=[(0.0, 0.0), (width, 0.0), (width, depth), (0.0, depth)],
        edge_kinds=[
            EdgeKind.FRONT,
            EdgeKind.SIDE_STREET,
            EdgeKind.REAR,
            EdgeKind.SIDE_INTERIOR,
        ],
        **kwargs,
    )
