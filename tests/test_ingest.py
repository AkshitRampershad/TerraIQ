"""Tests for the Loudoun GIS readers and the equivalent-rectangle stand-in."""

import math

import pytest

from engine.parcel import EdgeKind, Parcel
from ingest.loudoun import (
    load_centroids,
    load_districts,
    load_parcels,
    normalize_mcpi,
)


# --- parcel IDs Excel mangled ------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("28187793000", "028187793000"),   # leading zero stripped by Excel
        ("001154444000", "001154444000"),  # already intact
        (" 123 ", "000000000123"),
    ],
)
def test_leading_zeros_are_restored(raw, expected):
    assert normalize_mcpi(raw) == expected


@pytest.mark.parametrize("raw", ["2.17E+11", "4.88E+11", "2.3E+11"])
def test_scientific_notation_ids_are_refused_not_guessed(raw):
    """'2.17E+11' has lost nine digits; reconstructing it would join to the
    wrong parcel, which is worse than dropping the row."""
    assert normalize_mcpi(raw) is None


@pytest.mark.parametrize("raw", ["", "   ", None, "N/A"])
def test_unusable_ids_are_refused(raw):
    assert normalize_mcpi(raw) is None


def test_the_reader_reports_what_it_had_to_discard():
    records, report = load_parcels()
    assert report.rows > 0
    assert report.loaded == len(records)
    # The shipped sample is drawn from the corrupted export.
    assert report.destroyed_ids > 0
    assert "scientific notation" in report.describe()
    assert "typed as text" in report.describe()


def test_loaded_ids_are_all_normalized():
    records, _ = load_parcels()
    assert records
    assert all(len(mcpi) == 12 and mcpi.isdigit() for mcpi in records)


def test_centroids_load_and_normalize():
    centroids = load_centroids()
    assert centroids
    for mcpi, c in centroids.items():
        assert len(mcpi) == 12
        assert -80 < c.lon < -76 and 38 < c.lat < 40  # Loudoun County, VA


# --- the district catalog ----------------------------------------------


def test_districts_are_keyed_by_code_and_ordinance():
    districts = load_districts()
    assert districts["R16-2023"].name == "Townhouse/Multifamily Residential-16"
    # Three codes exist under both ordinances and must not be merged.
    for code in ("PDH3", "PDH6", "PDRDP"):
        ordinances = {r.ordinance for r in districts.values() if r.code == code}
        assert ordinances == {"1972", "2023"}


def test_district_descriptions_carry_no_dimensional_standards():
    """The finding that keeps the transcription honest: the GIS layer has none."""
    districts = load_districts()
    banned = ("setback", "yard", "floor area ratio", "lot coverage")
    for record in districts.values():
        lowered = record.description.lower()
        assert not any(word in lowered for word in banned), record.code


# --- the equivalent rectangle ------------------------------------------


def test_rectangle_matches_both_the_recorded_area_and_perimeter():
    """A 100 x 200 lot: area 20,000, perimeter 600."""
    p = Parcel.from_area_and_perimeter("X", area_sf=20_000, perimeter_ft=600)
    assert p.area_sf == pytest.approx(20_000)
    assert p.perimeter_ft == pytest.approx(600)


def test_the_short_side_is_taken_as_frontage():
    p = Parcel.from_area_and_perimeter("X", area_sf=20_000, perimeter_ft=600)
    assert p.frontage_ft() == pytest.approx(100)  # not 200


def test_a_lot_rounder_than_any_rectangle_falls_back_to_a_square():
    """Real row from Loudoun_Parcels.csv, compactness 0.795.

    A square is the roundest rectangle there is, at compactness 0.785. This
    lot beats that, so no rectangle has both its area and its perimeter. The
    area is matched exactly and the perimeter is allowed to differ, because
    area is what every zoning calculation downstream depends on.
    """
    recorded_area, recorded_perimeter = 42_366.98794, 818.2369013
    p = Parcel.from_area_and_perimeter("COMPACT", recorded_area, recorded_perimeter)

    assert p.area_sf == pytest.approx(recorded_area)
    assert p.compactness > 0.785
    # The square is slightly longer round than the real lot, and cannot not be.
    assert p.perimeter_ft > recorded_perimeter
    assert p.perimeter_ft == pytest.approx(recorded_perimeter, rel=0.01)
    assert "more compact than a rectangle" in p.geometry_source


def test_compactness_is_recorded_and_flags_elongated_lots():
    """Real row: a 236 x 715 sliver."""
    p = Parcel.from_area_and_perimeter("ELONGATED", 168_774.4716, 1_901.735059)
    assert p.compactness == pytest.approx(
        4 * math.pi * 168_774.4716 / 1_901.735059**2
    )
    assert p.compactness < 0.60


def test_an_elongated_lot_warns_that_the_stand_in_is_unreliable():
    from engine.catalog import load_bundle
    from engine.envelope import compute_envelope

    p = Parcel.from_area_and_perimeter("ELONGATED", 168_774.4716, 1_901.735059)
    env = compute_envelope(p, load_bundle("Loudoun County, VA", "R16"))
    assert any("non-rectangular" in f.title for f in env.findings)


def test_a_square_lot_does_not_warn():
    from engine.catalog import load_bundle
    from engine.envelope import compute_envelope

    p = Parcel.from_area_and_perimeter("SQUARE", 10_000, 400)
    env = compute_envelope(p, load_bundle("Loudoun County, VA", "R16"))
    assert not any("non-rectangular" in f.title for f in env.findings)


def test_the_stand_in_is_always_labelled_assumed():
    p = Parcel.from_area_and_perimeter("X", 20_000, 600)
    assert p.is_assumed_shape
    assert "ASSUMED" in p.geometry_source
    assert "ASSUMED" in p.edge_classification_source


def test_corner_lots_take_a_street_side_lot_line():
    p = Parcel.from_area_and_perimeter("X", 20_000, 600, corner_lot=True)
    assert EdgeKind.SIDE_STREET in p.edge_kinds


def test_a_parcel_record_without_a_perimeter_refuses_to_invent_a_shape():
    from ingest.loudoun import ParcelRecord

    record = ParcelRecord(
        mcpi="000000000001",
        legal_acres=1.0,
        legal_sqft=43_560,
        shape_area_sf=43_560,
        shape_perimeter_ft=None,
    )
    with pytest.raises(ValueError, match="no perimeter"):
        record.to_parcel()


def test_records_round_trip_into_a_usable_parcel():
    records, _ = load_parcels()
    fitted = [
        r.to_parcel() for r in records.values() if r.area_sf and r.shape_perimeter_ft
    ]
    assert fitted
    for parcel in fitted[:25]:
        assert parcel.area_sf > 0
        assert parcel.jurisdiction == "Loudoun County, VA"
