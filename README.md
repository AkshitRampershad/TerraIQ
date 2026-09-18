# UrbanAI

Two things live in this repo, both real and runnable:

1. **TerraIQ Parcel Analyzer** (`app.py`) — an AI agent that looks up a parcel's zoning in Loudoun County, VA and proposes zoning-constrained concept building plans.
2. **Portfolio Intelligence** (`pages/1_Portfolio_Intelligence.py`) — a Bronze/Silver/Gold data pipeline, a trained ML site-ranking model, a FastAPI ingestion service, and an LLM-generated executive report, built to demonstrate the data engineering work described in the "Data Engineer / AI Practitioner" experience entry on [akshitrampershad.com](https://akshitrampershad.com).

Both are one Streamlit app — Portfolio Intelligence shows up as a second page in the sidebar.

## 1. TerraIQ Parcel Analyzer

1. **Locate the parcel** — enter an address in Loudoun County (geocoded via [Nominatim/OpenStreetMap](https://nominatim.openstreetmap.org/)), or provide latitude/longitude directly.
2. **Fetch zoning data** — the app queries [Loudoun County's public zoning ArcGIS service](https://maps.loudoun.gov/) for the parcel's zoning attributes in real time.
3. **Generate concept plans** — the zoning info and parcel size are sent to an LLM ([Groq](https://groq.com/)-hosted GPT-OSS 120B (openai/gpt-oss-120b)) asking for 2–3 building concepts that maximize investment potential without violating the zoning rules.
4. **Visualize the layout** — each concept's footprint is rendered as an interactive Plotly building outline.

Scope: zoning lookups are specific to Loudoun County, VA (the ArcGIS endpoint and geocoding query are hardcoded to that jurisdiction); concepts are a starting point for exploration, not a substitute for a licensed architect or zoning attorney.

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
- **Loudoun County ArcGIS REST API** / **Nominatim (OpenStreetMap)** — zoning data source and geocoding, for TerraIQ only

## Project Structure
| Path | Purpose |
| --- | --- |
| `app.py` | TerraIQ Streamlit UI — parcel input, zoning lookup, concept generation |
| `zoning.py` | Queries Loudoun County's zoning ArcGIS endpoint |
| `gpt_functions.py` | Calls Groq to generate zoning-constrained building concepts |
| `layout_utils.py` | Renders a concept's footprint as a Plotly figure |
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
git clone https://github.com/AkshitRampershad/UrbanAI.git
cd UrbanAI
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
