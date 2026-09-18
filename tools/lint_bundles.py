#!/usr/bin/env python3
"""Check rule bundles for completeness, citation quality and plausibility.

    python -m tools.lint_bundles                     # every shipped bundle
    python -m tools.lint_bundles path/to/R-16.json

Catches the transcription mistakes that are easy to make and expensive to
find later: a missing key, a citation that is still a to-be-confirmed
placeholder, a rear setback of 500 feet, a percentage entered as 0.4 instead
of 40.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from engine.rules import Provenance, RuleBundle, RuleError

REQUIRED_KEYS = {
    "min_lot_area_sf",
    "min_lot_width_ft",
    "setback_front",
    "setback_rear",
    "setback_side_interior",
    "setback_side_street",
    "max_lot_coverage_pct",
    "max_far",
    "max_height_ft",
    "max_stories",
    "max_density_units_per_acre",
    "min_lot_area_per_unit_sf",
    "min_open_space_pct",
    "parking_spaces_per_unit",
}

# Ranges wide enough to admit any real district, narrow enough to catch a
# transposed digit or a unit mix-up.
PLAUSIBLE = {
    "min_lot_area_sf": (500, 2_000_000),
    "min_lot_width_ft": (10, 1_000),
    "setback_front": (0, 200),
    "setback_rear": (0, 200),
    "setback_side_interior": (0, 200),
    "setback_side_street": (0, 200),
    "max_lot_coverage_pct": (1, 100),
    "max_far": (0.01, 30),
    "max_height_ft": (10, 1_500),
    "max_stories": (1, 120),
    "max_density_units_per_acre": (0.01, 500),
    "min_lot_area_per_unit_sf": (100, 2_000_000),
    "min_open_space_pct": (0, 95),
    "parking_spaces_per_unit": (0, 5),
}

VAGUE_CITATION = ("to be confirmed", "tbd", "unknown", "placeholder", "not found")


def lint(path: Path) -> list[str]:
    """Return a list of problems; empty means the bundle looks sound."""
    problems: list[str] = []
    try:
        bundle = RuleBundle.from_json(path)
    except RuleError as e:
        return [f"will not load: {e}"]

    missing = REQUIRED_KEYS - set(bundle.rules)
    for key in sorted(missing):
        problems.append(f"{key}: required key absent (use null if unregulated)")

    for key in sorted(bundle.rules):
        rule = bundle.rules[key]
        cite = rule.citation.lower()

        if rule.trusted and any(v in cite for v in VAGUE_CITATION):
            problems.append(
                f"{key}: marked human_verified but the citation is still vague "
                f"({rule.citation!r})"
            )
        if rule.trusted and not rule.verified_on:
            problems.append(f"{key}: human_verified without a verified_on date")

        if not rule.regulated:
            continue

        lo, hi = PLAUSIBLE.get(key, (None, None))
        if lo is not None and not (lo <= rule.value <= hi):
            problems.append(
                f"{key}: {rule.value:g} {rule.unit} is outside the plausible range "
                f"{lo}-{hi} -- check units and decimal place"
            )

    front = bundle.number("setback_front")
    side = bundle.number("setback_side_interior")
    street_side = bundle.number("setback_side_street")
    if front is not None and side is not None and side > front:
        problems.append(
            f"interior side setback ({side:g} ft) exceeds the front setback "
            f"({front:g} ft) -- unusual; confirm they are not swapped"
        )
    if street_side is not None and side is not None and street_side < side:
        problems.append(
            f"street-side setback ({street_side:g} ft) is smaller than the interior "
            f"side setback ({side:g} ft) -- unusual; confirm they are not swapped"
        )

    upa = bundle.number("max_density_units_per_acre")
    per_unit = bundle.number("min_lot_area_per_unit_sf")
    if upa is not None and per_unit is not None:
        implied = 43_560 / per_unit
        if abs(implied - upa) / max(upa, 1e-9) > 0.1:
            problems.append(
                f"density stated two ways and they disagree: {upa:g} units/acre vs "
                f"{per_unit:g} sf/unit (implies {implied:.1f} units/acre)"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("bundles", nargs="*", help="bundle files; default is all shipped")
    args = ap.parse_args(argv)

    if args.bundles:
        paths = [Path(p) for p in args.bundles]
    else:
        root = Path(__file__).resolve().parent.parent / "reference" / "districts"
        paths = sorted(p for p in root.rglob("*.json") if not p.name.startswith("_"))

    if not paths:
        print("no bundles found", file=sys.stderr)
        return 2

    total = 0
    for path in paths:
        problems = lint(path)
        total += len(problems)
        status = "ok" if not problems else f"{len(problems)} problem(s)"
        print(f"{path}: {status}")
        for p in problems:
            print(f"  - {p}")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
