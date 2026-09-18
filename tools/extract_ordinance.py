#!/usr/bin/env python3
"""Draft a rule bundle from ordinance text, with every value quoting its source.

    python -m tools.extract_ordinance \
        --source loudoun-ch2.txt --jurisdiction "Loudoun County, VA" \
        --district R16 --district-name "Townhouse/Multifamily Residential" \
        --code-version "2023 Zoning Ordinance, adopted 2023-12-13" \
        --effective-date 2023-12-13 \
        --out reference/districts/loudoun-county-va/R16@2023.json

The model reads the ordinance and proposes values. Each one must come with a
verbatim excerpt from the document, and any value whose excerpt does not
actually appear in the source is discarded before it reaches the file. A model
that cannot point at real text does not get to contribute a number.

What comes out is a DRAFT, marked `llm_extracted`. It does not pass strict mode
and it is not a transcription until a person reviews it with
`tools.verify_bundle`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import requests

from engine.rules import Provenance, RuleBundle, RuleError, RuleValue
from groq_client import GROQ_API_URL, GROQ_MODEL, get_groq_api_key
from tools.ordinance_text import SourceUnavailable, contains_excerpt, load_text

# The quantities the engine needs, with the units it expects them in.
WANTED = {
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


def narrow(text: str, pattern: str, context: int = 60) -> str:
    """Keep only the lines near a pattern, so a long ordinance fits a prompt."""
    lines = text.splitlines()
    rx = re.compile(pattern, re.IGNORECASE)
    keep: set[int] = set()
    for i, line in enumerate(lines):
        if rx.search(line):
            keep.update(range(max(0, i - context), min(len(lines), i + context + 1)))
    if not keep:
        return ""
    return "\n".join(lines[i] for i in sorted(keep))


def build_prompt(source: str, district: str, jurisdiction: str) -> str:
    return f"""Below is text from the {jurisdiction} zoning ordinance. Read it and
report the dimensional standards for the {district} district only.

For each quantity you can find, give:
  value          the number, in the stated unit
  citation       the section or table number, exactly as the document writes it
  source_excerpt a VERBATIM span copied from the text below that states this
                 value. It must appear in the document character for character.
                 Do not paraphrase, reformat, or reconstruct it.

Rules:
- If the ordinance does not regulate a quantity for this district, give
  "value": null and say so in the excerpt only if the document says so;
  otherwise omit the key entirely.
- If you cannot find a quantity, OMIT it. Do not estimate, do not infer from a
  neighbouring district, and do not use general knowledge of zoning. An omitted
  value is correct behaviour; a guessed one is not.
- Convert to these units: {json.dumps(WANTED)}
- If the document gives a range or a conditional standard, take the base
  by-right number and note the condition in the excerpt.

Respond with JSON: {{"rules": {{"<key>": {{"value": ..., "citation": "...",
"source_excerpt": "..."}}}}}}

ORDINANCE TEXT
--------------
{source}
"""


def call_model(prompt: str, timeout: int = 120) -> dict:
    api_key = get_groq_api_key()
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Extraction needs a model; verification "
            "and linting do not."
        )
    response = requests.post(
        GROQ_API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": GROQ_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You transcribe zoning ordinances. You quote the document "
                        "verbatim and never supply a number the text does not "
                        "state. Respond with valid JSON only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return json.loads(response.json()["choices"][0]["message"]["content"])


def build_bundle(
    proposed: dict,
    source: str,
    *,
    jurisdiction: str,
    district: str,
    district_name: str,
    code_version: str,
    effective_date: str,
    source_url: str | None,
    source_name: str,
) -> tuple[RuleBundle, list[str]]:
    """Turn model output into a bundle, dropping anything it cannot evidence."""
    rules: dict[str, RuleValue] = {}
    rejected: list[str] = []

    for key, unit in WANTED.items():
        spec = proposed.get("rules", {}).get(key)
        if not isinstance(spec, dict):
            rejected.append(f"{key}: not found in the source")
            continue

        excerpt = (spec.get("source_excerpt") or "").strip()
        citation = (spec.get("citation") or "").strip()

        if not citation:
            rejected.append(f"{key}: no citation given")
            continue
        if not contains_excerpt(source, excerpt):
            rejected.append(
                f"{key}: quoted excerpt is not present in {source_name} -- discarded"
            )
            continue

        value = spec.get("value")
        if value is not None:
            try:
                value = float(value)
            except (TypeError, ValueError):
                rejected.append(f"{key}: value {value!r} is not numeric")
                continue

        rules[key] = RuleValue(
            key=key,
            value=value,
            unit=unit,
            citation=citation,
            provenance=Provenance.LLM_EXTRACTED,
            source_url=source_url,
            source_excerpt=excerpt,
            note=f"Machine-extracted from {source_name}. Unreviewed.",
        )

    # Keys the engine requires must exist even when nothing was found, so the
    # gap is visible in the file rather than surfacing as a crash later.
    for key, unit in WANTED.items():
        if key not in rules:
            rules[key] = RuleValue(
                key=key,
                value=None,
                unit=unit,
                citation=f"NOT FOUND in {source_name} -- transcribe by hand",
                provenance=Provenance.PLACEHOLDER,
                note="Extraction found no evidence for this quantity.",
            )

    bundle = RuleBundle(
        jurisdiction=jurisdiction,
        district=district,
        district_name=district_name,
        code_version=code_version,
        effective_date=effective_date,
        source_url=source_url,
        rules=rules,
    )
    return bundle, rejected


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--source", required=True, help="local .txt/.md/.pdf of the ordinance")
    ap.add_argument("--jurisdiction", required=True)
    ap.add_argument("--district", required=True)
    ap.add_argument("--district-name", default="")
    ap.add_argument("--code-version", required=True)
    ap.add_argument("--effective-date", required=True)
    ap.add_argument("--source-url", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--grep",
        default=None,
        help="narrow the source to lines near this pattern before prompting",
    )
    args = ap.parse_args(argv)

    try:
        full_text = load_text(args.source)
    except SourceUnavailable as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    prompt_text = narrow(full_text, args.grep) if args.grep else full_text
    if args.grep and not prompt_text:
        print(f"error: pattern {args.grep!r} matched nothing in {args.source}", file=sys.stderr)
        return 2

    try:
        proposed = call_model(build_prompt(prompt_text, args.district, args.jurisdiction))
    except (RuntimeError, requests.RequestException, KeyError, ValueError) as e:
        print(f"error: extraction failed -- {e}", file=sys.stderr)
        return 2

    try:
        # Excerpts are checked against the FULL text, not the narrowed slice,
        # so narrowing can never turn a real quote into a false rejection.
        bundle, rejected = build_bundle(
            proposed,
            full_text,
            jurisdiction=args.jurisdiction,
            district=args.district,
            district_name=args.district_name or args.district,
            code_version=args.code_version,
            effective_date=args.effective_date,
            source_url=args.source_url,
            source_name=Path(args.source).name,
        )
    except RuleError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    bundle.save(args.out)
    found = sum(1 for r in bundle.rules.values() if r.provenance is Provenance.LLM_EXTRACTED)
    print(f"Wrote {args.out}")
    print(f"  {found} of {len(WANTED)} standards extracted with a verified excerpt")
    for line in rejected:
        print(f"  - {line}")
    print("\nThis is a DRAFT. Review it before use:")
    print(f"  python -m tools.verify_bundle {args.out} --reviewer \"Your Name\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
