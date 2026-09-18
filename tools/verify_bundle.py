#!/usr/bin/env python3
"""Walk a person through confirming each standard against the ordinance.

    python -m tools.verify_bundle reference/districts/loudoun-county-va/R16@2023.json \
        --reviewer "Akshit Rampershad"

This is the step that turns a draft into a transcription. For each standard it
shows the value, the citation and the excerpt it was drawn from, and asks for
one of:

    y        the value is right              -> human_verified
    <number> the value is wrong, here is the right one
    n        this district does not regulate it -> null, human_verified
    s        skip, leave as it is
    q        save and stop

Only values a person confirms here are stamped `human_verified` with their name
and the date, and only those pass strict mode. Nothing else in the codebase can
set that marker.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from engine.rules import Provenance, RuleBundle, RuleError, RuleValue


def _settled_note(note: str | None) -> str | None:
    """Drop an extraction note's 'Unreviewed' claim once a person has reviewed it."""
    if not note:
        return note
    cleaned = note.replace("Unreviewed.", "").replace("Unreviewed", "").strip()
    return cleaned or None


def _prompt(rule: RuleValue, bundle: RuleBundle, stream, out) -> str:
    print("-" * 70, file=out)
    print(f"{rule.key}   [{rule.provenance.label}]", file=out)
    current = f"{rule.value:g} {rule.unit}" if rule.regulated else "not regulated"
    print(f"  current value : {current}", file=out)
    print(f"  citation      : {rule.citation}", file=out)
    if rule.source_excerpt:
        print(f"  quoted text   : \"{rule.source_excerpt}\"", file=out)
    if rule.note:
        print(f"  note          : {rule.note}", file=out)
    print(f"  [y]es / <number> / [n]ot regulated / [s]kip / [q]uit", file=out)
    out.flush()
    return (stream.readline() or "q").strip()


def verify(
    path: str | Path,
    reviewer: str,
    *,
    only: list[str] | None = None,
    stream=None,
    out=None,
    today: str | None = None,
) -> tuple[int, int]:
    """Interactive review. Returns (confirmed, remaining_unverified).

    `only` restricts the review to named standards, for re-checking one value
    after an ordinance amendment without walking the whole district again.
    """
    stream = stream or sys.stdin
    out = out or sys.stdout
    today = today or dt.date.today().isoformat()

    bundle = RuleBundle.from_json(path)
    print(f"\nReviewing {bundle.jurisdiction} {bundle.district} "
          f"({bundle.code_version})", file=out)
    print(f"Reviewer: {reviewer}\n", file=out)

    confirmed = 0
    if only:
        unknown = [k for k in only if k not in bundle.rules]
        if unknown:
            raise RuleError(
                f"{path}: no such standard(s) in this bundle: {', '.join(unknown)}"
            )

    for key in sorted(bundle.rules):
        rule = bundle.rules[key]
        if only and key not in only:
            continue
        if rule.trusted and not only:
            continue

        answer = _prompt(rule, bundle, stream, out)
        low = answer.lower()

        if low in ("q", "quit"):
            break
        if low in ("s", "skip", ""):
            continue

        if low in ("y", "yes"):
            value = rule.value
        elif low in ("n", "no"):
            value = None
        else:
            try:
                value = float(answer)
            except ValueError:
                print(f"  -- '{answer}' is not y/n/s/q or a number; skipped", file=out)
                continue

        bundle = bundle.with_rule(
            RuleValue(
                key=rule.key,
                value=value,
                unit=rule.unit,
                citation=rule.citation,
                provenance=Provenance.HUMAN_VERIFIED,
                source_url=rule.source_url,
                source_excerpt=rule.source_excerpt,
                verified_by=reviewer,
                verified_on=today,
                note=_settled_note(rule.note),
            )
        )
        confirmed += 1

    bundle.save(path)
    remaining = len(bundle.untrusted)
    print("-" * 70, file=out)
    print(f"Saved {path}", file=out)
    print(f"  {confirmed} standard(s) confirmed this session", file=out)
    if bundle.fully_verified:
        print("  Bundle is fully verified and now passes strict mode.", file=out)
    else:
        print(f"  {remaining} regulated value(s) still unverified:", file=out)
        for r in sorted(bundle.untrusted, key=lambda r: r.key):
            print(f"    - {r.key}", file=out)
    return confirmed, remaining


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("bundle", help="path to the district bundle JSON")
    ap.add_argument("--reviewer", required=True, help="who is putting their name to this")
    ap.add_argument(
        "--only",
        nargs="+",
        default=None,
        help="review only these standards, e.g. --only setback_front max_height_ft",
    )
    args = ap.parse_args(argv)

    if not args.reviewer.strip():
        print("error: --reviewer must name a person", file=sys.stderr)
        return 2
    try:
        verify(args.bundle, args.reviewer.strip(), only=args.only)
    except (RuleError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
