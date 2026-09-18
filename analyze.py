#!/usr/bin/env python3
"""Command-line envelope analysis -- no Streamlit, no API key, no network.

    python analyze.py --district R16 --acres 0.75 --frontage 150
    python analyze.py --district R-8 --parcel reference/parcels/irregular-corner.json
    python analyze.py --list

Useful for checking the engine's output directly, and as the reproducible path
for anyone who wants to confirm a number without running the app.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from engine.catalog import (
    AmbiguousDistrict,
    DistrictNotOnFile,
    iter_bundles,
    load_bundle,
)
from engine.envelope import compute_envelope
from engine.parcel import EdgeKind, Overlay, OverlayKind, Parcel
from engine.program import ProgramAssumptions, compute_program
from engine.report import render_report
from engine.rules import RuleError

JURISDICTION = "Loudoun County, VA"


def load_parcel(path: str | Path) -> Parcel:
    """Load a parcel from JSON: boundary coordinates in plane feet."""
    raw = json.loads(Path(path).read_text())
    overlays = [
        Overlay(
            name=o["name"],
            kind=OverlayKind(o.get("kind", "other")),
            coords=[tuple(c) for c in o.get("coords", [])],
            citation=o.get("citation", "unspecified"),
            buildable=bool(o.get("buildable", False)),
            source=o.get("source"),
        )
        for o in raw.get("overlays", [])
    ]
    return Parcel(
        parcel_id=raw["parcel_id"],
        coords=[tuple(c) for c in raw["coords"]],
        edge_kinds=[EdgeKind(k) for k in raw["edge_kinds"]],
        address=raw.get("address"),
        jurisdiction=raw.get("jurisdiction", JURISDICTION),
        zoning_district=raw.get("zoning_district"),
        overlays=overlays,
        geometry_source=raw.get("geometry_source", "supplied parcel file"),
        edge_classification_source=raw.get("edge_classification_source", "supplied parcel file"),
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="list districts on file and exit")
    ap.add_argument("--jurisdiction", default=JURISDICTION)
    ap.add_argument("--district", help="zoning district code, e.g. R16")
    ap.add_argument(
        "--ordinance",
        default=None,
        help="which ordinance the parcel is zoned under, e.g. 2023 (required "
        "for codes that exist under more than one)",
    )
    ap.add_argument("--parcel", help="path to a parcel JSON file")
    ap.add_argument("--acres", type=float, help="lot size, if no parcel file is given")
    ap.add_argument("--frontage", type=float, default=0.0, help="street frontage in feet")
    ap.add_argument("--floor-to-floor", type=float, default=10.0)
    ap.add_argument("--avg-unit-sf", type=float, default=950.0)
    ap.add_argument("--efficiency", type=float, default=0.82)
    ap.add_argument("--stall-sf", type=float, default=325.0)
    ap.add_argument(
        "--strict",
        action="store_true",
        help="refuse to run on standards no human has verified",
    )
    args = ap.parse_args(argv)

    if args.list:
        print(f"Districts on file for {args.jurisdiction}:")
        count = 0
        for code, ordinance, bundle in iter_bundles(args.jurisdiction):
            count += 1
            regulated = sum(1 for r in bundle.rules.values() if r.regulated)
            mark = "verified" if bundle.fully_verified else "UNVERIFIED"
            print(
                f"  {code:<8} {ordinance:<6} {regulated:>2}/{len(bundle.rules)} "
                f"standards  [{mark}]  {bundle.district_name}"
            )
        if not count:
            print("  (none)")
        else:
            print(f"\n{count} bundles. 'standards' counts values that are on file "
                  f"at all, verified or not.")
        return 0

    if not args.district:
        ap.error("--district is required (or use --list)")
    if not args.parcel and not args.acres:
        ap.error("give either --parcel or --acres")

    try:
        bundle = load_bundle(args.jurisdiction, args.district, args.ordinance)
    except (DistrictNotOnFile, AmbiguousDistrict) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.parcel:
        parcel = load_parcel(args.parcel)
    else:
        parcel = Parcel.assumed_rectangle(
            parcel_id=f"{args.acres} acre lot",
            area_sf=args.acres * 43_560,
            frontage_ft=args.frontage or None,
            jurisdiction=args.jurisdiction,
            zoning_district=args.district,
        )

    try:
        envelope = compute_envelope(
            parcel, bundle, strict=args.strict, floor_to_floor_ft=args.floor_to_floor
        )
    except RuleError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    program = compute_program(
        envelope,
        ProgramAssumptions(
            avg_unit_sf=args.avg_unit_sf,
            floor_plate_efficiency=args.efficiency,
            surface_stall_sf=args.stall_sf,
            floor_to_floor_ft=args.floor_to_floor,
        ),
    )
    print(render_report(envelope, program))
    return 1 if envelope.blockers else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        # Piping into head closes the stream early; that is not an error.
        sys.stderr.close()
        raise SystemExit(0)
