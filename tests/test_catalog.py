import pytest

from engine.catalog import (
    DistrictNotOnFile,
    available_districts,
    load_bundle,
    normalize_district,
)

JURISDICTION = "Loudoun County, VA"


@pytest.mark.parametrize(
    "raw,expected",
    [("r8", "R-8"), ("R 16", "R-16"), ("R-24", "R-24"), ("pd-h3", "PD-H3")],
)
def test_district_codes_normalize(raw, expected):
    assert normalize_district(raw) == expected


def test_shipped_bundles_load():
    districts = available_districts(JURISDICTION)
    assert districts, "expected shipped Loudoun bundles"
    for code in districts:
        bundle = load_bundle(JURISDICTION, code)
        assert bundle.district == code
        for rule in bundle.rules.values():
            assert rule.citation


def test_jurisdiction_name_variants_resolve():
    assert available_districts("loudoun-county-va")
    assert available_districts("Loudoun County VA")


def test_unknown_district_refuses_rather_than_guessing():
    """The single most important failure mode to get right."""
    with pytest.raises(DistrictNotOnFile, match="will not guess"):
        load_bundle(JURISDICTION, "XX-99")


def test_unknown_jurisdiction_refuses():
    with pytest.raises(DistrictNotOnFile):
        load_bundle("Atlantis", "R-1")


def test_shipped_bundles_are_marked_unverified():
    """They are placeholders; nothing should present them as authoritative."""
    for code in available_districts(JURISDICTION):
        assert not load_bundle(JURISDICTION, code).fully_verified
