import argparse
import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from benchmark_catalog import SUITE_INFO, SUITE_ORDER
from runner import list_models, run_benchmark


class BenchmarkApp:
    def __init__(self, root, config_path):
        self.root = root
        self.config_path = config_path
        self.queue = queue.Queue()
        self.run_thread = None
        self.last_result = None
        self.run_started_at = None
        self.progress_total_units = 0
        self.progress_completed_units = 0
        self.progress_detail = ""

        self.models = list_models(config_path)
        self.model_var = tk.StringVar(value=self.default_model_id())
        self.model_display_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Choose a model and one or more test types.")
        self.progress_var = tk.StringVar(value="Progress: idle")
        self.suite_vars = {
            suite_name: tk.BooleanVar(value=(suite_name == "Lite"))
            for suite_name in SUITE_ORDER
        }

        self.root.title("LLM Benchmark App")
        self.root.geometry("1100x760")
        self.root.minsize(980, 680)

        self.build_ui()
        self.populate_model_box()
        self.root.after(150, self.process_queue)

    def build_ui(self):
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)

        header = ttk.Label(
            outer,
            text="LLM Benchmark App",
            font=("Segoe UI", 18, "bold"),
        )
        header.pack(anchor="w")

        subheader = ttk.Label(
            outer,
            text="Pick one model, choose Lite / Regular / Stress Test, then run the benchmark.",
        )
        subheader.pack(anchor="w", pady=(0, 12))

        controls = ttk.LabelFrame(outer, text="Run Setup", padding=12)
        controls.pack(fill="x")

        model_row = ttk.Frame(controls)
        model_row.pack(fill="x", pady=(0, 10))
        ttk.Label(model_row, text="Model:", width=12).pack(side="left")
        self.model_box = ttk.Combobox(
            model_row,
            state="readonly",
            textvariable=self.model_display_var,
        )
        self.model_box.pack(side="left", fill="x", expand=True)

        suite_row = ttk.Frame(controls)
        suite_row.pack(fill="x")
        ttk.Label(suite_row, text="Tests:", width=12).pack(side="left")

        for suite_name in SUITE_ORDER:
            ttk.Checkbutton(
                suite_row,
                text=suite_name,
                variable=self.suite_vars[suite_name],
            ).pack(side="left", padx=(0, 12))

        ttk.Button(suite_row, text="Select All", command=self.select_all_suites).pack(side="left", padx=(8, 4))
        ttk.Button(suite_row, text="Clear", command=self.clear_suites).pack(side="left")

        info_box = ttk.LabelFrame(outer, text="Test Types", padding=12)
        info_box.pack(fill="x", pady=(12, 12))
        for suite_name in SUITE_ORDER:
            ttk.Label(
                info_box,
                text=f"{suite_name}: {SUITE_INFO[suite_name]['description']}",
                wraplength=980,
                justify="left",
            ).pack(anchor="w", pady=2)

        action_row = ttk.Frame(outer)
        action_row.pack(fill="x", pady=(0, 12))

        self.run_button = ttk.Button(action_row, text="Run Benchmark", command=self.start_run)
        self.run_button.pack(side="left")

        self.open_report_button = ttk.Button(
            action_row,
            text="Open Report",
            command=self.open_report,
            state="disabled",
        )
        self.open_report_button.pack(side="left", padx=(8, 0))

        self.open_results_button = ttk.Button(
            action_row,
            text="Open Results Folder",
            command=self.open_results_folder,
            state="disabled",
        )
        self.open_results_button.pack(side="left", padx=(8, 0))

        ttk.Label(action_row, textvariable=self.status_var).pack(side="right")

        self.progress = ttk.Progressbar(outer, mode="determinate", maximum=1, value=0)
        self.progress.pack(fill="x", pady=(0, 12))
        ttk.Label(outer, textvariable=self.progress_var).pack(anchor="w", pady=(0, 12))

        main_pane = ttk.Panedwindow(outer, orient="horizontal")
        main_pane.pack(fill="both", expand=True)

        left = ttk.Frame(main_pane, padding=(0, 0, 8, 0))
        right = ttk.Frame(main_pane)
        main_pane.add(left, weight=1)
        main_pane.add(right, weight=2)

        scores_frame = ttk.LabelFrame(left, text="Scores", padding=8)
        scores_frame.pack(fill="both", expand=True)

        self.score_tree = ttk.Treeview(scores_frame, columns=("metric", "value"), show="headings", height=16)
        self.score_tree.heading("metric", text="Metric")
        self.score_tree.heading("value", text="Score")
        self.score_tree.column("metric", width=260, anchor="w")
        self.score_tree.column("value", width=90, anchor="center")
        self.score_tree.pack(fill="both", expand=True)

        summary_frame = ttk.LabelFrame(right, text="Summary", padding=8)
        summary_frame.pack(fill="both", expand=True)

        self.summary_text = tk.Text(summary_frame, wrap="word", height=22)
        self.summary_text.pack(fill="both", expand=True)
        self.summary_text.configure(state="disabled")

        log_frame = ttk.LabelFrame(right, text="Live Log", padding=8)
        log_frame.pack(fill="both", expand=True, pady=(12, 0))

        self.log_text = tk.Text(log_frame, wrap="word", height=12)
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")

    def populate_model_box(self):
        labels = [self.model_label(model) for model in self.models]
        self.model_box["values"] = labels
        current_id = self.model_var.get()
        for label in labels:
            if label.startswith(current_id + " "):
                self.model_box.set(label)
                break
        else:
            if labels:
                self.model_box.set(labels[0])
                self.model_var.set(self.models[0]["id"])

        self.model_box.bind("<<ComboboxSelected>>", self.on_model_selected)

    def default_model_id(self):
        for model in self.models:
            if model.get("enabled"):
                return model["id"]
        return self.models[0]["id"]

    def model_label(self, model):
        return f"{model['id']}  |  {model['provider']}  |  {model['model']}"

    def on_model_selected(self, _event):
        label = self.model_box.get()
        model_id = label.split("  |  ", 1)[0].strip()
        self.model_var.set(model_id)

    def selected_suites(self):
        return [name for name in SUITE_ORDER if self.suite_vars[name].get()]

    def select_all_suites(self):
        for variable in self.suite_vars.values():
            variable.set(True)

    def clear_suites(self):
        for variable in self.suite_vars.values():
            variable.set(False)

    def start_run(self):
        if self.run_thread and self.run_thread.is_alive():
            return

        suites = self.selected_suites()
        if not suites:
            messagebox.showerror("No Tests Selected", "Select at least one test type.")
            return

        model_id = self.model_box.get().split("  |  ", 1)[0].strip()
        if not model_id:
            messagebox.showerror("No Model Selected", "Select a model from the list.")
            return

        self.last_result = None
        self.open_report_button.configure(state="disabled")
        self.open_results_button.configure(state="disabled")
        self.set_summary("")
        self.clear_scores()
        self.log(f"Starting benchmark for {model_id} with: {', '.join(suites)}")
        self.status_var.set("Running benchmark...")
        self.run_started_at = time.monotonic()
        self.progress_total_units = 1
        self.progress_completed_units = 0
        self.progress_detail = "Preparing run"
        self.progress.configure(maximum=1, value=0)
        self.update_progress_display()
        self.run_button.configure(state="disabled")

        self.run_thread = threading.Thread(
            target=self.run_worker,
            args=(model_id, suites),
            daemon=True,
        )
        self.run_thread.start()

    def run_worker(self, model_id, suites):
        try:
            result = run_benchmark(
                config_path=self.config_path,
                model_id=model_id,
                selected_suites=suites,
                progress_callback=self.queue.put,
            )
            self.queue.put({"type": "finished", "result": result})
        except Exception as exc:
            self.queue.put({"type": "error", "message": str(exc)})

    def process_queue(self):
        while True:
            try:
                event = self.queue.get_nowait()
            except queue.Empty:
                break

            event_type = event["type"]
            if event_type == "status":
                self.status_var.set(event["message"])
                self.log(event["message"])
            elif event_type == "progress_init":
                self.progress_total_units = max(1, event["total_units"])
                self.progress_completed_units = event["completed_units"]
                self.progress_detail = "Benchmark started"
                self.progress.configure(maximum=self.progress_total_units, value=self.progress_completed_units)
                self.update_progress_display()
            elif event_type == "progress_update":
                self.progress_total_units = max(1, event["total_units"])
                self.progress_completed_units = min(event["completed_units"], self.progress_total_units)
                self.progress.configure(maximum=self.progress_total_units, value=self.progress_completed_units)
                self.progress_detail = self.format_progress_detail(event)
                self.update_progress_display()
            elif event_type == "case_complete":
                self.log(
                    f"{event['suite_name']} - {event['case_title']} scored {event['score']:.1f}"
                )
            elif event_type == "suite_complete":
                self.log(
                    f"{event['suite_name']} finished with overall benchmark score {event['overall_benchmark_score']:.1f}"
                )
                self.log(event["summary"])
            elif event_type == "run_complete":
                self.log("Run finished. Building report files.")
            elif event_type == "finished":
                self.finish_run(event["result"])
            elif event_type == "error":
                self.fail_run(event["message"])

        if self.run_started_at is not None and self.run_thread and self.run_thread.is_alive():
            self.update_progress_display()

        self.root.after(150, self.process_queue)

    def finish_run(self, result):
        self.last_result = result
        self.progress_completed_units = self.progress_total_units
        self.progress.configure(value=self.progress_total_units)
        self.run_button.configure(state="normal")
        self.open_report_button.configure(state="normal")
        self.open_results_button.configure(state="normal")
        self.status_var.set("Benchmark finished.")
        self.progress_detail = "Benchmark complete"
        self.update_progress_display(force_complete=True)
        self.run_started_at = None
        self.populate_scores(result["summary"])
        self.populate_summary(result)
        self.log(f"Report saved to {result['paths']['report_path']}")

    def fail_run(self, message):
        self.run_button.configure(state="normal")
        self.status_var.set("Benchmark failed.")
        self.progress_detail = "Benchmark failed"
        self.update_progress_display()
        self.run_started_at = None
        self.log("Benchmark failed: " + message)
        messagebox.showerror("Benchmark Failed", message)

    def clear_scores(self):
        for item in self.score_tree.get_children():
            self.score_tree.delete(item)

    def populate_scores(self, summary):
        self.clear_scores()
        self.score_tree.insert("", "end", values=("Overall Benchmark Score", f"{summary['overall_benchmark_score']:.1f}"))
        for name, value in summary["categories"].items():
            self.score_tree.insert("", "end", values=(name, f"{value:.1f}"))

    def populate_summary(self, result):
        summary = result["summary"]
        lines = [
            f"Model: {summary['model']['id']} ({summary['model']['provider']} / {summary['model']['model_name']})",
            f"Overall Benchmark Score: {summary['overall_benchmark_score']:.1f}",
            "",
            "Overall Categories:",
        ]
        for name, value in summary["categories"].items():
            lines.append(f"- {name}: {value:.1f}")

        for suite in summary["suite_summaries"]:
            lines.extend(
                [
                    "",
                    f"{suite['suite_name']}",
                    f"Overall Benchmark Score: {suite['overall_benchmark_score']:.1f}",
                    "Test Summary:",
                    suite["summary"],
                    "Evidence:",
                ]
            )
            for item in suite["evidence"]:
                lines.append(f"- {item}")

        lines.extend(
            [
                "",
                "Files:",
                f"- SQLite: {result['paths']['db_path']}",
                f"- CSV: {result['paths']['csv_path']}",
                f"- Report: {result['paths']['report_path']}",
                f"- Summary JSON: {result['paths']['summary_path']}",
            ]
        )
        self.set_summary("\n".join(lines))

    def set_summary(self, text):
        self.summary_text.configure(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", text)
        self.summary_text.configure(state="disabled")

    def log(self, text):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def update_progress_display(self, force_complete=False):
        total = max(1, self.progress_total_units)
        completed = min(self.progress_completed_units, total)
        percent = (completed / total) * 100.0
        elapsed = self.format_elapsed()

        if force_complete:
            percent = 100.0
            completed = total

        if self.run_started_at is None and not force_complete:
            self.progress_var.set("Progress: idle")
            return

        detail = self.progress_detail or "Running benchmark"
        self.progress_var.set(
            f"Progress: {completed}/{total} steps ({percent:.1f}%)  |  Elapsed: {elapsed}  |  {detail}"
        )

    def format_progress_detail(self, event):
        suite_name = event.get("suite_name")
        case_title = event.get("case_title")
        step_label = event.get("step_label")

        parts = []
        if suite_name:
            parts.append(suite_name)
        if case_title:
            parts.append(case_title)
        if step_label:
            parts.append(step_label)
        return " - ".join(parts)

    def format_elapsed(self):
        if self.run_started_at is None:
            return "00:00"
        elapsed_seconds = int(time.monotonic() - self.run_started_at)
        minutes, seconds = divmod(elapsed_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def open_report(self):
        if not self.last_result:
            return
        open_path(self.last_result["paths"]["report_path"])

    def open_results_folder(self):
        if not self.last_result:
            return
        open_path(str(Path(self.last_result["paths"]["report_path"]).parent))


def open_path(path):
    if hasattr(os, "startfile"):
        os.startfile(path)


def run_headless(config_path, model_id, suites):
    result = run_benchmark(config_path=config_path, model_id=model_id, selected_suites=suites)
    print(f"Overall Benchmark Score: {result['summary']['overall_benchmark_score']:.1f}")
    for name, value in result["summary"]["categories"].items():
        print(f"{name}: {value:.1f}")
    print(f"Report: {result['paths']['report_path']}")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="LLM Benchmark App")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--headless", action="store_true", help="Run without the desktop app")
    parser.add_argument("--model-id", help="Model id from config.yaml for headless mode")
    parser.add_argument(
        "--tests",
        nargs="+",
        choices=SUITE_ORDER,
        help="Test suites to run in headless mode",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.headless:
        if not args.model_id:
            parser.error("--model-id is required with --headless")
        if not args.tests:
            parser.error("--tests is required with --headless")
        return run_headless(args.config, args.model_id, args.tests)

    root = tk.Tk()
    app = BenchmarkApp(root, args.config)
    del app
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
