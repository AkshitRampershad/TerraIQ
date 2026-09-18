import pytest

from engine.envelope import compute_envelope
from engine.parcel import EdgeKind, Overlay, OverlayKind, Parcel
from engine.rules import Provenance, RuleError
from tests.factories import bundle, corner_rect, rect


def test_rectangular_lot_matches_hand_calculation():
    """100x200 lot, 25 front, 25 rear, 10 sides -> 80 x 150 = 12,000 sf."""
    env = compute_envelope(
        rect(100, 200),
        bundle(setback_front=25, setback_rear=25, setback_side_interior=10),
    )
    assert env.buildable_area_sf == pytest.approx(12_000, rel=1e-6)
    assert env.area_lost_to_setbacks_sf == pytest.approx(8_000, rel=1e-6)


def test_each_lot_line_gets_its_own_setback():
    """Asymmetric setbacks must not be applied as a uniform inward shrink."""
    env = compute_envelope(
        rect(100, 200),
        bundle(setback_front=40, setback_rear=10, setback_side_interior=5),
    )
    # width 100-10=90, depth 200-50=150
    assert env.buildable_area_sf == pytest.approx(90 * 150, rel=1e-6)


def test_corner_lot_uses_the_street_side_setback():
    """A corner lot's street-facing side takes the larger street-side number."""
    b = bundle(
        setback_front=25,
        setback_rear=25,
        setback_side_interior=5,
        setback_side_street=20,
    )
    interior = compute_envelope(rect(100, 200), b)
    corner = compute_envelope(corner_rect(100, 200), b)
    assert corner.buildable_area_sf < interior.buildable_area_sf
    # width 100 - 20 (street side) - 5 (interior) = 75; depth 200 - 50 = 150
    assert corner.buildable_area_sf == pytest.approx(75 * 150, rel=1e-6)


def test_setback_is_measured_perpendicular_from_an_irregular_boundary():
    """On a non-rectangular lot the envelope is smaller than any naive inset."""
    l_shaped = Parcel(
        parcel_id="L",
        coords=[(0, 0), (100, 0), (100, 100), (60, 100), (60, 200), (0, 200)],
        edge_kinds=[
            EdgeKind.FRONT,
            EdgeKind.SIDE_INTERIOR,
            EdgeKind.REAR,
            EdgeKind.SIDE_INTERIOR,
            EdgeKind.REAR,
            EdgeKind.SIDE_INTERIOR,
        ],
    )
    env = compute_envelope(
        l_shaped, bundle(setback_front=20, setback_rear=20, setback_side_interior=10)
    )
    assert 0 < env.buildable_area_sf < l_shaped.area_sf
    # The reentrant corner must actually bite: a plain 10 ft inset of the
    # bounding box would leave far more than this.
    assert env.buildable_area_sf < 0.65 * l_shaped.area_sf


def test_no_build_overlay_is_subtracted():
    b = bundle(setback_front=25, setback_rear=25, setback_side_interior=10)
    plain = compute_envelope(rect(100, 200), b)

    easement = Overlay(
        name="20 ft sanitary sewer easement",
        kind=OverlayKind.EASEMENT,
        coords=[(40, 25), (60, 25), (60, 175), (40, 175)],
        citation="Plat book 12 p. 44",
    )
    with_easement = compute_envelope(
        rect(100, 200, overlays=[easement]), b
    )
    assert with_easement.buildable_area_sf < plain.buildable_area_sf
    assert with_easement.area_lost_to_overlays_sf == pytest.approx(20 * 150, rel=1e-6)
    # The easement splits the buildable area into two strips.
    assert with_easement.largest_contiguous_sf < with_easement.buildable_area_sf


def test_advisory_overlay_does_not_shrink_the_envelope_but_is_reported():
    """A constraint the engine cannot model geometrically is surfaced, not dropped."""
    historic = Overlay(
        name="Old Town historic district",
        kind=OverlayKind.HISTORIC,
        coords=[],
        citation="Zoning Ord. art. 7",
        buildable=True,
    )
    env = compute_envelope(
        rect(100, 200, overlays=[historic]),
        bundle(setback_front=25, setback_rear=25, setback_side_interior=10),
    )
    assert env.buildable_area_sf == pytest.approx(12_000, rel=1e-6)
    assert any("not modelled geometrically" in f.title for f in env.findings)


def test_setbacks_can_consume_the_whole_lot():
    env = compute_envelope(
        rect(40, 60), bundle(setback_front=30, setback_rear=30, setback_side_interior=25)
    )
    assert env.buildable_area_sf == 0
    assert env.is_buildable is False
    assert any(f.severity == "blocker" for f in env.findings)


def test_lot_coverage_caps_the_footprint_below_the_geometry():
    env = compute_envelope(
        rect(100, 200),
        bundle(
            setback_front=25,
            setback_rear=25,
            setback_side_interior=10,
            max_lot_coverage_pct=30,
        ),
    )
    assert env.buildable_area_sf == pytest.approx(12_000)
    assert env.max_footprint_sf == pytest.approx(6_000)  # 30% of 20,000
    assert env.determination("max_footprint").driver == "maximum lot coverage"


def test_setbacks_bind_when_coverage_is_generous():
    env = compute_envelope(
        rect(100, 200),
        bundle(
            setback_front=25,
            setback_rear=25,
            setback_side_interior=10,
            max_lot_coverage_pct=90,
        ),
    )
    assert env.max_footprint_sf == pytest.approx(12_000)
    assert env.determination("max_footprint").driver == "setback geometry"


def test_stories_come_from_height_and_floor_to_floor():
    env = compute_envelope(
        rect(100, 200),
        bundle(setback_front=20, setback_rear=20, setback_side_interior=10, max_height_ft=45),
        floor_to_floor_ft=12,
    )
    assert env.stories == 3  # 45 // 12


def test_story_cap_can_bind_before_the_height_cap():
    env = compute_envelope(
        rect(100, 200),
        bundle(
            setback_front=20,
            setback_rear=20,
            setback_side_interior=10,
            max_height_ft=60,
            max_stories=3,
        ),
        floor_to_floor_ft=10,
    )
    assert env.stories == 3
    assert env.determination("stories").driver == "story limit"


def test_height_too_low_for_one_story_is_a_blocker():
    env = compute_envelope(
        rect(100, 200),
        bundle(setback_front=20, setback_rear=20, setback_side_interior=10, max_height_ft=8),
        floor_to_floor_ft=10,
    )
    assert env.stories == 0
    assert any(f.severity == "blocker" for f in env.findings)


def test_undersized_lot_is_flagged_but_not_silently_zeroed():
    env = compute_envelope(
        rect(40, 100),
        bundle(
            setback_front=20,
            setback_rear=20,
            setback_side_interior=5,
            min_lot_area_sf=10_000,
        ),
    )
    assert any("smaller than the district minimum" in f.title for f in env.findings)
    assert env.buildable_area_sf > 0  # nonconforming, not automatically unbuildable


def test_missing_setback_rule_raises_instead_of_assuming_zero():
    b = bundle(setback_front=20, setback_rear=20, setback_side_interior=10)
    del b.rules["setback_rear"]
    with pytest.raises(RuleError, match="absent from the bundle"):
        compute_envelope(rect(100, 200), b)


def test_strict_mode_refuses_placeholder_standards():
    b = bundle(
        provenance=Provenance.PLACEHOLDER,
        setback_front=20,
        setback_rear=20,
        setback_side_interior=10,
    )
    with pytest.raises(RuleError, match="human-verified"):
        compute_envelope(rect(100, 200), b, strict=True)
    # ...but still computes, loudly, when not strict.
    env = compute_envelope(rect(100, 200), b)
    assert any("not human-verified" in f.title for f in env.findings)


def test_engine_is_deterministic():
    """The property every downstream step depends on."""
    b = bundle(
        setback_front=25,
        setback_rear=25,
        setback_side_interior=10,
        max_lot_coverage_pct=40,
        max_height_ft=45,
    )
    runs = {compute_envelope(rect(100, 200), b).max_footprint_sf for _ in range(10)}
    assert len(runs) == 1


def test_a_district_with_no_setbacks_on_file_says_so_loudly():
    """An untranscribed district yields the whole lot; that is not an answer."""
    env = compute_envelope(rect(100, 200), bundle(max_height_ft=35))
    assert env.buildable_area_sf == pytest.approx(20_000)
    assert any("not a buildable envelope" in f.title for f in env.findings)


def test_a_district_with_setbacks_does_not_raise_that_finding():
    env = compute_envelope(
        rect(100, 200),
        bundle(setback_front=25, setback_rear=25, setback_side_interior=10),
    )
    assert not any("not a buildable envelope" in f.title for f in env.findings)
