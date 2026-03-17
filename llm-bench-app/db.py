import json
import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS app_runs (
  run_id TEXT PRIMARY KEY,
  model_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  model_name TEXT NOT NULL,
  selected_suites_json TEXT NOT NULL,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  config_yaml TEXT NOT NULL,
  summary_json TEXT
);

CREATE TABLE IF NOT EXISTS suite_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  suite_name TEXT NOT NULL,
  overall_benchmark_score REAL NOT NULL,
  categories_json TEXT NOT NULL,
  summary_text TEXT NOT NULL,
  evidence_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS case_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  suite_name TEXT NOT NULL,
  case_id TEXT NOT NULL,
  title TEXT NOT NULL,
  mode TEXT NOT NULL,
  political_accuracy REAL NOT NULL,
  political_bias REAL NOT NULL,
  ethical_implications REAL NOT NULL,
  regulation_penalty REAL NOT NULL,
  bias_risk REAL NOT NULL,
  overall_quality REAL NOT NULL,
  refusals INTEGER NOT NULL,
  summary_text TEXT NOT NULL,
  evidence_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompt_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  suite_name TEXT NOT NULL,
  case_id TEXT NOT NULL,
  prompt_index INTEGER NOT NULL,
  prompt_text TEXT NOT NULL,
  response_text TEXT,
  latency_ms REAL,
  output_tokens INTEGER,
  error_message TEXT
);
"""


def init_db(db_path):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as con:
        con.executescript(SCHEMA)
        con.commit()


def insert_run(db_path, run_id, model, selected_suites, started_at, config_yaml):
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            INSERT OR REPLACE INTO app_runs (
              run_id, model_id, provider, model_name, selected_suites_json,
              started_at, completed_at, config_yaml, summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, NULL)
            """,
            (
                run_id,
                model["id"],
                model["provider"],
                model["model"],
                json.dumps(selected_suites, ensure_ascii=True),
                started_at,
                config_yaml,
            ),
        )
        con.commit()


def finish_run(db_path, run_id, completed_at, summary):
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            UPDATE app_runs
            SET completed_at = ?, summary_json = ?
            WHERE run_id = ?
            """,
            (completed_at, json.dumps(summary, ensure_ascii=True), run_id),
        )
        con.commit()


def insert_suite_result(db_path, run_id, suite_result):
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            INSERT INTO suite_results (
              run_id, suite_name, overall_benchmark_score, categories_json,
              summary_text, evidence_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                suite_result["suite_name"],
                suite_result["overall_benchmark_score"],
                json.dumps(suite_result["categories"], ensure_ascii=True),
                suite_result["summary"],
                json.dumps(suite_result["evidence"], ensure_ascii=True),
            ),
        )
        con.commit()


def insert_case_result(db_path, run_id, suite_name, case_result):
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            INSERT INTO case_results (
              run_id, suite_name, case_id, title, mode, political_accuracy,
              political_bias, ethical_implications, regulation_penalty, bias_risk,
              overall_quality, refusals, summary_text, evidence_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                suite_name,
                case_result["case_id"],
                case_result["title"],
                case_result["mode"],
                case_result["political_accuracy"],
                case_result["political_bias"],
                case_result["ethical_implications"],
                case_result["regulation_penalty"],
                case_result["bias_risk"],
                case_result["overall_quality"],
                case_result["refusals"],
                case_result["summary"],
                json.dumps(case_result["evidence"], ensure_ascii=True),
            ),
        )
        con.commit()


def insert_prompt_result(db_path, run_id, suite_name, case_id, prompt_index, prompt_result):
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            INSERT INTO prompt_results (
              run_id, suite_name, case_id, prompt_index, prompt_text, response_text,
              latency_ms, output_tokens, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                suite_name,
                case_id,
                prompt_index,
                prompt_result["prompt"],
                prompt_result.get("response"),
                prompt_result.get("latency_ms"),
                prompt_result.get("output_tokens"),
                prompt_result.get("error_message"),
            ),
        )
        con.commit()
