# Tests

```bash
pip install -r requirements.txt pytest
python -m pytest tests/ -q
```

The suite covers the engine, not the Streamlit UI or the live GIS/LLM calls,
so it runs offline with no API key.

What it is actually checking:

| File | Guards |
| --- | --- |
| `test_rules.py` | A value without a citation cannot exist; "unregulated" never collapses to zero; strict mode rejects anything a human has not verified |
| `test_envelope.py` | Setback geometry against hand calculations, corner lots, irregular boundaries, easement subtraction, which cap binds, determinism |
| `test_program.py` | FAR vs. stacking, density vs. floor area, and whether the required parking physically fits |
| `test_validate.py` | Model output that exceeds the envelope is caught — including a footprint that is the right size but in the wrong place |
| `test_catalog.py` | An unknown district refuses rather than guessing |
| `test_cli.py` | End-to-end runs over the shipped bundles and sample parcel |
