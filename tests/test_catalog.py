import pytest

from engine.catalog import (
    AmbiguousDistrict,
    DistrictNotOnFile,
    available_codes,
    iter_bundles,
    load_bundle,
    normalize_district,
)

JURISDICTION = "Loudoun County, VA"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("r16", "R16"),
        ("R-16", "R16"),
        ("R 16", "R16"),
        ("pd-h3", "PDH3"),
        ("  tr1ubf ", "TR1UBF"),
    ],
)
def test_district_codes_normalize_to_the_county_spelling(raw, expected):
    """Loudoun writes R16, not R-16; any spelling must reach the same bundle."""
    assert normalize_district(raw) == expected


def test_the_catalog_matches_the_county_zoning_layer():
    codes = available_codes(JURISDICTION)
    assert len(codes) == 54
    for expected in ("R16", "R24", "R4", "R8", "A10", "JLMA20", "TR1UBF"):
        assert expected in codes


def test_every_shipped_bundle_loads_with_citations_on_every_rule():
    seen = 0
    for code, ordinance, bundle in iter_bundles(JURISDICTION):
        seen += 1
        assert bundle.district == code
        for rule in bundle.rules.values():
            assert rule.citation.strip()
    assert seen == 57


def test_any_spelling_finds_the_bundle():
    for spelling in ("R16", "r-16", "R 16"):
        assert load_bundle(JURISDICTION, spelling).district == "R16"


def test_jurisdiction_name_variants_resolve():
    assert available_codes("loudoun-county-va")
    assert available_codes("Loudoun County VA")


def test_unknown_district_refuses_rather_than_guessing():
    with pytest.raises(DistrictNotOnFile, match="will not guess"):
        load_bundle(JURISDICTION, "XX99")


def test_unknown_jurisdiction_refuses():
    with pytest.raises(DistrictNotOnFile):
        load_bundle("Atlantis", "R1")


def test_a_code_under_two_ordinances_refuses_to_pick_one():
    """PDH3 exists under 1972 and 2023 with different standards."""
    with pytest.raises(AmbiguousDistrict, match="will not pick one"):
        load_bundle(JURISDICTION, "PDH3")


@pytest.mark.parametrize("ordinance", ["1972", "2023"])
def test_naming_the_ordinance_resolves_the_ambiguity(ordinance):
    bundle = load_bundle(JURISDICTION, "PDH3", ordinance)
    assert ordinance in bundle.code_version


def test_asking_for_an_ordinance_a_district_lacks_is_an_error():
    with pytest.raises(DistrictNotOnFile, match="no bundle for"):
        load_bundle(JURISDICTION, "R16", "1972")


def test_no_shipped_bundle_claims_to_be_verified():
    """They are a work list, not a transcription."""
    for code, ordinance, bundle in iter_bundles(JURISDICTION):
        assert not bundle.fully_verified


def test_a_bundle_with_nothing_transcribed_does_not_pass_strict_mode():
    """The false green light: empty must not read as verified."""
    from engine.rules import RuleError

    bundle = load_bundle(JURISDICTION, "A10")
    assert all(not r.regulated for r in bundle.rules.values())
    with pytest.raises(RuleError, match="must be confirmed"):
        bundle.assert_verified()


def test_density_extracted_from_the_county_description_is_present_but_unreviewed():
    from engine.rules import Provenance

    bundle = load_bundle(JURISDICTION, "R16")
    rule = bundle.rules["max_density_units_per_acre"]
    assert rule.value == 16
    assert rule.provenance is Provenance.LLM_EXTRACTED
    assert "16 units per acre" in rule.source_excerpt
    assert "ZD_ZONE_DESC" in rule.citation


def test_lot_area_per_unit_districts_are_not_recorded_as_units_per_acre():
    """R4 says '1 unit per 10,000 square feet' -- a different quantity."""
    bundle = load_bundle(JURISDICTION, "R4")
    assert bundle.number("min_lot_area_per_unit_sf") == 10_000
    assert bundle.number("max_density_units_per_acre") is None
