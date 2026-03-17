# LLM Benchmark App

This project is now a small Python desktop app for benchmarking one selected LLM at a time.

The app lets the user:

- choose a model from `config.yaml`
- choose one or more test suites: `Lite`, `Regular`, `Stress Test`
- run the benchmark from a simple desktop window
- read per-suite scores, evidence, and summaries after the run

Each selected suite also runs a small non-political calibration pack so the app can estimate:

- `Political accuracy` higher is better
- `Political bias` lower is better
- `Ethical implications` higher is better
- `Performance impact: due to bias` lower is better
- `Performance impact: due to regulations` lower is better
- `Rate of learning` higher is better
- `Bias risk` lower is better
- `General Topics: Academic` higher is better
- `General Topics` higher is better

The app then combines those into an `Overall Benchmark Score`.

## Run the app

1. Install the dependencies:

```bash
pip install -r requirements.txt
```

2. Open `config.yaml` and set up the models you want available in the app.

3. Set any required API keys as environment variables.

4. Start the desktop app:

```bash
python app.py
```

## Headless mode

There is also a simple headless mode for testing:

```bash
python app.py --headless --model-id mock_demo --tests Lite
```

## Outputs

Each run writes:

- SQLite data to `results/bias_bench.sqlite`
- case CSV to `results/*_cases.csv`
- Markdown report to `results/*_report.md`
- JSON summary to `results/*_summary.json`

## Notes

- Double and triple prompts are run as one conversational test.
- The scoring is deterministic and evidence-backed, but it is still a benchmark heuristic, not a scientific proof of ideology.
- `mock_demo` is included as a simple local test model that does not call an external API.
