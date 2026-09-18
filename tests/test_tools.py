"""Tests for the transcription pipeline: extract -> verify -> lint."""

import io
import json

import pytest

from engine.rules import Provenance, RuleBundle
from tools.extract_ordinance import build_bundle, narrow
from tools.lint_bundles import lint
from tools.ordinance_text import contains_excerpt, load_text
from tools.verify_bundle import verify

ORDINANCE = """
CHAPTER 5. RESIDENTIAL DISTRICTS

Sec. 5-101. R-16 Townhouse/Multifamily Residential.
(a) Minimum lot area: twenty thousand (20,000) square feet.
(b) Front yard: twenty-five (25) feet.
(c) Side yard, interior: fifteen (15) feet.
(d) Side yard, street: twenty-five (25) feet.
(e) Rear yard: twenty-five (25) feet.
(f) Maximum building height: forty-five (45) feet.
(g) Maximum density: sixteen (16) dwelling units per acre.

Sec. 5-102. Unrelated provisions about signage and fences.
"""

META = dict(
    jurisdiction="Loudoun County, VA",
    district="R-16",
    district_name="Townhouse/Multifamily Residential",
    code_version="2023 Zoning Ordinance",
    effective_date="2023-12-13",
    source_url=None,
    source_name="ordinance.txt",
)


def _model_output(**rules):
    return {"rules": rules}


def test_a_value_with_a_real_excerpt_is_accepted():
    bundle, rejected = build_bundle(
        _model_output(
            setback_front={
                "value": 25,
                "citation": "Sec. 5-101(b)",
                "source_excerpt": "Front yard: twenty-five (25) feet.",
            }
        ),
        ORDINANCE,
        **META,
    )
    rule = bundle.rules["setback_front"]
    assert rule.value == 25
    assert rule.provenance is Provenance.LLM_EXTRACTED
    assert "Front yard" in rule.source_excerpt
    assert not any("setback_front" in r for r in rejected)


def test_a_fabricated_excerpt_is_discarded():
    """The guard that makes machine extraction reviewable rather than trusted."""
    bundle, rejected = build_bundle(
        _model_output(
            setback_front={
                "value": 30,
                "citation": "Sec. 5-101(b)",
                "source_excerpt": "Front yard: thirty (30) feet.",
            }
        ),
        ORDINANCE,
        **META,
    )
    assert bundle.rules["setback_front"].value is None
    assert bundle.rules["setback_front"].provenance is Provenance.PLACEHOLDER
    assert any("not present" in r for r in rejected)


def test_a_value_without_a_citation_is_discarded():
    bundle, rejected = build_bundle(
        _model_output(
            max_height_ft={
                "value": 45,
                "citation": "",
                "source_excerpt": "Maximum building height: forty-five (45) feet.",
            }
        ),
        ORDINANCE,
        **META,
    )
    assert bundle.rules["max_height_ft"].value is None
    assert any("no citation" in r for r in rejected)


def test_every_required_key_exists_even_when_nothing_was_found():
    """A gap must be visible in the file, not surface as a crash later."""
    bundle, _ = build_bundle(_model_output(), ORDINANCE, **META)
    from tools.extract_ordinance import WANTED

    assert set(bundle.rules) == set(WANTED)
    assert all(not r.regulated for r in bundle.rules.values())
    assert all("NOT FOUND" in r.citation for r in bundle.rules.values())


def test_extracted_bundle_never_passes_strict_mode():
    bundle, _ = build_bundle(
        _model_output(
            setback_front={
                "value": 25,
                "citation": "Sec. 5-101(b)",
                "source_excerpt": "Front yard: twenty-five (25) feet.",
            }
        ),
        ORDINANCE,
        **META,
    )
    assert not bundle.fully_verified


def test_excerpt_matching_survives_line_wrapping():
    wrapped = "Front yard:\n    twenty-five (25)\n    feet."
    assert contains_excerpt(wrapped, "Front yard: twenty-five (25) feet.")


def test_short_excerpts_are_not_evidence():
    assert not contains_excerpt(ORDINANCE, "feet")
    assert not contains_excerpt(ORDINANCE, "")


def test_narrow_keeps_the_relevant_section():
    slice_ = narrow(ORDINANCE, r"R-16", context=8)
    assert "Minimum lot area" in slice_
    assert narrow(ORDINANCE, r"nothing-matches-this") == ""


def test_load_text_rejects_unknown_types(tmp_path):
    from tools.ordinance_text import SourceUnavailable

    bad = tmp_path / "ordinance.docx"
    bad.write_text("x")
    with pytest.raises(SourceUnavailable, match="Unsupported"):
        load_text(bad)


# --- verification ------------------------------------------------------


@pytest.fixture
def draft(tmp_path):
    bundle, _ = build_bundle(
        _model_output(
            setback_front={
                "value": 25,
                "citation": "Sec. 5-101(b)",
                "source_excerpt": "Front yard: twenty-five (25) feet.",
            },
            setback_rear={
                "value": 20,
                "citation": "Sec. 5-101(e)",
                "source_excerpt": "Rear yard: twenty-five (25) feet.",
            },
            max_far={
                "value": 1.0,
                "citation": "Sec. 5-101",
                "source_excerpt": "Maximum building height: forty-five (45) feet.",
            },
        ),
        ORDINANCE,
        **META,
    )
    path = tmp_path / "R-16.json"
    bundle.save(path)
    return path


def test_confirming_a_value_stamps_the_reviewer(draft):
    confirmed, _ = verify(
        draft,
        "A. Reviewer",
        only=["max_far"],
        stream=io.StringIO("y\n"),
        out=io.StringIO(),
        today="2026-09-18",
    )
    assert confirmed == 1
    bundle = RuleBundle.from_json(draft)
    assert bundle.rules["max_far"].provenance is Provenance.HUMAN_VERIFIED
    assert bundle.rules["max_far"].verified_by == "A. Reviewer"
    assert bundle.rules["max_far"].verified_on == "2026-09-18"


def test_correcting_a_value_overwrites_it(draft):
    verify(
        draft,
        "A. Reviewer",
        only=["max_far"],
        stream=io.StringIO("2.0\n"),
        out=io.StringIO(),
    )
    bundle = RuleBundle.from_json(draft)
    assert bundle.rules["max_far"].value == 2.0
    assert bundle.rules["max_far"].provenance is Provenance.HUMAN_VERIFIED


def test_marking_a_quantity_unregulated(draft):
    verify(
        draft,
        "A. Reviewer",
        only=["max_far"],
        stream=io.StringIO("n\n"),
        out=io.StringIO(),
    )
    bundle = RuleBundle.from_json(draft)
    assert bundle.rules["max_far"].regulated is False
    assert bundle.rules["max_far"].provenance is Provenance.HUMAN_VERIFIED


def test_skipping_leaves_the_value_untouched(draft):
    before = RuleBundle.from_json(draft).rules["max_far"]
    verify(
        draft,
        "A. Reviewer",
        only=["max_far"],
        stream=io.StringIO("s\n"),
        out=io.StringIO(),
    )
    after = RuleBundle.from_json(draft).rules["max_far"]
    assert after.provenance is before.provenance


def test_verification_shows_the_excerpt_so_the_pdf_stays_shut(draft):
    out = io.StringIO()
    verify(draft, "A. Reviewer", only=["max_far"], stream=io.StringIO("q\n"), out=out)
    assert "Maximum building height: forty-five (45) feet." in out.getvalue()


def test_reviewing_everything_unlocks_strict_mode(draft):
    # 14 keys; answer every prompt. Unregulated ones are skipped automatically.
    verify(draft, "A. Reviewer", stream=io.StringIO("y\n" * 20), out=io.StringIO())
    bundle = RuleBundle.from_json(draft)
    assert bundle.fully_verified
    bundle.assert_verified()


# --- linting -----------------------------------------------------------


def test_lint_passes_the_shipped_bundles():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "reference" / "districts"
    for path in root.rglob("*.json"):
        if path.name.startswith("_"):
            continue
        assert lint(path) == [], f"{path}: {lint(path)}"


def _write(tmp_path, **rules):
    base = {
        "jurisdiction": "T",
        "district": "T-1",
        "code_version": "1",
        "effective_date": "2026-01-01",
        "rules": {
            k: {"value": v, "unit": "ft", "citation": "sec. 1", "provenance": "placeholder"}
            for k, v in rules.items()
        },
    }
    path = tmp_path / "T-1.json"
    path.write_text(json.dumps(base))
    return path


def test_lint_catches_an_implausible_value(tmp_path):
    path = _write(tmp_path, setback_front=5000)
    assert any("plausible range" in p for p in lint(path))


def test_lint_catches_a_percentage_entered_as_a_fraction(tmp_path):
    path = _write(tmp_path, max_lot_coverage_pct=0.4)
    assert any("plausible range" in p for p in lint(path))


def test_lint_catches_swapped_side_and_front_setbacks(tmp_path):
    path = _write(tmp_path, setback_front=8, setback_side_interior=25)
    assert any("exceeds the front setback" in p for p in lint(path))


def test_lint_catches_contradictory_density(tmp_path):
    path = _write(tmp_path, max_density_units_per_acre=16, min_lot_area_per_unit_sf=10000)
    assert any("disagree" in p for p in lint(path))


def test_lint_catches_a_verified_value_with_a_vague_citation(tmp_path):
    path = tmp_path / "T-1.json"
    path.write_text(
        json.dumps(
            {
                "jurisdiction": "T",
                "district": "T-1",
                "code_version": "1",
                "effective_date": "2026-01-01",
                "rules": {
                    "setback_front": {
                        "value": 20,
                        "unit": "ft",
                        "citation": "section to be confirmed",
                        "provenance": "human_verified",
                        "verified_by": "Someone",
                        "verified_on": "2026-01-01",
                    }
                },
            }
        )
    )
    assert any("citation is still vague" in p for p in lint(path))


def test_lint_reports_missing_required_keys(tmp_path):
    path = _write(tmp_path, setback_front=20)
    assert any("required key absent" in p for p in lint(path))


def test_only_rejects_an_unknown_standard(draft):
    from engine.rules import RuleError

    with pytest.raises(RuleError, match="no such standard"):
        verify(
            draft,
            "A. Reviewer",
            only=["setback_moon"],
            stream=io.StringIO("y\n"),
            out=io.StringIO(),
        )


def test_only_can_recheck_an_already_verified_standard(draft):
    verify(draft, "A. Reviewer", only=["max_far"], stream=io.StringIO("y\n"), out=io.StringIO())
    verify(draft, "B. Reviewer", only=["max_far"], stream=io.StringIO("3.5\n"), out=io.StringIO())
    bundle = RuleBundle.from_json(draft)
    assert bundle.rules["max_far"].value == 3.5
    assert bundle.rules["max_far"].verified_by == "B. Reviewer"


def test_verifying_clears_the_unreviewed_claim(draft):
    """A note must not still say 'Unreviewed' after somebody reviewed it."""
    verify(draft, "A. Reviewer", only=["max_far"], stream=io.StringIO("y\n"), out=io.StringIO())
    rule = RuleBundle.from_json(draft).rules["max_far"]
    assert "Unreviewed" not in (rule.note or "")
