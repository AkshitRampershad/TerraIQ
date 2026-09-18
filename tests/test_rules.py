import json

import pytest

from engine.rules import Provenance, RuleBundle, RuleError, RuleValue
from tests.factories import bundle


def test_a_value_without_a_citation_is_rejected():
    """The whole design rests on this: no citation, no rule."""
    with pytest.raises(RuleError, match="no citation"):
        RuleValue(key="setback_front", value=20, unit="ft", citation="")


def test_unregulated_is_not_zero():
    """A district that does not regulate a thing must not read as regulating 0."""
    b = bundle(max_far=None)
    assert b.require("max_far").regulated is False
    assert b.number("max_far") is None
    assert b.number("max_far", default=99) == 99


def test_missing_rule_raises_rather_than_defaulting():
    b = bundle()
    del b.rules["setback_front"]
    with pytest.raises(RuleError, match="absent from the bundle"):
        b.require("setback_front")


def test_negative_values_rejected():
    with pytest.raises(RuleError, match="must not be negative"):
        RuleValue(key="setback_front", value=-5, unit="ft", citation="sec. 1")


def test_strict_mode_refuses_unverified_standards():
    b = bundle(provenance=Provenance.PLACEHOLDER, setback_front=20)
    assert b.fully_verified is False
    with pytest.raises(RuleError, match="human-verified"):
        b.assert_verified()


def test_llm_extracted_is_not_trusted():
    """A model reading the ordinance is a draft, not a verification."""
    b = bundle(provenance=Provenance.LLM_EXTRACTED, setback_front=20)
    assert b.fully_verified is False
    with pytest.raises(RuleError):
        b.assert_verified()


def test_verified_bundle_passes_strict_mode():
    b = bundle(setback_front=20)
    b.assert_verified()


def test_round_trip_from_json(tmp_path):
    path = tmp_path / "T-1.json"
    path.write_text(
        json.dumps(
            {
                "jurisdiction": "Testville",
                "district": "T-1",
                "code_version": "1",
                "effective_date": "2026-01-01",
                "rules": {
                    "setback_front": {
                        "value": 20,
                        "unit": "ft",
                        "citation": "sec. 1",
                        "provenance": "human_verified",
                        "verified_by": "A. Reviewer",
                        "verified_on": "2026-09-18",
                        "source_excerpt": "Front yard: 20 feet.",
                    }
                },
            }
        )
    )
    b = RuleBundle.from_json(path)
    assert b.number("setback_front") == 20
    assert b.fully_verified


def test_unknown_provenance_rejected(tmp_path):
    path = tmp_path / "T-2.json"
    path.write_text(
        json.dumps(
            {
                "jurisdiction": "T",
                "district": "T-2",
                "code_version": "1",
                "effective_date": "2026-01-01",
                "rules": {
                    "setback_front": {
                        "value": 20,
                        "unit": "ft",
                        "citation": "sec. 1",
                        "provenance": "vibes",
                    }
                },
            }
        )
    )
    with pytest.raises(RuleError, match="unknown provenance"):
        RuleBundle.from_json(path)


def test_human_verified_must_name_a_person():
    """Verification is somebody putting their name to a number."""
    with pytest.raises(RuleError, match="names nobody"):
        RuleValue(
            key="setback_front",
            value=20,
            unit="ft",
            citation="sec. 1",
            provenance=Provenance.HUMAN_VERIFIED,
        )


def test_bundle_round_trips_through_disk(tmp_path):
    b = bundle(setback_front=20, max_height_ft=35)
    path = tmp_path / "out.json"
    b.save(path)
    again = RuleBundle.from_json(path)
    assert again.number("setback_front") == 20
    assert again.number("max_height_ft") == 35
    assert again.fully_verified
    assert again.rules["setback_front"].verified_by == "Test Reviewer"


def test_with_rule_replaces_without_mutating():
    b = bundle(setback_front=20)
    updated = b.with_rule(
        RuleValue(
            key="setback_front",
            value=25,
            unit="ft",
            citation="sec. 9",
            provenance=Provenance.HUMAN_VERIFIED,
            verified_by="A. Reviewer",
        )
    )
    assert b.number("setback_front") == 20
    assert updated.number("setback_front") == 25
