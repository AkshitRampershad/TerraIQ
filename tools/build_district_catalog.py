#!/usr/bin/env python3
"""Generate rule-bundle stubs for every district in the county's zoning layer.

    python -m tools.build_district_catalog

Replaces hand-invented district codes with the authoritative list from
`reference/loudoun-gis/Loudoun_Zoning.csv`: 54 codes, their official names and
descriptions, and the ordinance each falls under.

Bundles are named `<CODE>@<ORDINANCE>.json` because three codes (PDH3, PDH6,
PDRDP) exist under both the 2023 and the 1972 ordinance with different
standards. A file keyed on the code alone would silently merge them.

Almost every value comes out null. That is the honest state: the zoning layer
carries district identity, not dimensional standards. Across all 54
descriptions there is no mention of a setback, yard, height, floor area ratio
or lot coverage. Density is the one exception -- ten districts state it in
prose, and it is extracted here by pattern match with the sentence kept as the
source excerpt, marked machine-extracted and awaiting review.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from engine.rules import Provenance, RuleBundle, RuleValue
from ingest.loudoun import JURISDICTION, DistrictRecord, load_districts

OUT_ROOT = Path(__file__).resolve().parent.parent / "reference" / "districts"

UNITS = {
    "min_lot_area_sf": "sf",
    "min_lot_width_ft": "ft",
    "setback_front": "ft",
    "setback_rear": "ft",
    "setback_side_interior": "ft",
    "setback_side_street": "ft",
    "max_lot_coverage_pct": "%",
    "max_far": "ratio",
    "max_height_ft": "ft",
    "max_stories": "stories",
    "max_density_units_per_acre": "units/acre",
    "min_lot_area_per_unit_sf": "sf/unit",
    "min_open_space_pct": "%",
    "parking_spaces_per_unit": "spaces/unit",
}

# Anchored on "density of" / "Max N units per acre" so the base figure is taken
# and the "... with ADU" bonus that follows it is not.
DENSITY_PER_ACRE = re.compile(
    r"densit(?:y|ies)\s+of\s+([\d.]+)\s+(?:dwelling\s+)?units?\s+per\s+acre", re.I
)
DENSITY_MAX_PREFIX = re.compile(
    r"\bmax(?:imum)?\s+([\d.]+)\s+(?:dwelling\s+)?units?\s+per\s+acre", re.I
)
LOT_AREA_PER_UNIT = re.compile(
    r"densit(?:y|ies)\s+of\s+1\s+unit\s+per\s+([\d,]+)\s+square\s+feet", re.I
)
ADU_BONUS = re.compile(r"([\d.]+)\s+(?:dwelling\s+)?units?\s+per\s+acre\s+with\s+ADU", re.I)


# A sentence end is a period not sitting inside a decimal number: these
# descriptions are full of figures like "19.2 units per acre", and splitting on
# a bare "." would cut the excerpt in half mid-number.
_SENTENCE_END = re.compile(r"\.(?!\d)")


def _sentence_containing(text: str, match: re.Match) -> str:
    """The whole sentence a match sits in, to serve as the source excerpt."""
    start = 0
    for boundary in _SENTENCE_END.finditer(text, 0, match.start()):
        start = boundary.end()
    end = len(text)
    after = _SENTENCE_END.search(text, match.end())
    if after:
        end = after.end()
    return text[start:end].strip()


def density_rules(record: DistrictRecord) -> dict[str, RuleValue]:
    """Extract whatever density the district description actually states."""
    desc = record.description
    citation = (
        f"Loudoun County zoning GIS layer, ZD_ZONE_DESC for {record.code} "
        f"({record.ordinance} ordinance) -- description field, NOT the ordinance text"
    )
    adu = ADU_BONUS.search(desc)
    note = "Extracted by pattern match from the county's GIS description field."
    if adu:
        note += (
            f" The description also allows {adu.group(1)} units per acre with an ADU; "
            "only the base density is recorded here."
        )

    out: dict[str, RuleValue] = {}

    match = DENSITY_PER_ACRE.search(desc) or DENSITY_MAX_PREFIX.search(desc)
    if match:
        out["max_density_units_per_acre"] = RuleValue(
            key="max_density_units_per_acre",
            value=float(match.group(1)),
            unit="units/acre",
            citation=citation,
            provenance=Provenance.LLM_EXTRACTED,
            source_excerpt=_sentence_containing(desc, match),
            note=note,
        )

    match = LOT_AREA_PER_UNIT.search(desc)
    if match:
        out["min_lot_area_per_unit_sf"] = RuleValue(
            key="min_lot_area_per_unit_sf",
            value=float(match.group(1).replace(",", "")),
            unit="sf/unit",
            citation=citation,
            provenance=Provenance.LLM_EXTRACTED,
            source_excerpt=_sentence_containing(desc, match),
            note=note,
        )
    return out


def build(record: DistrictRecord) -> RuleBundle:
    extracted = density_rules(record)
    rules: dict[str, RuleValue] = {}

    for key, unit in UNITS.items():
        if key in extracted:
            rules[key] = extracted[key]
            continue
        rules[key] = RuleValue(
            key=key,
            value=None,
            unit=unit,
            citation=(
                f"Loudoun County Zoning Ordinance ({record.ordinance}), district "
                f"standards for {record.code} -- NOT YET TRANSCRIBED"
            ),
            provenance=Provenance.PLACEHOLDER,
            note=(
                "The county's zoning GIS layer carries district identity only. "
                "Transcribe this from the ordinance text with tools.extract_ordinance "
                "or by hand, then confirm it with tools.verify_bundle."
            ),
        )

    return RuleBundle(
        jurisdiction=JURISDICTION,
        district=record.code,
        district_name=record.name or record.code,
        code_version=f"{record.ordinance} ordinance",
        effective_date="2023-12-13" if record.ordinance == "2023" else "unknown",
        source_url="https://www.loudoun.gov/1755/Zoning-Ordinance",
        rules=rules,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--zoning-csv", default=None)
    ap.add_argument("--out", default=None, help="output directory")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    districts = load_districts(args.zoning_csv)
    out_dir = Path(args.out) if args.out else OUT_ROOT / "loudoun-county-va"
    out_dir.mkdir(parents=True, exist_ok=True)

    with_density = 0
    for key, record in sorted(districts.items()):
        bundle = build(record)
        if any(r.trusted or r.provenance is Provenance.LLM_EXTRACTED
               for r in bundle.rules.values()):
            with_density += 1
        if not args.dry_run:
            bundle.save(out_dir / f"{record.code}@{record.ordinance}.json")

    codes = {r.code for r in districts.values()}
    dual = sorted(
        c for c in codes
        if len({r.ordinance for r in districts.values() if r.code == c}) > 1
    )
    print(f"{'Would write' if args.dry_run else 'Wrote'} {len(districts)} bundles "
          f"to {out_dir}")
    print(f"  {len(codes)} distinct district codes")
    print(f"  {with_density} with a density extracted from the description field")
    print(f"  {len(districts) - with_density} with no standards at all yet")
    if dual:
        print(f"  codes under two ordinances, kept separate: {', '.join(dual)}")
    print("\nNo setbacks, heights, coverage or FAR anywhere -- those are in the")
    print("ordinance text, which is not part of this export.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
