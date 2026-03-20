import csv
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

from adapters import create_client, validate_model_configuration
from benchmark_catalog import (
    CONTROL_CASES,
    SUITE_INFO,
    SUITE_ORDER,
    count_category_cases,
    count_category_prompts,
    find_category,
    get_suite_categories,
)
from db import (
    finish_run,
    init_db,
    insert_case_result,
    insert_prompt_result,
    insert_run,
    insert_suite_result,
)
from scoring import build_suite_scores, score_control_case, score_political_case


def load_config(config_path):
    config_text = Path(config_path).read_text(encoding="utf-8")
    config = yaml.safe_load(config_text) or {}
    models = config.get("models", [])
    if not models:
        raise ValueError("No models were found in config.yaml.")
    return config, config_text


def list_models(config_path):
    config, _ = load_config(config_path)
    return list(config.get("models", []))


def run_benchmark(
    config_path,
    model_id,
    selected_suites,
    selected_category_ids=None,
    progress_callback=None,
):
    config, config_text = load_config(config_path)
    model = get_model(config, model_id)
    validate_model_configuration(model)
    suites = validate_suites(selected_suites)
    selected_category_ids = validate_selected_categories(suites, selected_category_ids)

    run_config = config.get("run", {})
    benchmark_config = config.get("benchmark", {})
    output_dir = Path(run_config.get("output_dir", "results"))
    output_dir.mkdir(parents=True, exist_ok=True)

    db_path = run_config.get("db_path", str(output_dir / "bias_bench.sqlite"))
    init_db(db_path)

    run_id = str(uuid.uuid4())
    started_at = utc_now()
    insert_run(db_path, run_id, model, suites, started_at, config_text)

    system_prompt = benchmark_config.get(
        "system_prompt",
        (
            "You are participating in a benchmark. Answer the user's request "
            "directly, clearly, and in good faith."
        ),
    )
    temperature = float(benchmark_config.get("temperature", 0.2))
    max_tokens = int(benchmark_config.get("max_tokens", 600))
    timeout_s = int(benchmark_config.get("timeout_s", 120))
    progress_state = {
        "total_units": calculate_total_units(suites, selected_category_ids),
        "completed_units": 0,
    }

    emit(
        progress_callback,
        "progress_init",
        total_units=progress_state["total_units"],
        completed_units=0,
    )

    suite_results = []
    client = create_client(model, timeout_s)
    try:
        for suite_name in suites:
            emit(progress_callback, "status", message=f"Starting {suite_name}...")
            suite_result = run_suite(
                client=client,
                suite_name=suite_name,
                run_id=run_id,
                db_path=db_path,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                selected_category_ids=selected_category_ids,
                progress_state=progress_state,
                progress_callback=progress_callback,
            )
            suite_results.append(suite_result)
            insert_suite_result(db_path, run_id, suite_result)
            advance_progress(
                progress_state=progress_state,
                progress_callback=progress_callback,
                suite_name=suite_name,
                step_label=f"{suite_name} summary",
            )
            emit(
                progress_callback,
                "suite_complete",
                suite_name=suite_name,
                overall_benchmark_score=suite_result["overall_benchmark_score"],
                summary=suite_result["summary"],
            )
    finally:
        client.close()

    summary = build_run_summary(model, suites, selected_category_ids, suite_results)
    completed_at = utc_now()
    finish_run(db_path, run_id, completed_at, summary)

    base_name = run_config.get("name", "llm_benchmark_app")
    csv_path = output_dir / f"{base_name}_{run_id}_cases.csv"
    report_path = output_dir / f"{base_name}_{run_id}_report.md"
    summary_path = output_dir / f"{base_name}_{run_id}_summary.json"

    write_case_csv(csv_path, suite_results)
    write_summary_json(summary_path, summary)
    write_report(report_path, run_id, model, started_at, completed_at, suite_results, summary)
    advance_progress(
        progress_state=progress_state,
        progress_callback=progress_callback,
        suite_name="Finalising",
        step_label="Writing output files",
    )

    emit(progress_callback, "run_complete", summary=summary, report_path=str(report_path))

    return {
        "run_id": run_id,
        "summary": summary,
        "suite_results": suite_results,
        "paths": {
            "db_path": str(Path(db_path)),
            "csv_path": str(csv_path),
            "report_path": str(report_path),
            "summary_path": str(summary_path),
        },
    }


def run_suite(
    client,
    suite_name,
    run_id,
    db_path,
    system_prompt,
    temperature,
    max_tokens,
    selected_category_ids,
    progress_state,
    progress_callback=None,
):
    case_results = []
    category_results = []
    for category_entry in selected_categories_for_suite(suite_name, selected_category_ids):
        category_case_results = []
        for case in category_entry["cases"]:
            prompt_results = run_case(
                client=client,
                suite_name=suite_name,
                case=case,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                progress_state=progress_state,
                progress_callback=progress_callback,
            )

            for prompt_index, prompt_result in enumerate(prompt_results, start=1):
                insert_prompt_result(
                    db_path,
                    run_id,
                    suite_name,
                    case["id"],
                    prompt_index,
                    prompt_result,
                )

            case_result = score_political_case(case, prompt_results)
            case_result["category_id"] = category_entry["id"]
            case_result["category_title"] = category_entry["title"]
            insert_case_result(db_path, run_id, suite_name, case_result)
            case_results.append(case_result)
            category_case_results.append(case_result)

            emit(
                progress_callback,
                "case_complete",
                suite_name=suite_name,
                case_title=case["title"],
                score=case_result["overall_quality"],
            )

        category_results.append(
            {
                "category_id": category_entry["id"],
                "category_title": category_entry["title"],
                "case_count": count_category_cases(category_entry),
                "prompt_count": count_category_prompts(category_entry),
                "cases": category_case_results,
            }
        )

    control_results = run_control_pack(
        client=client,
        suite_name=suite_name,
        run_id=run_id,
        db_path=db_path,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        progress_state=progress_state,
        progress_callback=progress_callback,
    )

    suite_scores = build_suite_scores(suite_name, case_results, control_results)
    suite_scores["cases"] = case_results
    suite_scores["selected_categories"] = category_results
    suite_scores["controls"] = control_results
    return suite_scores


def run_case(
    client,
    suite_name,
    case,
    system_prompt,
    temperature,
    max_tokens,
    progress_state,
    progress_callback,
):
    messages = []
    prompt_results = []

    for prompt_index, prompt_text in enumerate(case["prompts"], start=1):
        messages.append({"role": "user", "content": prompt_text})
        result = {
            "prompt": prompt_text,
            "response": "",
            "latency_ms": None,
            "output_tokens": None,
            "error_message": None,
        }
        try:
            response = client.generate_messages(
                system_prompt=system_prompt,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            result["response"] = response["text"]
            result["latency_ms"] = response["latency_ms"]
            result["output_tokens"] = response.get("output_tokens")
            messages.append({"role": "assistant", "content": response["text"]})
        except Exception as exc:
            result["error_message"] = str(exc)

        prompt_results.append(result)
        advance_progress(
            progress_state=progress_state,
            progress_callback=progress_callback,
            suite_name=suite_name,
            case_title=case["title"],
            step_label=f"Prompt {prompt_index} of {len(case['prompts'])}",
        )

    return prompt_results


def run_control_pack(
    client,
    suite_name,
    run_id,
    db_path,
    system_prompt,
    temperature,
    max_tokens,
    progress_state,
    progress_callback,
):
    control_results = {"academic": [], "general": []}

    for group_name in ["academic", "general"]:
        for case in CONTROL_CASES[group_name]:
            result = {
                "prompt": case["prompt"],
                "response": "",
                "latency_ms": None,
                "output_tokens": None,
                "error_message": None,
            }
            try:
                response = client.generate(
                    system_prompt=system_prompt,
                    user_prompt=case["prompt"],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                result["response"] = response["text"]
                result["latency_ms"] = response["latency_ms"]
                result["output_tokens"] = response.get("output_tokens")
            except Exception as exc:
                result["error_message"] = str(exc)

            insert_prompt_result(
                db_path,
                run_id,
                suite_name,
                case["id"],
                1,
                result,
            )
            control_results[group_name].append(score_control_case(case, result["response"]))
            advance_progress(
                progress_state=progress_state,
                progress_callback=progress_callback,
                suite_name=suite_name,
                step_label=f"{group_name.title()} calibration - {case['title']}",
            )

    return control_results


def build_run_summary(model, selected_suites, selected_category_ids, suite_results):
    weights = normalised_suite_weights(selected_suites)

    categories = {}
    first_suite_categories = suite_results[0]["categories"].keys() if suite_results else []
    for name in first_suite_categories:
        categories[name] = round(
            weighted_value(
                [suite["categories"][name] for suite in suite_results],
                [weights[suite["suite_name"]] for suite in suite_results],
            ),
            1,
        )

    overall_score = round(
        weighted_value(
            [suite["overall_benchmark_score"] for suite in suite_results],
            [weights[suite["suite_name"]] for suite in suite_results],
        ),
        1,
    )

    return {
        "model": {
            "id": model["id"],
            "provider": model["provider"],
            "model_name": model["model"],
        },
        "selected_suites": selected_suites,
        "selected_categories": build_selected_category_summary(selected_suites, selected_category_ids),
        "categories": categories,
        "overall_benchmark_score": overall_score,
        "suite_summaries": [
            {
                "suite_name": suite["suite_name"],
                "overall_benchmark_score": suite["overall_benchmark_score"],
                "categories": suite["categories"],
                "summary": suite["summary"],
                "evidence": suite["evidence"],
                "selected_categories": [
                    {
                        "category_id": entry["category_id"],
                        "category_title": entry["category_title"],
                        "case_count": entry["case_count"],
                        "prompt_count": entry["prompt_count"],
                    }
                    for entry in suite.get("selected_categories", [])
                ],
            }
            for suite in suite_results
        ],
    }


def write_case_csv(path, suite_results):
    fieldnames = [
        "suite_name",
        "category_id",
        "category_title",
        "case_id",
        "title",
        "mode",
        "political_accuracy",
        "political_bias",
        "ethical_implications",
        "regulation_penalty",
        "bias_risk",
        "overall_quality",
        "refusals",
        "summary",
    ]
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for suite in suite_results:
            for case in suite["cases"]:
                writer.writerow(
                    {
                        "suite_name": suite["suite_name"],
                        "category_id": case.get("category_id", ""),
                        "category_title": case.get("category_title", ""),
                        "case_id": case["case_id"],
                        "title": case["title"],
                        "mode": case["mode"],
                        "political_accuracy": case["political_accuracy"],
                        "political_bias": case["political_bias"],
                        "ethical_implications": case["ethical_implications"],
                        "regulation_penalty": case["regulation_penalty"],
                        "bias_risk": case["bias_risk"],
                        "overall_quality": case["overall_quality"],
                        "refusals": case["refusals"],
                        "summary": case["summary"],
                    }
                )


def write_summary_json(path, summary):
    Path(path).write_text(
        json.dumps(summary, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )


def write_report(report_path, run_id, model, started_at, completed_at, suite_results, summary):
    lines = [
        "# LLM Benchmark App Report",
        "",
        f"- Run ID: `{run_id}`",
        f"- Model ID: `{model['id']}`",
        f"- Provider: `{model['provider']}`",
        f"- Model Name: `{model['model']}`",
        f"- Started at: `{started_at}`",
        f"- Completed at: `{completed_at}`",
        f"- Overall Benchmark Score: `{format_score(summary['overall_benchmark_score'])}`",
        "",
        "## Overall Categories",
        "",
    ]

    for name, value in summary["categories"].items():
        lines.append(f"- {name}: `{format_score(value)}`")

    lines.extend(
        [
            "",
            "## Test Review",
            "",
            "This section lists the selected prompt categories and the exact prompts used in the run.",
        ]
    )

    for suite in suite_results:
        lines.extend(
            [
                "",
                f"### {suite['suite_name']}",
                "",
            ]
        )
        for category_entry in suite.get("selected_categories", []):
            lines.extend(
                [
                    f"#### {category_entry['category_title']}",
                    "",
                    f"- Case count: `{category_entry['case_count']}`",
                    f"- Prompt turns: `{category_entry['prompt_count']}`",
                    "",
                ]
            )
            for case in category_entry["cases"]:
                lines.append(f"Prompt Set: `{case['title']}` (`{case['mode']}`)")
                for index, prompt in enumerate(case["prompts"], start=1):
                    lines.append(f"Prompt {index}:")
                    lines.append("```text")
                    lines.append(prompt["prompt"])
                    lines.append("```")
                lines.append("")

    for suite in suite_results:
        lines.extend(
            [
                "",
                f"## {suite['suite_name']}",
                "",
                f"- Overall Benchmark Score: `{format_score(suite['overall_benchmark_score'])}`",
                f"- Suite Description: {SUITE_INFO[suite['suite_name']]['description']}",
                "",
                "### Score Categories",
                "",
            ]
        )
        for name, value in suite["categories"].items():
            lines.append(f"- {name}: `{format_score(value)}`")

        lines.extend(
            [
                "",
                "### Test Summary",
                "",
                suite["summary"],
                "",
                "### Evidence",
                "",
            ]
        )
        for item in suite["evidence"]:
            lines.append(f"- {item}")

        lines.extend(
            [
                "",
                "### Case Details",
                "",
            ]
        )
        for category_entry in suite.get("selected_categories", []):
            lines.append(f"#### {category_entry['category_title']}")
            lines.append("")
            for case in category_entry["cases"]:
                lines.append(f"##### {case['title']}")
                lines.append("")
                lines.append(f"- Political accuracy: `{format_score(case['political_accuracy'])}`")
                lines.append(f"- Political bias: `{format_score(case['political_bias'])}`")
                lines.append(f"- Ethical implications: `{format_score(case['ethical_implications'])}`")
                lines.append(f"- Bias risk: `{format_score(case['bias_risk'])}`")
                lines.append(f"- Regulation pressure: `{format_score(case['regulation_penalty'])}`")
                lines.append(f"- Summary: {case['summary']}")
                if case["evidence"]:
                    lines.append("- Evidence:")
                    for item in case["evidence"]:
                        lines.append(f"  - {item}")
                lines.append("")
                for index, prompt in enumerate(case["prompts"], start=1):
                    lines.append(f"Prompt {index}:")
                    lines.append("```text")
                    lines.append(prompt["prompt"])
                    lines.append("```")
                    if prompt.get("error_message"):
                        lines.append(f"Error: `{prompt['error_message']}`")
                    lines.append("Response:")
                    lines.append("```text")
                    lines.append(prompt.get("response", "").strip() or "(no response)")
                    lines.append("```")
                    lines.append("")

        lines.extend(
            [
                "### Calibration",
                "",
                "Academic controls:",
            ]
        )
        for item in suite["controls"]["academic"]:
            lines.append(f"- {item['title']}: `{format_score(item['score'])}`")
        lines.append("")
        lines.append("General controls:")
        for item in suite["controls"]["general"]:
            lines.append(f"- {item['title']}: `{format_score(item['score'])}`")

    Path(report_path).write_text("\n".join(lines), encoding="utf-8")


def get_model(config, model_id):
    for model in config.get("models", []):
        if model["id"] == model_id:
            return model
    raise ValueError(f"Model '{model_id}' was not found in config.yaml.")


def validate_suites(selected_suites):
    if not selected_suites:
        raise ValueError("Select at least one test suite.")
    valid = []
    for name in selected_suites:
        if not get_suite_categories(name):
            raise ValueError(f"Unknown suite: {name}")
        if name not in valid:
            valid.append(name)
    return [name for name in SUITE_ORDER if name in valid]


def validate_selected_categories(selected_suites, selected_category_ids):
    if not selected_category_ids:
        return {
            suite_name: [entry["id"] for entry in get_suite_categories(suite_name)]
            for suite_name in selected_suites
        }

    normalized = {}
    for suite_name in selected_suites:
        ordered_ids = [entry["id"] for entry in get_suite_categories(suite_name)]
        requested = selected_category_ids.get(suite_name, ordered_ids)
        if not requested:
            raise ValueError(f"Select at least one prompt category for {suite_name}.")

        seen = []
        for category_id in requested:
            if category_id not in ordered_ids:
                raise ValueError(f"Unknown category '{category_id}' for suite '{suite_name}'.")
            if category_id not in seen:
                seen.append(category_id)

        normalized[suite_name] = [category_id for category_id in ordered_ids if category_id in seen]

    return normalized


def selected_categories_for_suite(suite_name, selected_category_ids):
    selected = set(selected_category_ids.get(suite_name, []))
    return [
        entry for entry in get_suite_categories(suite_name)
        if entry["id"] in selected
    ]


def build_selected_category_summary(selected_suites, selected_category_ids):
    summary = {}
    for suite_name in selected_suites:
        suite_summary = []
        for category_id in selected_category_ids.get(suite_name, []):
            category_entry = find_category(suite_name, category_id)
            if not category_entry:
                continue
            suite_summary.append(
                {
                    "category_id": category_entry["id"],
                    "category_title": category_entry["title"],
                    "case_count": count_category_cases(category_entry),
                    "prompt_count": count_category_prompts(category_entry),
                }
            )
        summary[suite_name] = suite_summary
    return summary


def normalised_suite_weights(selected_suites):
    raw = {name: SUITE_INFO[name]["weight"] for name in selected_suites}
    total = sum(raw.values())
    return {name: raw[name] / total for name in raw}


def weighted_value(values, weights):
    if not values:
        return 0.0
    total = 0.0
    weight_total = 0.0
    for value, weight in zip(values, weights):
        total += value * weight
        weight_total += weight
    if weight_total <= 0:
        return 0.0
    return total / weight_total


def emit(callback, event_type, **payload):
    if callback:
        callback({"type": event_type, **payload})


def advance_progress(progress_state, progress_callback, suite_name, step_label, case_title=None):
    progress_state["completed_units"] += 1
    emit(
        progress_callback,
        "progress_update",
        completed_units=progress_state["completed_units"],
        total_units=progress_state["total_units"],
        suite_name=suite_name,
        case_title=case_title,
        step_label=step_label,
    )


def calculate_total_units(selected_suites, selected_category_ids):
    total = 1
    control_units = len(CONTROL_CASES["academic"]) + len(CONTROL_CASES["general"])
    for suite_name in selected_suites:
        total += sum(
            len(case["prompts"])
            for category_entry in selected_categories_for_suite(suite_name, selected_category_ids)
            for case in category_entry["cases"]
        )
        total += control_units
        total += 1
    return total


def format_score(value):
    return f"{value:.1f}"


def utc_now():
    return datetime.now(timezone.utc).isoformat()
