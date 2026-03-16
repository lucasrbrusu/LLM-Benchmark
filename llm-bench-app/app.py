import argparse
import sys

from runner import run_benchmark


def format_score(value):
    if value is None:
        return "n/a"
    return f"{value:.1f}"


def main():
    parser = argparse.ArgumentParser(
        description="Run the source-grounded LLM bias benchmark."
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to the YAML config file. Default: config.yaml",
    )
    args = parser.parse_args()

    try:
        result = run_benchmark(args.config)
    except Exception as exc:
        print(f"Benchmark failed: {exc}")
        return 1

    print(f"Run ID: {result['run_id']}")
    print(f"SQLite DB: {result['paths']['db_path']}")
    print(f"CSV export: {result['paths']['csv_path']}")
    print(f"Markdown report: {result['paths']['report_path']}")
    print("")
    print("Model summary:")

    for item in result["summary"]["per_model"]:
        print(
            f"- {item['model_id']}: "
            f"overall={format_score(item['overall_score'])}, "
            f"political={format_score(item['political_bias_score'])}, "
            f"ethical={format_score(item['ethical_bias_score'])}, "
            f"general={format_score(item['general_topic_score'])}, "
            f"bias_risk={format_score(item['bias_risk_score'])}, "
            f"failures={item['failures']}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
