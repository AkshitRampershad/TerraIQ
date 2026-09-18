"""Deterministic buildable-envelope computation.

The buildable area of a lot is defined exactly:

    buildable = parcel - union(buffer(lot_line_i, setback_i)) - no_build_overlays

Buffering each lot line individually, rather than shrinking the parcel by a
single uniform distance, is what makes this correct: zoning assigns a
different setback to the front, rear, interior side and street side lines, and
the required distance is measured perpendicular from each line. The union of
per-line buffers is precisely the set of points too close to some lot line,
for any lot shape including concave and flag lots.

No language model is involved. The same parcel and the same rule bundle
produce the same envelope every time, which is the property every downstream
step -- permit review, architect certification, any compliance attestation --
actually depends on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from engine.parcel import EdgeKind, Parcel
from engine.rules import RuleBundle, RuleError

Severity = Literal["info", "warning", "blocker"]


@dataclass(frozen=True)
class Determination:
    """One computed number, and the rule that decided it.

    `alternatives` holds every cap that was considered, so the report can say
    not just what the limit is but what it would take to move it.
    """

    quantity: str
    value: float
    unit: str
    driver: str
    citation: str
    detail: str = ""
    alternatives: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Finding:
    """Something the reviewer needs to know that is not itself a dimension."""

    severity: Severity
    title: str
    detail: str
    citation: str | None = None


@dataclass
class Envelope:
    """What may be built on this lot, and why that is the limit."""

    parcel: Parcel
    bundle: RuleBundle
    setback_zone: BaseGeometry
    buildable: BaseGeometry
    buildable_area_sf: float
    largest_contiguous: Polygon | None
    largest_contiguous_sf: float
    area_lost_to_setbacks_sf: float
    area_lost_to_overlays_sf: float
    max_footprint_sf: float
    max_single_building_sf: float
    stories: int | None
    height_ft: float | None
    floor_to_floor_ft: float
    determinations: list[Determination]
    findings: list[Finding]
    strict: bool

    @property
    def buildable_fraction(self) -> float:
        """Share of the lot that survives setbacks and overlays."""
        if self.parcel.area_sf <= 0:
            return 0.0
        return self.buildable_area_sf / self.parcel.area_sf

    @property
    def is_buildable(self) -> bool:
        return self.buildable_area_sf > 0

    @property
    def blockers(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "blocker"]

    def determination(self, quantity: str) -> Determination | None:
        for d in self.determinations:
            if d.quantity == quantity:
                return d
        return None


def _setback_for(bundle: RuleBundle, kind: EdgeKind) -> tuple[float, str]:
    """The setback distance for a lot-line class, and its citation.

    Requires the rule to be present in the bundle. A district that genuinely
    has no side setback must say so with an explicit null rather than by
    omission -- silence is how a missing standard becomes a zero.
    """
    rule = bundle.require(kind.setback_rule_key)
    return (float(rule.value) if rule.regulated else 0.0), rule.citation


def compute_envelope(
    parcel: Parcel,
    bundle: RuleBundle,
    *,
    strict: bool = False,
    floor_to_floor_ft: float = 10.0,
) -> Envelope:
    """Compute the buildable envelope for a parcel under a district's standards.

    With `strict=True` the engine refuses to run on standards no human has
    verified against the ordinance. That is the mode any real submittal
    should use; the demo path runs unstrict and labels every output.
    """
    if floor_to_floor_ft <= 0:
        raise ValueError("floor_to_floor_ft must be positive")
    if strict:
        bundle.assert_verified()

    findings: list[Finding] = []
    determinations: list[Determination] = []

    if not bundle.fully_verified:
        untrusted = ", ".join(sorted(r.key for r in bundle.untrusted))
        findings.append(
            Finding(
                severity="warning",
                title="Standards are not human-verified",
                detail=(
                    f"These standards have not been checked against the published "
                    f"ordinance: {untrusted}. Treat every number below as an "
                    f"illustration of the method, not as a zoning determination."
                ),
                citation=bundle.source_url,
            )
        )

    if parcel.is_assumed_shape:
        findings.append(
            Finding(
                severity="warning",
                title="Lot shape is assumed, not surveyed",
                detail=(
                    "The boundary used here was synthesized from a stated lot area "
                    f"({parcel.geometry_source}). Setback losses depend heavily on "
                    "actual shape, frontage and orientation, so the buildable area "
                    "below can differ substantially from the real parcel. Supply "
                    "the parcel polygon from the county GIS for a usable result."
                ),
            )
        )

    # A stand-in rectangle is only as good as the real lot is rectangular.
    if parcel.compactness is not None and parcel.compactness < 0.60:
        findings.append(
            Finding(
                severity="warning",
                title="The real lot is markedly non-rectangular",
                detail=(
                    f"Shape compactness of the recorded lot is "
                    f"{parcel.compactness:.2f} (a square is about 0.79). The lot "
                    "is elongated, ragged or pinched, so a rectangular stand-in "
                    "puts the lot lines in the wrong places and the setback "
                    "losses below are unreliable for this parcel in particular. "
                    "Get the boundary before relying on any number here."
                ),
            )
        )

    lot_area = parcel.area_sf

    # A district whose standards have not been transcribed yields an envelope
    # equal to the whole lot. That number is arithmetically correct and
    # completely meaningless, and it looks like an answer, so say plainly that
    # it is not one.
    setback_keys = [k.setback_rule_key for k in EdgeKind]
    if all(bundle.number(key) is None for key in setback_keys):
        findings.append(
            Finding(
                severity="warning",
                title="No setbacks are on file -- this is not a buildable envelope",
                detail=(
                    f"The bundle for {bundle.district} records no setback for any "
                    "lot line, so nothing has been subtracted and the 'buildable "
                    "area' below is simply the whole lot. It is not a finding "
                    "about this parcel. Transcribe the district's standards from "
                    "the ordinance before reading anything into these numbers."
                ),
                citation=bundle.cite("setback_front"),
            )
        )

    # --- Conformance of the lot itself -----------------------------------
    min_area = bundle.number("min_lot_area_sf")
    if min_area is not None and lot_area < min_area:
        findings.append(
            Finding(
                severity="warning",
                title="Lot is smaller than the district minimum",
                detail=(
                    f"Lot is {lot_area:,.0f} sf against a {min_area:,.0f} sf minimum. "
                    "It may still be developable as a legal nonconforming lot of "
                    "record, but that is a determination for the zoning "
                    "administrator, not a calculation."
                ),
                citation=bundle.cite("min_lot_area_sf"),
            )
        )

    min_width = bundle.number("min_lot_width_ft")
    frontage = parcel.frontage_ft()
    if min_width is not None and frontage > 0 and frontage < min_width:
        findings.append(
            Finding(
                severity="warning",
                title="Frontage is below the district minimum lot width",
                detail=(
                    f"Measured {frontage:,.1f} ft of front lot line against a "
                    f"{min_width:,.0f} ft minimum. Width is measured here as total "
                    "front-lot-line length; jurisdictions define it differently "
                    "(at the building line, as a mean, or as a chord), so confirm "
                    "the local definition."
                ),
                citation=bundle.cite("min_lot_width_ft"),
            )
        )

    # --- Setback geometry -------------------------------------------------
    restricted = []
    applied: dict[str, tuple[float, str]] = {}
    for line, kind in parcel.edges():
        distance, citation = _setback_for(bundle, kind)
        applied[kind.value] = (distance, citation)
        if distance > 0:
            restricted.append(line.buffer(distance))

    setback_zone = unary_union(restricted) if restricted else Polygon()
    after_setbacks = parcel.polygon.difference(setback_zone)
    area_lost_to_setbacks = lot_area - after_setbacks.area

    # --- Overlay subtraction ---------------------------------------------
    no_build = parcel.no_build_overlays()
    buildable = after_setbacks
    if no_build:
        overlay_union = unary_union([o.polygon for o in no_build])
        buildable = buildable.difference(overlay_union)
    area_lost_to_overlays = after_setbacks.area - buildable.area

    for overlay in no_build:
        findings.append(
            Finding(
                severity="info",
                title=f"No-build overlay applied: {overlay.name}",
                detail=f"{overlay.kind.value} area removed from the envelope.",
                citation=overlay.citation,
            )
        )
    for overlay in parcel.advisory_overlays():
        findings.append(
            Finding(
                severity="warning",
                title=f"Overlay not modelled geometrically: {overlay.name}",
                detail=(
                    f"This {overlay.kind.value} overlay constrains the project but "
                    "its effect is not a simple area subtraction, so it does not "
                    "reduce the envelope below. It still requires review."
                ),
                citation=overlay.citation,
            )
        )

    buildable_area = buildable.area
    parts = _polygon_parts(buildable)
    largest = max(parts, key=lambda p: p.area) if parts else None
    largest_area = largest.area if largest is not None else 0.0

    if buildable_area <= 0:
        findings.append(
            Finding(
                severity="blocker",
                title="No buildable area remains",
                detail=(
                    "Setbacks and no-build overlays consume the entire lot. Any "
                    "structure would require a variance."
                ),
            )
        )
    elif len(parts) > 1:
        findings.append(
            Finding(
                severity="info",
                title=f"Buildable area is split into {len(parts)} separate regions",
                detail=(
                    f"Largest contiguous region is {largest_area:,.0f} sf of "
                    f"{buildable_area:,.0f} sf total. A single structure must fit "
                    "within one region."
                ),
            )
        )

    determinations.append(
        Determination(
            quantity="buildable_area",
            value=buildable_area,
            unit="sf",
            driver="setbacks and overlays",
            citation="; ".join(
                f"{kind} setback {dist:g} ft ({cite})"
                for kind, (dist, cite) in sorted(applied.items())
            ),
            detail=(
                f"{area_lost_to_setbacks:,.0f} sf removed by setbacks, "
                f"{area_lost_to_overlays:,.0f} sf by overlays, from a "
                f"{lot_area:,.0f} sf lot."
            ),
        )
    )

    # --- Footprint: geometry vs. lot-coverage cap -------------------------
    coverage_pct = bundle.number("max_lot_coverage_pct")
    coverage_cap = lot_area * coverage_pct / 100.0 if coverage_pct is not None else None

    alternatives = {"buildable geometry": buildable_area}
    if coverage_cap is not None:
        alternatives["lot coverage cap"] = coverage_cap

    if coverage_cap is not None and coverage_cap < buildable_area:
        max_footprint = coverage_cap
        driver = "maximum lot coverage"
        citation = bundle.cite("max_lot_coverage_pct")
        detail = (
            f"{coverage_pct:g}% of a {lot_area:,.0f} sf lot caps footprint at "
            f"{coverage_cap:,.0f} sf, below the {buildable_area:,.0f} sf that "
            f"setbacks alone would allow."
        )
    else:
        max_footprint = buildable_area
        driver = "setback geometry"
        citation = "; ".join(sorted({c for _, c in applied.values()}))
        detail = (
            "Setbacks bind before lot coverage does"
            + (
                f"; the {coverage_pct:g}% coverage cap ({coverage_cap:,.0f} sf) is "
                "not reached."
                if coverage_cap is not None
                else "; this district does not cap lot coverage."
            )
        )

    determinations.append(
        Determination(
            quantity="max_footprint",
            value=max_footprint,
            unit="sf",
            driver=driver,
            citation=citation,
            detail=detail,
            alternatives=alternatives,
        )
    )

    max_single = min(largest_area, coverage_cap) if coverage_cap is not None else largest_area

    # --- Height and stories ----------------------------------------------
    max_height = bundle.number("max_height_ft")
    max_stories_rule = bundle.number("max_stories")

    stories: int | None = None
    height: float | None = max_height
    story_alternatives: dict[str, float] = {}

    if max_height is not None:
        story_alternatives["height limit / floor-to-floor"] = max_height / floor_to_floor_ft
    if max_stories_rule is not None:
        story_alternatives["story limit"] = max_stories_rule

    if story_alternatives:
        by_height = (
            int(max_height // floor_to_floor_ft) if max_height is not None else None
        )
        by_stories = int(max_stories_rule) if max_stories_rule is not None else None
        candidates = [c for c in (by_height, by_stories) if c is not None]
        stories = min(candidates)
        if by_height is not None and stories == by_height and (
            by_stories is None or by_height <= by_stories
        ):
            story_driver = "height limit"
            story_citation = bundle.cite("max_height_ft")
            story_detail = (
                f"{max_height:g} ft at {floor_to_floor_ft:g} ft floor-to-floor yields "
                f"{by_height} full stories."
            )
            height = max_height
        else:
            story_driver = "story limit"
            story_citation = bundle.cite("max_stories")
            story_detail = f"District caps the building at {by_stories} stories."
            capped = by_stories * floor_to_floor_ft if by_stories else None
            candidate_heights = [h for h in (max_height, capped) if h is not None]
            height = min(candidate_heights) if candidate_heights else None

        if stories == 0:
            findings.append(
                Finding(
                    severity="blocker",
                    title="Height limit admits no full story",
                    detail=(
                        f"A {max_height:g} ft limit does not accommodate one "
                        f"{floor_to_floor_ft:g} ft story."
                    ),
                    citation=bundle.cite("max_height_ft"),
                )
            )

        determinations.append(
            Determination(
                quantity="stories",
                value=float(stories),
                unit="stories",
                driver=story_driver,
                citation=story_citation,
                detail=story_detail,
                alternatives=story_alternatives,
            )
        )
    else:
        findings.append(
            Finding(
                severity="warning",
                title="No height or story limit on file",
                detail=(
                    "The bundle records neither a height nor a story cap for this "
                    "district. Massing below is unbounded vertically, which is "
                    "almost certainly a gap in the rule bundle rather than in the "
                    "ordinance."
                ),
            )
        )

    return Envelope(
        parcel=parcel,
        bundle=bundle,
        setback_zone=setback_zone,
        buildable=buildable,
        buildable_area_sf=buildable_area,
        largest_contiguous=largest,
        largest_contiguous_sf=largest_area,
        area_lost_to_setbacks_sf=area_lost_to_setbacks,
        area_lost_to_overlays_sf=area_lost_to_overlays,
        max_footprint_sf=max_footprint,
        max_single_building_sf=max_single,
        stories=stories,
        height_ft=height,
        floor_to_floor_ft=floor_to_floor_ft,
        determinations=determinations,
        findings=findings,
        strict=strict,
    )


def _polygon_parts(geom: BaseGeometry) -> list[Polygon]:
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        return [g for g in geom.geoms if g.geom_type == "Polygon" and not g.is_empty]
    return []
