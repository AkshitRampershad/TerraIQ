"""Massing and yield: what the envelope actually supports as a building.

The envelope says how much area may be covered and how tall the building may
be. Turning that into floor area, unit count and parking demand needs a
handful of assumptions that are not zoning -- floor-to-floor height, average
unit size, how much of a floor plate is leasable, how much land a surface
parking stall consumes. Those are recorded in `ProgramAssumptions` and printed
in the report, so a reader can tell a code requirement from a modelling
choice. Conflating the two is the mistake that makes an analysis unreviewable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from engine.envelope import Determination, Envelope, Finding


@dataclass(frozen=True)
class ProgramAssumptions:
    """Modelling inputs that are emphatically not zoning standards."""

    avg_unit_sf: float = 950.0
    floor_plate_efficiency: float = 0.82
    surface_stall_sf: float = 325.0
    floor_to_floor_ft: float = 10.0

    def describe(self) -> list[str]:
        return [
            f"Average unit size: {self.avg_unit_sf:,.0f} sf",
            f"Floor plate efficiency (net leasable / gross): "
            f"{self.floor_plate_efficiency:.0%}",
            f"Surface parking, incl. drive aisle share: "
            f"{self.surface_stall_sf:,.0f} sf per stall",
            f"Floor-to-floor height: {self.floor_to_floor_ft:g} ft",
        ]


@dataclass
class Program:
    """The buildable program implied by an envelope."""

    envelope: Envelope
    assumptions: ProgramAssumptions
    footprint_sf: float
    stories: int | None
    gross_floor_area_sf: float | None
    far_achieved: float | None
    effective_stories: float | None
    units: int | None
    parking_required: int | None
    parking_area_sf: float | None
    land_left_for_parking_sf: float | None
    parking_fits: bool | None
    open_space_required_sf: float | None
    determinations: list[Determination] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def binding_constraint(self) -> str:
        """The single rule that most limits this project."""
        gfa = self.determination("gross_floor_area")
        if gfa is not None:
            return gfa.driver
        return "undetermined"

    def determination(self, quantity: str) -> Determination | None:
        for d in self.determinations:
            if d.quantity == quantity:
                return d
        return None


def compute_program(
    envelope: Envelope,
    assumptions: ProgramAssumptions | None = None,
) -> Program:
    """Derive floor area, unit yield and parking demand from an envelope."""
    assumptions = assumptions or ProgramAssumptions(
        floor_to_floor_ft=envelope.floor_to_floor_ft
    )
    bundle = envelope.bundle
    lot_area = envelope.parcel.area_sf
    footprint = envelope.max_footprint_sf

    determinations: list[Determination] = []
    findings: list[Finding] = []

    if envelope.blockers:
        return Program(
            envelope=envelope,
            assumptions=assumptions,
            footprint_sf=footprint,
            stories=envelope.stories,
            gross_floor_area_sf=None,
            far_achieved=None,
            effective_stories=None,
            units=None,
            parking_required=None,
            parking_area_sf=None,
            land_left_for_parking_sf=None,
            parking_fits=None,
            open_space_required_sf=None,
            findings=[
                Finding(
                    severity="blocker",
                    title="Program not computed",
                    detail="The envelope has a blocking finding; nothing fits.",
                )
            ],
        )

    # --- Gross floor area: stacking vs. FAR -------------------------------
    stories = envelope.stories
    gfa: float | None = None
    far_cap = None
    max_far = bundle.number("max_far")
    if max_far is not None:
        far_cap = lot_area * max_far

    if stories is None:
        findings.append(
            Finding(
                severity="warning",
                title="Floor area bounded only by FAR",
                detail=(
                    "No height or story limit is on file, so stacked floor area is "
                    "unbounded; the figure below reflects the FAR cap alone."
                ),
            )
        )
        gfa = far_cap
        if gfa is not None:
            determinations.append(
                Determination(
                    quantity="gross_floor_area",
                    value=gfa,
                    unit="sf",
                    driver="floor area ratio",
                    citation=bundle.cite("max_far"),
                    detail=f"FAR {max_far:g} on a {lot_area:,.0f} sf lot.",
                )
            )
    else:
        stacked = footprint * stories
        alternatives = {"footprint x stories": stacked}
        if far_cap is not None:
            alternatives["FAR cap"] = far_cap

        if far_cap is not None and far_cap < stacked:
            gfa = far_cap
            determinations.append(
                Determination(
                    quantity="gross_floor_area",
                    value=gfa,
                    unit="sf",
                    driver="floor area ratio",
                    citation=bundle.cite("max_far"),
                    detail=(
                        f"FAR {max_far:g} caps floor area at {far_cap:,.0f} sf, below "
                        f"the {stacked:,.0f} sf that {stories} stories of "
                        f"{footprint:,.0f} sf would give. The height is available but "
                        "the floor area is not, so the plate must shrink or a storey "
                        "must come off."
                    ),
                    alternatives=alternatives,
                )
            )
        else:
            gfa = stacked
            footprint_det = envelope.determination("max_footprint")
            determinations.append(
                Determination(
                    quantity="gross_floor_area",
                    value=gfa,
                    unit="sf",
                    driver=(
                        f"{footprint_det.driver} and height"
                        if footprint_det
                        else "footprint and height"
                    ),
                    citation=(footprint_det.citation if footprint_det else ""),
                    detail=(
                        f"{stories} stories over a {footprint:,.0f} sf plate"
                        + (
                            f"; the FAR cap of {far_cap:,.0f} sf is not reached."
                            if far_cap is not None
                            else "; this district does not cap FAR."
                        )
                    ),
                    alternatives=alternatives,
                )
            )

    far_achieved = (gfa / lot_area) if (gfa is not None and lot_area > 0) else None
    effective_stories = (gfa / footprint) if (gfa is not None and footprint > 0) else None

    # --- Unit yield: density cap vs. floor area ---------------------------
    units: int | None = None
    if gfa is not None:
        by_floor_area = int(
            (gfa * assumptions.floor_plate_efficiency) // assumptions.avg_unit_sf
        )
        candidates: dict[str, float] = {"floor area / unit size": by_floor_area}

        upa = bundle.number("max_density_units_per_acre")
        per_unit_area = bundle.number("min_lot_area_per_unit_sf")
        by_density: int | None = None
        density_citation = ""
        if upa is not None:
            by_density = int(envelope.parcel.area_acres * upa)
            candidates["density cap (units/acre)"] = by_density
            density_citation = bundle.cite("max_density_units_per_acre")
        elif per_unit_area is not None and per_unit_area > 0:
            by_density = int(lot_area // per_unit_area)
            candidates["density cap (lot area per unit)"] = by_density
            density_citation = bundle.cite("min_lot_area_per_unit_sf")

        if by_density is not None and by_density < by_floor_area:
            units = by_density
            determinations.append(
                Determination(
                    quantity="units",
                    value=float(units),
                    unit="units",
                    driver="density cap",
                    citation=density_citation,
                    detail=(
                        f"Density limits the site to {by_density} units even though "
                        f"{by_floor_area:,.0f} units of floor area are available. "
                        "Larger units, not more of them, is the way to use the "
                        "remaining floor area."
                    ),
                    alternatives=candidates,
                )
            )
        else:
            units = by_floor_area
            determinations.append(
                Determination(
                    quantity="units",
                    value=float(units),
                    unit="units",
                    driver="available floor area",
                    citation=bundle.cite("max_far") or "",
                    detail=(
                        f"{gfa:,.0f} sf gross at "
                        f"{assumptions.floor_plate_efficiency:.0%} efficiency supports "
                        f"{by_floor_area} units of {assumptions.avg_unit_sf:,.0f} sf"
                        + (
                            f"; the density cap of {by_density} units is not reached."
                            if by_density is not None
                            else "; this district does not cap density."
                        )
                    ),
                    alternatives=candidates,
                )
            )

        if units == 0:
            findings.append(
                Finding(
                    severity="blocker",
                    title="No dwelling units fit",
                    detail=(
                        "Available floor area or the density cap admits zero units at "
                        f"{assumptions.avg_unit_sf:,.0f} sf each."
                    ),
                )
            )

    # --- Open space and parking ------------------------------------------
    open_space_pct = bundle.number("min_open_space_pct")
    open_space_required = (
        lot_area * open_space_pct / 100.0 if open_space_pct is not None else None
    )

    parking_required: int | None = None
    parking_area: float | None = None
    land_left: float | None = None
    parking_fits: bool | None = None

    ratio = bundle.number("parking_spaces_per_unit")
    if ratio is not None and units is not None:
        parking_required = math.ceil(units * ratio)
        parking_area = parking_required * assumptions.surface_stall_sf
        land_left = lot_area - footprint - (open_space_required or 0.0)
        parking_fits = parking_area <= land_left

        determinations.append(
            Determination(
                quantity="parking",
                value=float(parking_required),
                unit="spaces",
                driver="parking ratio",
                citation=bundle.cite("parking_spaces_per_unit"),
                detail=(
                    f"{ratio:g} spaces per unit x {units} units. At "
                    f"{assumptions.surface_stall_sf:,.0f} sf per surface stall that "
                    f"needs {parking_area:,.0f} sf against {land_left:,.0f} sf of "
                    "land left after footprint and required open space."
                ),
            )
        )

        if not parking_fits:
            shortfall = parking_area - land_left
            findings.append(
                Finding(
                    severity="blocker",
                    title="Surface parking does not fit",
                    detail=(
                        f"Required parking exceeds available land by "
                        f"{shortfall:,.0f} sf. The site needs structured or podium "
                        "parking, a reduced unit count, or a parking reduction -- "
                        "this is usually what decides whether a small infill site "
                        "pencils, and it is invisible if you only check FAR and "
                        "height."
                    ),
                    citation=bundle.cite("parking_spaces_per_unit"),
                )
            )

    return Program(
        envelope=envelope,
        assumptions=assumptions,
        footprint_sf=footprint,
        stories=stories,
        gross_floor_area_sf=gfa,
        far_achieved=far_achieved,
        effective_stories=effective_stories,
        units=units,
        parking_required=parking_required,
        parking_area_sf=parking_area,
        land_left_for_parking_sf=land_left,
        parking_fits=parking_fits,
        open_space_required_sf=open_space_required,
        determinations=determinations,
        findings=findings,
    )
