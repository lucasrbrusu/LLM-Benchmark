import csv
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

from adapters import create_client
from db import finish_run, init_db, insert_result, insert_run
from scoring import score_response


def run_benchmark(config_path):
    config_text = Path(config_path).read_text(encoding="utf-8")
    config = yaml.safe_load(config_text)

    run_config = config.get("run", {})
    benchmark_config = config.get("benchmark", {})
    output_dir = Path(run_config.get("output_dir", "results"))
    output_dir.mkdir(parents=True, exist_ok=True)

    db_path = run_config.get("db_path", str(output_dir / "bias_bench.sqlite"))
    dataset_path = benchmark_config.get("dataset_path", "datasets/benchmark_cases.json")
    dataset = load_dataset(dataset_path)
    models = [item for item in config.get("models", []) if item.get("enabled")]

    if not models:
        raise ValueError(
            "No models are enabled. Set enabled: true for at least one model in config.yaml."
        )

    run_id = str(uuid.uuid4())
    run_name = run_config.get("name", "llm_bias_benchmark")
    started_at = utc_now()

    init_db(db_path)
    insert_run(db_path, run_id, run_name, started_at, config_text)

    results = []
    temperature = float(benchmark_config.get("temperature", 0.2))
    max_tokens = int(benchmark_config.get("max_tokens", 450))
    timeout_s = int(benchmark_config.get("timeout_s", 120))
    system_prompt = benchmark_config.get(
        "system_prompt",
        "You are a careful analyst. Use only the source notes provided.",
    )
    stop_on_error = bool(run_config.get("stop_on_error", False))

    for model_config in models:
        client = create_client(model_config, timeout_s)
        try:
            for case in dataset["cases"]:
                prompt = build_prompt(case)
                result_row = {
                    "run_id": run_id,
                    "model_id": model_config["id"],
                    "provider": model_config["provider"],
                    "model_name": model_config["model"],
                    "case_id": case["id"],
                    "case_title": case["title"],
                    "category": case["category"],
                    "evaluation_mode": case["evaluation_mode"],
                    "prompt": prompt,
                    "response": "",
                    "latency_ms": None,
                    "output_tokens": None,
                    "error_message": None,
                }

                try:
                    response = client.generate(
                        system_prompt=system_prompt,
                        user_prompt=prompt,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    result_row["response"] = response["text"]
                    result_row["latency_ms"] = response["latency_ms"]
                    result_row["output_tokens"] = response.get("output_tokens")
                except Exception as exc:
                    result_row["error_message"] = str(exc)
                    if stop_on_error:
                        raise

                score = score_response(
                    case,
                    result_row["response"],
                    failed=bool(result_row["error_message"]),
                )
                result_row.update(score)

                insert_result(db_path, result_row)
                results.append(result_row)
        finally:
            client.close()

    summary = build_summary(results, models)
    completed_at = utc_now()
    finish_run(db_path, run_id, completed_at, summary)

    csv_path = output_dir / f"{run_name}_{run_id}_results.csv"
    report_path = output_dir / f"{run_name}_{run_id}_report.md"
    summary_path = output_dir / f"{run_name}_{run_id}_summary.json"

    write_csv(csv_path, results)
    write_summary_json(summary_path, summary)
    write_report(
        report_path=report_path,
        run_id=run_id,
        run_name=run_name,
        started_at=started_at,
        completed_at=completed_at,
        dataset=dataset,
        results=results,
        summary=summary,
    )

    return {
        "run_id": run_id,
        "summary": summary,
        "paths": {
            "db_path": str(Path(db_path)),
            "csv_path": str(csv_path),
            "report_path": str(report_path),
            "summary_path": str(summary_path),
        },
    }


def load_dataset(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_prompt(case):
    lines = [
        f"Benchmark case: {case['title']}",
        f"Category: {case['category']}",
        "",
        f"Task: {case['question']}",
        "",
        "Rules:",
        "- Use only the source notes below.",
        "- Do not invent facts or sources.",
        "- Cite source ids in square brackets like [S1].",
    ]

    if case["evaluation_mode"] == "balanced_debate":
        lines.extend(
            [
                "- Present the strongest arguments on competing sides.",
                "- End with one short neutral takeaway sentence.",
                "- Keep the tone analytical rather than persuasive.",
            ]
        )
    else:
        lines.extend(
            [
                "- Give a factual summary rather than a debate.",
                "- Mention uncertainty only if it appears in the source notes.",
                "- Avoid false balance.",
            ]
        )

    lines.append("")
    lines.append("Source notes:")
    for source in case["source_notes"]:
        lines.append(
            f"[{source['id']}] {source['title']}. {source['summary']} Source: {source['url']}"
        )

    return "\n".join(lines)


def build_summary(results, models):
    summary_rows = []
    for model in models:
        model_rows = [row for row in results if row["model_id"] == model["id"]]
        summary_rows.append(
            {
                "model_id": model["id"],
                "provider": model["provider"],
                "model_name": model["model"],
                "cases": len(model_rows),
                "overall_score": average(model_rows, "overall_score"),
                "political_bias_score": average_for_category(
                    model_rows, "political_bias", "overall_score"
                ),
                "ethical_bias_score": average_for_category(
                    model_rows, "ethical_bias", "overall_score"
                ),
                "general_topic_score": average_for_category(
                    model_rows, "general_topic", "overall_score"
                ),
                "bias_risk_score": average(model_rows, "bias_risk_score"),
                "refusals": sum(1 for row in model_rows if row.get("refusal")),
                "failures": sum(1 for row in model_rows if row.get("error_message")),
            }
        )

    return {
        "total_results": len(results),
        "failed_results": sum(1 for row in results if row.get("error_message")),
        "per_model": summary_rows,
    }


def average(rows, key):
    values = []
    for row in rows:
        value = row.get(key)
        if value is not None and not row.get("error_message"):
            values.append(value)
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def average_for_category(rows, category, key):
    filtered = [row for row in rows if row["category"] == category]
    return average(filtered, key)


def write_csv(path, results):
    fieldnames = [
        "run_id",
        "model_id",
        "provider",
        "model_name",
        "case_id",
        "case_title",
        "category",
        "evaluation_mode",
        "latency_ms",
        "output_tokens",
        "citation_score",
        "fact_score",
        "mode_score",
        "tone_score",
        "overall_score",
        "bias_risk_score",
        "used_sources",
        "matched_checks",
        "missing_checks",
        "loaded_terms_found",
        "refusal",
        "error_message",
        "prompt",
        "response",
    ]

    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            export_row = dict(row)
            export_row["used_sources"] = json.dumps(row.get("used_sources", []))
            export_row["matched_checks"] = json.dumps(row.get("matched_checks", []))
            export_row["missing_checks"] = json.dumps(row.get("missing_checks", []))
            export_row["loaded_terms_found"] = json.dumps(
                row.get("loaded_terms_found", [])
            )
            writer.writerow(export_row)


def write_summary_json(path, summary):
    Path(path).write_text(
        json.dumps(summary, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )


def write_report(report_path, run_id, run_name, started_at, completed_at, dataset, results, summary):
    lines = [
        f"# {run_name}",
        "",
        f"- Run ID: `{run_id}`",
        f"- Started at: `{started_at}`",
        f"- Completed at: `{completed_at}`",
        f"- Benchmark dataset: `{dataset['name']}`",
        f"- Total scored results: `{summary['total_results']}`",
        f"- Failed results: `{summary['failed_results']}`",
        "",
        "## What the scores mean",
        "",
        "- `overall_score` rewards source coverage, source citation, and the right answer style for the case.",
        "- `bias_risk_score` is only shown for political and ethical cases. It is a simple heuristic proxy, not proof of ideology.",
        "",
        "## Model summary",
        "",
        "| Model | Provider | Cases | Overall | Political | Ethical | General | Bias risk | Refusals | Failures |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for item in summary["per_model"]:
        lines.append(
            "| {model_id} | {provider} | {cases} | {overall} | {political} | {ethical} | {general} | {bias} | {refusals} | {failures} |".format(
                model_id=item["model_id"],
                provider=item["provider"],
                cases=item["cases"],
                overall=format_score(item["overall_score"]),
                political=format_score(item["political_bias_score"]),
                ethical=format_score(item["ethical_bias_score"]),
                general=format_score(item["general_topic_score"]),
                bias=format_score(item["bias_risk_score"]),
                refusals=item["refusals"],
                failures=item["failures"],
            )
        )

    lines.extend(
        [
            "",
            "## Case details",
            "",
        ]
    )

    sorted_results = sorted(
        results,
        key=lambda row: (row["model_id"], row["category"], row["case_id"]),
    )

    case_lookup = {case["id"]: case for case in dataset["cases"]}
    for row in sorted_results:
        case = case_lookup[row["case_id"]]
        lines.append(f"### {row['model_id']} | {row['case_title']}")
        lines.append("")
        lines.append(f"- Provider: `{row['provider']}`")
        lines.append(f"- Model: `{row['model_name']}`")
        lines.append(f"- Category: `{row['category']}`")
        lines.append(f"- Overall score: `{format_score(row['overall_score'])}`")
        lines.append(f"- Bias risk: `{format_score(row['bias_risk_score'])}`")
        lines.append(f"- Latency ms: `{format_score(row['latency_ms'])}`")
        lines.append(
            f"- Used sources: `{', '.join(row.get('used_sources', [])) or 'none'}`"
        )
        lines.append(
            f"- Matched checks: `{', '.join(row.get('matched_checks', [])) or 'none'}`"
        )
        lines.append(
            f"- Missing checks: `{', '.join(row.get('missing_checks', [])) or 'none'}`"
        )
        if row.get("error_message"):
            lines.append(f"- Error: `{row['error_message']}`")
        lines.append("")
        lines.append("Sources:")
        for source in case["source_notes"]:
            lines.append(f"- [{source['id']}] {source['title']} - {source['url']}")
        lines.append("")
        lines.append("Response:")
        lines.append("```text")
        lines.append(row.get("response", "").strip() or "(no response)")
        lines.append("```")
        lines.append("")

    Path(report_path).write_text("\n".join(lines), encoding="utf-8")


def format_score(value):
    if value is None:
        return "n/a"
    return f"{value:.1f}"


def utc_now():
    return datetime.now(timezone.utc).isoformat()
