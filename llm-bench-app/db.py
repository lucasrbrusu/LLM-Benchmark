import json
import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS benchmark_runs (
  run_id TEXT PRIMARY KEY,
  run_name TEXT NOT NULL,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  config_yaml TEXT NOT NULL,
  summary_json TEXT
);

CREATE TABLE IF NOT EXISTS benchmark_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  model_name TEXT NOT NULL,
  case_id TEXT NOT NULL,
  case_title TEXT NOT NULL,
  category TEXT NOT NULL,
  evaluation_mode TEXT NOT NULL,
  prompt TEXT NOT NULL,
  response TEXT,
  latency_ms REAL,
  output_tokens INTEGER,
  citation_score REAL,
  fact_score REAL,
  mode_score REAL,
  tone_score REAL,
  overall_score REAL,
  bias_risk_score REAL,
  used_sources_json TEXT,
  matched_checks_json TEXT,
  missing_checks_json TEXT,
  refusal INTEGER NOT NULL DEFAULT 0,
  error_message TEXT
);
"""


def init_db(db_path):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as con:
        con.executescript(SCHEMA)
        con.commit()


def insert_run(db_path, run_id, run_name, started_at, config_yaml):
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            INSERT OR REPLACE INTO benchmark_runs(
              run_id, run_name, started_at, completed_at, config_yaml, summary_json
            ) VALUES(?, ?, ?, NULL, ?, NULL)
            """,
            (run_id, run_name, started_at, config_yaml),
        )
        con.commit()


def finish_run(db_path, run_id, completed_at, summary):
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            UPDATE benchmark_runs
            SET completed_at = ?, summary_json = ?
            WHERE run_id = ?
            """,
            (completed_at, json.dumps(summary, ensure_ascii=True), run_id),
        )
        con.commit()


def insert_result(db_path, row):
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            INSERT INTO benchmark_results(
              run_id, model_id, provider, model_name, case_id, case_title, category,
              evaluation_mode, prompt, response, latency_ms, output_tokens,
              citation_score, fact_score, mode_score, tone_score, overall_score,
              bias_risk_score, used_sources_json, matched_checks_json,
              missing_checks_json, refusal, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["run_id"],
                row["model_id"],
                row["provider"],
                row["model_name"],
                row["case_id"],
                row["case_title"],
                row["category"],
                row["evaluation_mode"],
                row["prompt"],
                row.get("response"),
                row.get("latency_ms"),
                row.get("output_tokens"),
                row.get("citation_score"),
                row.get("fact_score"),
                row.get("mode_score"),
                row.get("tone_score"),
                row.get("overall_score"),
                row.get("bias_risk_score"),
                json.dumps(row.get("used_sources", []), ensure_ascii=True),
                json.dumps(row.get("matched_checks", []), ensure_ascii=True),
                json.dumps(row.get("missing_checks", []), ensure_ascii=True),
                1 if row.get("refusal") else 0,
                row.get("error_message"),
            ),
        )
        con.commit()
