# WikiMind Test Matrix Results

Systematic comparison of LLM providers and document types.
Run via `scripts/run_test_matrix.py`. Results below are appended automatically.
Quality scores (1-5) are filled in manually after running.

## Methodology

- **Latency**: wall-clock time from ingest to compilation complete
- **Cost**: USD from CostLog for the compile + Q&A LLM calls combined
- **Output tokens**: from LLM response usage
- **Citations**: number of source articles cited in the Q&A answer
- **Accuracy** (1-5, manual): does the answer match the source?
- **Attribution** (1-5, manual): does it cite the right article?
- **Completeness** (1-5, manual): does it cover the key points?
- **Confidence calibration** (1-5, manual): does it correctly say "I don't know" when it should?

## Results

| Date | Provider | Doc Type | Doc | Latency | Cost | Citations | Accuracy | Attribution | Completeness | Calibration | Notes |
|------|----------|----------|-----|---------|------|-----------|----------|-------------|--------------|-------------|-------|

<!-- Results appended automatically by scripts/run_test_matrix.py -->
| 2026-04-07 | openai | slide-deck | Digital Sovereignty Deck_2026.pdf | 10.1s | $0.0210 | 2 | | | | | |
