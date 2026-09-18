# TerraIQ

Two things live in this repo, both real and runnable:

1. **TerraIQ Parcel Analyzer** (`app.py`) — looks up a parcel's zoning in Loudoun County, VA, **computes** its buildable envelope with a deterministic rule engine, and then has an LLM propose concept plans *inside* that envelope.
2. **Portfolio Intelligence** (`pages/1_Portfolio_Intelligence.py`) — a Bronze/Silver/Gold data pipeline, a trained ML site-ranking model, a FastAPI ingestion service, and an LLM-generated executive report, built to demonstrate the data engineering work described in the "Data Engineer / AI Practitioner" experience entry on [akshitrampershad.com](https://akshitrampershad.com).

Both are one Streamlit app — Portfolio Intelligence shows up as a second page in the sidebar.

## 1. TerraIQ Parcel Analyzer

1. **Locate the parcel** — enter an address in Loudoun County (geocoded via [Nominatim/OpenStreetMap](https://nominatim.openstreetmap.org/)), or provide latitude/longitude directly.
2. **Fetch zoning data** — the app queries [Loudoun County's public zoning GIS service](https://logis.loudoun.gov/) for the parcel's zoning district in real time.
3. **Compute the buildable envelope** — a deterministic rule engine (`engine/`) applies the district's dimensional standards to the lot geometry. No model involved: same input, same answer, every time, with the code section cited for every number.
4. **Generate concept plans** — the computed envelope is handed to an LLM ([Groq](https://groq.com/)-hosted `openai/gpt-oss-120b`) as a fixed budget. The model allocates space within it; it never decides how much may be built.
5. **Re-check every concept** — anything the model returns is validated back against the envelope. A concept that exceeds a limit, or places a footprint in a setback, is reported as a violation instead of being drawn.

### Why the envelope is computed rather than generated

Everything downstream of a concept plan — permit review, an architect's stamp,
any claim that a design is compliant — depends on the numbers being
reproducible and attributable. A floor-area figure that a model produced at
`temperature=0.5` is neither: it changes between runs, and it cannot name the
ordinance section it came from. So the split is strict:

| Decided by the rule engine | Decided by the model |
| --- | --- |
| Buildable area after setbacks and overlays | How to shape a footprint within it |
| Maximum footprint, stories, height | Unit mix and floor plate strategy |
| Gross floor area, unit yield, parking demand | Which trade-offs to present, and why |
| Which rule binds, and its citation | Narrative explanation |

**Every dimensional standard carries a provenance marker** — `placeholder`,
`llm_extracted`, or `human_verified`. Only `human_verified` values pass strict
mode (`--strict`). **The district bundles currently shipped in
`reference/districts/` are all placeholders**: structurally plausible, not
transcribed from Loudoun's ordinance. Every report says so on its face. They
exist to exercise the engine, not to answer a zoning question.

When a district has no bundle on file, the engine stops and says so. It does
not fall back to a "typical" district and it does not ask a model to recall the
standards — an invented setback is worse than no answer, because it looks like
an answer.

### Known gap: lot geometry

The GIS query returns zoning for a *point*, not the parcel polygon, so the app
currently synthesizes a rectangular lot from a typed-in acreage and labels it
as assumed. Setback losses depend heavily on real shape, frontage and
orientation, so those areas are indicative until the parcel layer is wired in.
The engine itself already handles arbitrary polygons — see
`reference/parcels/irregular-corner.json`, a corner lot with a clipped corner
and a sewer easement that splits the buildable area in two.

### Transcribing a jurisdiction's standards

The bundles ship as placeholders because a real one has to come out of the
published ordinance. `tools/` is the pipeline for getting there, and it is
built so that no step can quietly invent a number.

```bash
# 1. Draft from the ordinance text (needs GROQ_API_KEY and a local copy)
python -m tools.extract_ordinance \
    --source loudoun-chapter-2.pdf \
    --grep "R-16" \
    --jurisdiction "Loudoun County, VA" --district R-16 \
    --district-name "Townhouse/Multifamily Residential" \
    --code-version "2023 Zoning Ordinance, adopted 2023-12-13" \
    --effective-date 2023-12-13 \
    --out reference/districts/loudoun-county-va/R-16.json

# 2. Review it — this is the only thing that can set human_verified
python -m tools.verify_bundle reference/districts/loudoun-county-va/R-16.json \
    --reviewer "Your Name"

# 3. Check for transcription slips
python -m tools.lint_bundles
```

**The extraction step requires evidence.** Every value the model proposes must
come with a verbatim excerpt, and that excerpt is checked against the source
document character for character (whitespace-normalized, so PDF line wrapping
is fine). A value whose quote is not in the document is discarded before it
reaches the file:

```
- max_far: quoted excerpt is not present in loudoun-chapter-2.pdf -- discarded
```

Anything not found is written as `null` with a `NOT FOUND ... transcribe by
hand` citation, so gaps are visible in the file rather than surfacing as a
crash later. Excerpts are matched against the *whole* document even when
`--grep` narrowed the prompt, so narrowing can never cause a false rejection.

**Verification is a person putting their name to a number.** `verify_bundle`
shows the value, its citation and the excerpt it came from, and records
`verified_by` and `verified_on`. The schema refuses to construct a
`human_verified` value that names nobody. Use `--only setback_front` to
re-check a single standard after an amendment.

**The linter** catches the slips that are cheap to make and expensive to find:
values outside a plausible range, a percentage entered as `0.4` instead of
`40`, side and front setbacks swapped, a density stated two ways that
disagree, and a `human_verified` value whose citation is still a placeholder.

### Command line

The engine runs without Streamlit, an API key, or a network connection:

```bash
python analyze.py --list
python analyze.py --district R-16 --acres 0.75 --frontage 150
python analyze.py --district R-16 --parcel reference/parcels/irregular-corner.json
python analyze.py --district R-16 --acres 0.75 --strict   # refuses: standards unverified
```

### Tests

```bash
python -m pytest tests/ -q
```

89 tests covering setback geometry against hand calculations, corner lots,
irregular boundaries, easement subtraction, which constraint binds, the
validation layer that catches model output exceeding the envelope, and the
transcription pipeline — including that a fabricated ordinance quote is
rejected. See `tests/README.md`.

Scope: zoning lookups are specific to Loudoun County, VA (the GIS endpoint and
geocoding query are hardcoded to that jurisdiction). This is a feasibility
tool, not a substitute for a licensed architect, a zoning attorney, or the
jurisdiction's own review.

**Data provenance:** all parcel/zoning data is synthetically generated (`pipeline/generate_sample_data.py`), seeded for reproducibility, with field names and value ranges modeled on public Loudoun County parcel/zoning structure. It is not scraped or downloaded from any live system, and realistic data-quality issues (nulls, negative values, duplicates) are deliberately injected so the Silver-layer quality checks have real problems to catch.

### FastAPI service endpoints
Run standalone with `uvicorn api.ingestion_service:app --reload --port 8000` (the Streamlit page calls the same pipeline functions in-process, so this is optional — useful for exercising the ingestion API directly):

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Liveness check; reports the active backend (local vs. databricks) |
| `POST /ingest` | Accept a batch of parcel records, land them in Bronze |
| `POST /pipeline/run` | Run the full Bronze → Silver → Gold pipeline (auto-generates sample data on first run) |
| `GET /pipeline/status` | Latest pipeline run metrics |
| `GET /parcels/top` | Top-N parcels by predicted development suitability |
| `GET /parcels/{id}` | Look up a single parcel from the Gold layer |
| `POST /report/generate` | Synthesize the latest run into an executive report |

## Tech Stack
- **[Streamlit](https://streamlit.io/)** — UI and app framework
- **[Groq API](https://groq.com/)** (GPT-OSS 120B, `openai/gpt-oss-120b`) — concept plan generation and executive reporting
- **[DuckDB](https://duckdb.org/)** + **Parquet** — local medallion pipeline (stand-in for Databricks Lakehouse)
- **[scikit-learn](https://scikit-learn.org/)** — site-ranking model training (stand-in for Databricks AutoML)
- **[FastAPI](https://fastapi.tiangolo.com/)** — parcel ingestion/query service
- **[Plotly](https://plotly.com/python/)** — building layout visualization
- **[Shapely](https://shapely.readthedocs.io/)** — the envelope geometry (per-lot-line setback buffering, overlay subtraction)
- **Loudoun County ArcGIS REST API** / **Nominatim (OpenStreetMap)** — zoning data source and geocoding, for TerraIQ only

## Project Structure
| Path | Purpose |
| --- | --- |
| `app.py` | TerraIQ Streamlit UI — parcel input, zoning lookup, envelope, concepts |
| `analyze.py` | CLI for the engine — no Streamlit, no API key, no network |
| `engine/rules.py` | Rule bundles: every standard carries a citation and a provenance marker |
| `engine/parcel.py` | Lot geometry and lot-line classification |
| `engine/envelope.py` | Deterministic buildable-envelope computation |
| `engine/program.py` | Massing, unit yield, parking demand |
| `engine/validate.py` | Checks model-proposed concepts against the envelope |
| `engine/report.py` | Renders the analysis with the authority for every number |
| `engine/catalog.py` | District code → rule bundle, refusing to guess |
| `reference/districts/` | Per-district rule bundles (currently placeholders) |
| `reference/parcels/` | Sample parcel geometry |
| `tools/extract_ordinance.py` | Draft a bundle from ordinance text; discards any value it cannot quote |
| `tools/verify_bundle.py` | Interactive human review — the only path to `human_verified` |
| `tools/lint_bundles.py` | Completeness, citation quality and plausibility checks |
| `tests/` | 89 tests, offline |
| `zoning.py` | Queries Loudoun County's zoning GIS endpoint |
| `gpt_functions.py` | Asks Groq to allocate space within a computed envelope |
| `layout_utils.py` | Renders lot, envelope and proposed building as a Plotly site plan |
| `groq_client.py` | Shared Groq API config/key lookup (Streamlit secrets or env var) |
| `pages/1_Portfolio_Intelligence.py` | Portfolio Intelligence Streamlit page |
| `pipeline/generate_sample_data.py` | Synthetic parcel/zoning dataset generator |
| `pipeline/medallion.py` | Bronze → Silver → Gold pipeline (DuckDB + Parquet) |
| `pipeline/train_model.py` | Trains and selects the site-ranking model |
| `pipeline/executive_report.py` | LLM (Groq) executive report generator, with offline fallback |
| `pipeline/cloud_adapters.py` | AWS/Databricks placeholder adapters |
| `api/ingestion_service.py` | FastAPI ingestion/query/report service |
| `requirements.txt` | Python dependencies |
| `.devcontainer/` | GitHub Codespaces config |

## Getting Started

### Prerequisites
- Python 3.11+
- A [Groq API key](https://console.groq.com/keys) (optional for Portfolio Intelligence — it falls back to a numbers-only report without one; required for TerraIQ's concept generation)

### Setup
```bash
git clone https://github.com/AkshitRampershad/TerraIQ.git
cd TerraIQ
pip install -r requirements.txt
```

Add your Groq API key as a Streamlit secret (never commit this file — it's gitignored):
```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# then edit .streamlit/secrets.toml with your real key
```

Run the app:
```bash
streamlit run app.py
```

The app opens at `http://localhost:8501`, with **Portfolio Intelligence** available as a second page in the sidebar.

### Using GitHub Codespaces
This repo includes a `.devcontainer` configuration — opening it in a Codespace installs dependencies and launches Streamlit on port 8501 automatically. You'll still need to add `GROQ_API_KEY` as a Codespaces secret before TerraIQ's concept-generation step will work (Portfolio Intelligence works without it).

### Deploying to Streamlit Community Cloud
1. Push this repo to GitHub (already done if you're reading this from the deployed app's source).
2. At [share.streamlit.io](https://share.streamlit.io), create a new app pointing at this repo, branch, and `app.py` as the entry point.
3. In the app's **Settings → Secrets**, paste:
   ```toml
   GROQ_API_KEY = "your-groq-api-key"
   ```
4. Deploy. Portfolio Intelligence works immediately (data/model are generated on first click); TerraIQ's concept generation needs the secret above.

### Using a real AWS/Databricks backend
By default the pipeline runs entirely locally. To point it at real infrastructure once you have workspace access, set `PIPELINE_BACKEND=databricks` and populate the config in `pipeline/cloud_adapters.py` (AWS region/S3 bucket, Databricks host/token, AutoML experiment ID, MLflow tracking URI, DLT pipeline ID, LakeFlow job ID) — then implement the SDK calls documented in each adapter function.
