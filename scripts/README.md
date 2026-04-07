# WikiMind Scripts

Standalone CLI utilities that wrap the WikiMind gateway. These are not
imported by the application; they exist to support manual benchmarking,
debugging, and operations workflows.

## run_test_matrix.py

Systematically benchmark LLM providers across document types.

### Setup

1. Start the WikiMind backend: `make dev`
2. Configure the providers you want to test (set their API keys in `.env`)
3. Restart `make dev` so the providers auto-enable

### Run a single test

```bash
python scripts/run_test_matrix.py \
  --doc ~/papers/attention-is-all-you-need.pdf \
  --doc-type academic-paper \
  --question "What is the time complexity of self-attention?" \
  --provider anthropic
```

The script will:

1. Verify the gateway is up at `http://localhost:7842` (override with `--base-url`).
2. Verify the requested provider is configured and enabled in `/settings`.
3. Ingest the document (URL, PDF, or text file — auto-detected from `--doc`).
4. Poll `/ingest/sources/{id}` until the source compiles or fails (default
   timeout 5 minutes; override with `--timeout`).
5. Record compilation latency and the LLM cost delta from `/settings/llm/cost`.
6. POST `/query` with the question and record the citation count.
7. Append a row to `docs/test-matrix-results.md` (override with `--output`).

### Run a sweep (manually orchestrated)

For each provider you have configured, run the same test:

```bash
for p in anthropic openai google; do
  python scripts/run_test_matrix.py --provider $p \
    --doc ~/sample.pdf --doc-type slide-deck \
    --question "What is X?"
done
```

Then open `docs/test-matrix-results.md` and fill in the manual quality scores
(Accuracy / Attribution / Completeness / Calibration) for each row.

### Arguments

| Flag | Required | Description |
|------|----------|-------------|
| `--doc` | yes | Path to a PDF/text file or an `http(s)` URL |
| `--doc-type` | yes | Short label for the row (e.g. `slide-deck`, `academic-paper`) |
| `--question` | yes | The question to ask after compilation |
| `--provider` | yes | One of `anthropic`, `openai`, `google`, `ollama` |
| `--base-url` | no | Default `http://localhost:7842` |
| `--output` | no | Default `docs/test-matrix-results.md` |
| `--timeout` | no | Compilation poll timeout in seconds (default `300`) |

### Notes

- The script does not grade answer quality. It records latency, cost, and
  citation count automatically; humans grade the 1-5 quality columns by
  editing the markdown table after the run.
- Cost is captured as a delta against `/settings/llm/cost` so it covers both
  compile and Q&A LLM calls performed during the run.
- The script depends only on `httpx` (already a WikiMind runtime dependency)
  plus the Python standard library.
