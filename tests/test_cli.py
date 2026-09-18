"""End-to-end checks through the CLI, using the shipped bundles and parcels."""

import json

import pytest

from analyze import load_parcel, main
from engine.catalog import load_bundle
from engine.envelope import compute_envelope
from engine.program import compute_program

SAMPLE = "reference/parcels/irregular-corner.json"


def test_list_districts(capsys):
    assert main(["--list"]) == 0
    out = capsys.readouterr().out
    assert "R-16" in out
    assert "UNVERIFIED" in out


def test_analysis_runs_and_cites_everything(capsys):
    assert main(["--district", "R-16", "--acres", "0.75", "--frontage", "150"]) == 0
    out = capsys.readouterr().out
    assert "BUILDABLE ENVELOPE" in out
    assert "HOW EACH NUMBER WAS DETERMINED" in out
    assert "NOT VERIFIED AGAINST THE PUBLISHED ORDINANCE" in out
    assert "Authority:" in out


def test_unknown_district_exits_nonzero(capsys):
    assert main(["--district", "ZZ-99", "--acres", "1"]) == 2
    assert "will not guess" in capsys.readouterr().err


def test_strict_mode_refuses_the_placeholder_bundles(capsys):
    assert main(["--district", "R-16", "--acres", "0.75", "--strict"]) == 2
    assert "human-verified" in capsys.readouterr().err


def test_sample_parcel_easement_splits_the_envelope():
    parcel = load_parcel(SAMPLE)
    env = compute_envelope(parcel, load_bundle("Loudoun County, VA", "R-16"))
    assert env.area_lost_to_overlays_sf > 0
    # The easement runs the full depth, so no single building can use the
    # whole buildable area.
    assert env.largest_contiguous_sf < env.buildable_area_sf
    assert any("separate regions" in f.title for f in env.findings)


def test_sample_parcel_is_reproducible():
    parcel = load_parcel(SAMPLE)
    bundle = load_bundle("Loudoun County, VA", "R-16")
    results = {
        json.dumps(
            {
                "buildable": round(compute_envelope(parcel, bundle).buildable_area_sf, 6),
                "units": compute_program(compute_envelope(parcel, bundle)).units,
            }
        )
        for _ in range(5)
    }
    assert len(results) == 1


@pytest.mark.parametrize("district", ["R-4", "R-8", "R-16", "R-24"])
def test_every_shipped_district_analyses_cleanly(district):
    assert main(["--district", district, "--acres", "1.0", "--frontage", "150"]) == 0
