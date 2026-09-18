"""Lookup from a jurisdiction's district code to its rule bundle.

The important behaviour here is the failure case. When no bundle exists for a
district, the engine says so and stops. It does not fall back to a "typical"
district, and it does not ask a model to recall the standards -- an invented
setback is worse than no answer, because it looks like an answer.
"""

from __future__ import annotations

import re
from pathlib import Path

from engine.rules import RuleBundle, RuleError

DATA_ROOT = Path(__file__).resolve().parent.parent / "reference" / "districts"


class DistrictNotOnFile(RuleError):
    """No verified-or-placeholder rule bundle exists for this district."""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")


def normalize_district(code: str) -> str:
    """Normalize a district code as GIS returns it ('r8', 'R 8') to 'R-8'."""
    cleaned = re.sub(r"\s+", "", (code or "").strip().upper())
    match = re.fullmatch(r"([A-Z]+)-?(\d+)", cleaned)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    return cleaned


def _folder_for(jurisdiction: str) -> Path | None:
    """Resolve a jurisdiction name to its data folder.

    Tries the exact slug first, then a few spelling variants, so that
    "Loudoun County, VA", "Loudoun County VA" and "loudoun-county-va" all land
    on the same bundles instead of silently reporting no districts on file.
    """
    slug = _slug(jurisdiction)
    candidates = [slug, slug.replace("-county", ""), slug.replace("county-", "")]
    for candidate in candidates:
        folder = DATA_ROOT / candidate
        if folder.is_dir():
            return folder
    return None


def available_districts(jurisdiction: str) -> list[str]:
    folder = _folder_for(jurisdiction)
    if folder is None:
        return []
    return sorted(
        p.stem for p in folder.glob("*.json") if not p.stem.startswith("_")
    )


def load_bundle(jurisdiction: str, district: str) -> RuleBundle:
    """Load the rule bundle for a district, or explain why we cannot."""
    folder = _folder_for(jurisdiction)
    code = normalize_district(district)
    path = (folder / f"{code}.json") if folder is not None else None

    if path is None or not path.is_file():
        known = available_districts(jurisdiction)
        raise DistrictNotOnFile(
            f"No rule bundle on file for {jurisdiction} district {code!r}. "
            + (
                f"Districts available: {', '.join(known)}."
                if known
                else f"No districts are on file for {jurisdiction}."
            )
            + " Add one from reference/districts/_TEMPLATE.json, transcribed from "
            "the published ordinance. The engine will not guess a district's "
            "standards."
        )
    return RuleBundle.from_json(path)
