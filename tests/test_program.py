import pytest

from engine.envelope import compute_envelope
from engine.program import ProgramAssumptions, compute_program
from tests.factories import bundle, rect

BASE = dict(setback_front=25, setback_rear=25, setback_side_interior=10)


def _program(parcel, b, **assumption_kwargs):
    env = compute_envelope(parcel, b)
    return compute_program(env, ProgramAssumptions(**assumption_kwargs))


def test_floor_area_is_footprint_times_stories_when_far_is_slack():
    prog = _program(
        rect(100, 200),
        bundle(**BASE, max_lot_coverage_pct=30, max_height_ft=40, max_far=5.0),
    )
    # 30% of 20,000 = 6,000 sf plate; 40 ft / 10 = 4 stories
    assert prog.gross_floor_area_sf == pytest.approx(24_000)
    assert prog.binding_constraint != "floor area ratio"


def test_far_caps_floor_area_below_what_the_height_allows():
    prog = _program(
        rect(100, 200),
        bundle(**BASE, max_lot_coverage_pct=30, max_height_ft=40, max_far=0.5),
    )
    assert prog.gross_floor_area_sf == pytest.approx(10_000)  # 0.5 x 20,000
    assert prog.binding_constraint == "floor area ratio"
    assert prog.effective_stories == pytest.approx(10_000 / 6_000)


def test_density_cap_can_bind_before_floor_area():
    """A generous envelope with a tight density cap yields fewer, larger units."""
    prog = _program(
        rect(200, 200),  # 40,000 sf ~ 0.918 acres
        bundle(
            **BASE,
            max_lot_coverage_pct=50,
            max_height_ft=60,
            max_far=3.0,
            max_density_units_per_acre=10,
        ),
        avg_unit_sf=900,
    )
    assert prog.units == 9  # 0.918 acres x 10 u/ac, floored
    assert prog.determination("units").driver == "density cap"


def test_floor_area_binds_when_density_is_generous():
    prog = _program(
        rect(100, 200),
        bundle(
            **BASE,
            max_lot_coverage_pct=40,
            max_height_ft=30,
            max_density_units_per_acre=100,
        ),
        avg_unit_sf=1_000,
    )
    # 8,000 sf plate x 3 stories = 24,000 gross; x 0.82 / 1,000 = 19 units
    assert prog.units == 19
    assert prog.determination("units").driver == "available floor area"


def test_lot_area_per_unit_works_as_an_alternative_density_form():
    prog = _program(
        rect(100, 200),
        bundle(
            **BASE,
            max_lot_coverage_pct=50,
            max_height_ft=50,
            min_lot_area_per_unit_sf=4_000,
        ),
        avg_unit_sf=800,
    )
    assert prog.units == 5  # 20,000 / 4,000


def test_parking_that_does_not_fit_is_a_blocker():
    """The constraint that actually kills small infill sites."""
    prog = _program(
        rect(100, 200),
        bundle(
            **BASE,
            max_lot_coverage_pct=60,
            max_height_ft=60,
            max_density_units_per_acre=200,
            parking_spaces_per_unit=2.0,
        ),
        avg_unit_sf=700,
    )
    assert prog.parking_fits is False
    assert any(f.severity == "blocker" for f in prog.findings)
    assert any("parking" in f.title.lower() for f in prog.findings)


def test_open_space_requirement_reduces_land_available_for_parking():
    kwargs = dict(
        **BASE,
        max_lot_coverage_pct=25,
        max_height_ft=30,
        max_density_units_per_acre=20,
        parking_spaces_per_unit=1.0,
    )
    without = _program(rect(150, 200), bundle(**kwargs))
    with_open = _program(rect(150, 200), bundle(**kwargs, min_open_space_pct=40))
    assert with_open.land_left_for_parking_sf < without.land_left_for_parking_sf


def test_blocked_envelope_produces_no_program():
    prog = _program(
        rect(40, 60),
        bundle(setback_front=30, setback_rear=30, setback_side_interior=25),
    )
    assert prog.gross_floor_area_sf is None
    assert prog.units is None


def test_assumptions_are_reported_separately_from_the_code():
    prog = _program(
        rect(100, 200),
        bundle(**BASE, max_lot_coverage_pct=40, max_height_ft=40),
        avg_unit_sf=1_100,
    )
    described = " ".join(prog.assumptions.describe())
    assert "1,100 sf" in described
    assert "efficiency" in described
