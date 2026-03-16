# LLM Bias Benchmark MVP

This project is a small Python benchmark for comparing how different LLMs handle:

- political bias and policy trade-offs
- ethical bias and fairness questions
- a couple of general factual topics

The benchmark is source-grounded. Each test case includes short notes from real sources such as NIST, UNESCO, the European Commission, OECD, FTC, EEOC, NASA, WHO, CDC, and NOAA. Models are asked to answer using only those notes, and the app scores how well they stay grounded, cite sources, and handle the topic in the right style.

## Why this version is simpler

- One command to run: `python app.py`
- No Streamlit dashboard
- SQLite for run history
- CSV and Markdown exports in `results/`
- Small Python files and plain YAML config

## Quick start

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Open `config.yaml`.

3. Enable the model providers you want to test and set the real model IDs.

4. Set the matching API keys as environment variables.

5. Run the benchmark:

```bash
python app.py
```

## Supported providers

- `openai`
- `anthropic`
- `gemini`
- `github_models`
- `openai_compatible`

Notes:

- `github_models` is the simplest GitHub-side API path for models hosted through GitHub Models.
- Consumer GitHub Copilot chat is not called directly by this MVP because it is not exposed as a simple public chat API in the same way.
- `openai_compatible` works with local or hosted endpoints that implement the OpenAI chat completions shape.

## Outputs

- SQLite DB: `results/bias_bench.sqlite`
- Raw CSV export: `results/*_results.csv`
- Markdown report: `results/*_report.md`
- JSON summary: `results/*_summary.json`

## What the scores mean

- `overall_score`: how well the model covered the source-backed facts and followed the requested style
- `bias_risk_score`: a heuristic proxy for imbalance on political and ethical cases only

This is an MVP. It is useful for side-by-side comparisons, but it is not a definitive scientific measurement of ideology.
