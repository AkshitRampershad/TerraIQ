"""The guard rail: a model may propose, but the engine decides."""

import pytest

from engine.envelope import compute_envelope
from engine.program import compute_program
from engine.validate import validate_concept
from tests.factories import bundle, rect

BASE = dict(
    setback_front=25,
    setback_rear=25,
    setback_side_interior=10,
    max_lot_coverage_pct=40,
    max_height_ft=40,
    max_far=1.0,
    max_density_units_per_acre=40,
    parking_spaces_per_unit=1.0,
)


@pytest.fixture
def analysis():
    env = compute_envelope(rect(100, 200), bundle(**BASE))
    return env, compute_program(env)


def test_a_compliant_concept_passes(analysis):
    env, prog = analysis
    concept = {
        "option_name": "Modest",
        "building_area_sft": prog.gross_floor_area_sf - 500,
        "floors": env.stories,
        "layout": {"footprint": [[30, 30], [70, 30], [70, 170], [30, 170]]},
    }
    assert validate_concept(concept, env, prog) == []


def test_too_many_floors_is_caught(analysis):
    env, prog = analysis
    violations = validate_concept({"floors": env.stories + 3}, env, prog)
    assert [v.field for v in violations] == ["floors"]
    assert violations[0].citation


def test_excess_floor_area_is_caught(analysis):
    env, prog = analysis
    violations = validate_concept(
        {"building_area_sft": prog.gross_floor_area_sf * 2}, env, prog
    )
    assert any(v.field == "building_area_sft" for v in violations)


def test_unit_count_derived_from_floors_is_checked(analysis):
    env, prog = analysis
    violations = validate_concept(
        {"floors": env.stories, "units_per_floor": 50}, env, prog
    )
    assert any(v.field == "units" for v in violations)


def test_footprint_that_encroaches_a_setback_is_caught(analysis):
    """Right size, wrong place -- the failure a size-only check misses."""
    env, prog = analysis
    concept = {
        "floors": 1,
        "layout": {"footprint": [[0, 0], [60, 0], [60, 60], [0, 60]]},
    }
    violations = validate_concept(concept, env, prog)
    assert any(v.field == "footprint placement" for v in violations)


def test_oversized_footprint_is_caught(analysis):
    env, prog = analysis
    concept = {
        "floors": 1,
        "layout": {"footprint": [[25, 25], [95, 25], [95, 195], [25, 195]]},
    }
    violations = validate_concept(concept, env, prog)
    assert any(v.field == "footprint area" for v in violations)


def test_malformed_model_output_does_not_crash_the_check(analysis):
    env, prog = analysis
    for junk in (
        {},
        {"floors": "several"},
        {"layout": "a nice open plan"},
        {"layout": {"footprint": [[1, 2]]}},
        {"layout": {"footprint": [["a", "b"], ["c", "d"], ["e", "f"]]}},
        {"building_area_sft": None},
    ):
        assert isinstance(validate_concept(junk, env, prog), list)


def test_violations_render_with_their_authority(analysis):
    env, prog = analysis
    violations = validate_concept({"floors": 99}, env, prog)
    assert "Testville Code" in str(violations[0])
