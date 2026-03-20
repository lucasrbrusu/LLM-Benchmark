import argparse
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from benchmark_catalog import (
    SUITE_INFO,
    SUITE_ORDER,
    count_category_cases,
    count_category_prompts,
    get_suite_categories,
)
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
        self.manage_profiles_window = None
        self.manage_profile_box = None
        self.profile_name_entry = None
        self.save_profile_button = None
        self.model_key_entries = {}
        self.profile_store_path = default_profile_store_path()
        self.profile_store = load_profile_store(self.profile_store_path)
        self.category_catalog = {
            suite_name: get_suite_categories(suite_name)
            for suite_name in SUITE_ORDER
        }

        self.models = list_models(config_path)
        self.model_var = tk.StringVar(value=self.default_model_id())
        self.profile_var = tk.StringVar(value=self.profile_store.get("active_profile", ""))
        self.manage_profile_var = tk.StringVar(value=self.profile_store.get("active_profile", ""))
        self.profile_name_var = tk.StringVar()
        self.profile_status_var = tk.StringVar(value="")
        self.provider_var = tk.StringVar(value="-")
        self.version_var = tk.StringVar(value="-")
        self.model_key_vars = {
            model["id"]: tk.StringVar()
            for model in self.models
        }
        self.status_var = tk.StringVar(value="Choose a profile, model, and one or more prompt categories.")
        self.progress_var = tk.StringVar(value="Progress: idle")
        self.suite_vars = {
            suite_name: tk.BooleanVar(value=(suite_name == "Lite"))
            for suite_name in SUITE_ORDER
        }
        self.category_vars = {
            suite_name: {
                entry["id"]: tk.BooleanVar(value=(suite_name == "Lite"))
                for entry in self.category_catalog[suite_name]
            }
            for suite_name in SUITE_ORDER
        }
        self.test_review_text = None
        self.score_tree = None
        self.summary_text = None
        self.log_text = None
        self.status_banner = None
        self.mousewheel_bound = False
        self.palette = {
            "page_bg": "#eef2f6",
            "card_bg": "#ffffff",
            "surface_bg": "#f7f9fc",
            "border": "#d7dee8",
            "text": "#10233f",
            "muted": "#5b6b83",
            "primary": "#07081a",
            "primary_hover": "#1a1f36",
            "primary_text": "#ffffff",
            "neutral_bg": "#f8fafc",
            "neutral_border": "#d7dee8",
            "neutral_text": "#334155",
            "info_bg": "#eef4ff",
            "info_border": "#bfdbfe",
            "info_text": "#1d4ed8",
            "success_bg": "#ebfbf1",
            "success_border": "#86efac",
            "success_text": "#166534",
            "error_bg": "#fff1f2",
            "error_border": "#fda4af",
            "error_text": "#be123c",
        }

        self.root.title("LLM Benchmark App")
        self.root.geometry("1220x860")
        self.root.minsize(1080, 720)
        self.root.configure(bg=self.palette["page_bg"])

        self.configure_styles()
        self.build_ui()
        self.populate_profile_box()
        self.populate_model_box()
        self.refresh_profile_controls()
        self.set_summary(
            "Run the benchmark to see scores, summaries, and output file paths here."
        )
        self.set_log_text("Live updates appear here while the benchmark is running.")
        self.set_status_message(
            "Choose a profile, model, and one or more prompt categories.",
            tone="neutral",
        )
        self.root.after(150, self.process_queue)

    def configure_styles(self):
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        page_bg = self.palette["page_bg"]
        card_bg = self.palette["card_bg"]
        surface_bg = self.palette["surface_bg"]
        text = self.palette["text"]
        muted = self.palette["muted"]

        style.configure("App.TFrame", background=page_bg)
        style.configure("Card.TFrame", background=card_bg)
        style.configure("Inset.TFrame", background=surface_bg)

        style.configure(
            "Card.TLabelframe",
            background=card_bg,
            borderwidth=1,
            relief="solid",
        )
        style.configure(
            "Card.TLabelframe.Label",
            background=card_bg,
            foreground=text,
            font=("Segoe UI", 15, "bold"),
        )
        style.configure(
            "Inset.TLabelframe",
            background=surface_bg,
            borderwidth=1,
            relief="solid",
        )
        style.configure(
            "Inset.TLabelframe.Label",
            background=surface_bg,
            foreground=text,
            font=("Segoe UI", 11, "bold"),
        )

        style.configure(
            "HeroSubtitle.TLabel",
            background=card_bg,
            foreground=muted,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Card.TLabel",
            background=card_bg,
            foreground=text,
            font=("Segoe UI", 10),
        )
        style.configure(
            "CardHint.TLabel",
            background=card_bg,
            foreground=muted,
            font=("Segoe UI", 10),
        )
        style.configure(
            "FieldLabel.TLabel",
            background=card_bg,
            foreground=muted,
            font=("Segoe UI", 9, "bold"),
        )
        style.configure(
            "InsetHint.TLabel",
            background=surface_bg,
            foreground=muted,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Inset.TCheckbutton",
            background=surface_bg,
            foreground=text,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Card.TCheckbutton",
            background=card_bg,
            foreground=text,
            font=("Segoe UI", 10),
        )

        style.configure(
            "Primary.TButton",
            padding=(18, 12),
            background=self.palette["primary"],
            foreground=self.palette["primary_text"],
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            borderwidth=0,
        )
        style.map(
            "Primary.TButton",
            background=[
                ("active", self.palette["primary_hover"]),
                ("pressed", self.palette["primary_hover"]),
                ("disabled", "#cbd5e1"),
            ],
            foreground=[("disabled", "#f8fafc")],
        )
        style.configure(
            "Secondary.TButton",
            padding=(14, 10),
            background=card_bg,
            foreground=text,
            font=("Segoe UI", 10),
            relief="solid",
            borderwidth=1,
        )
        style.map(
            "Secondary.TButton",
            background=[("active", surface_bg), ("pressed", surface_bg)],
        )
        style.configure(
            "Small.TButton",
            padding=(10, 6),
            background=card_bg,
            foreground=text,
            font=("Segoe UI", 9, "bold"),
            relief="solid",
            borderwidth=1,
        )
        style.map(
            "Small.TButton",
            background=[("active", surface_bg), ("pressed", surface_bg)],
        )

        style.configure("Card.TCombobox", padding=8)
        style.map(
            "Card.TCombobox",
            fieldbackground=[("readonly", card_bg)],
            selectbackground=[("readonly", card_bg)],
            selectforeground=[("readonly", text)],
            foreground=[("readonly", text)],
        )
        style.configure("Card.TEntry", padding=8)

        style.configure(
            "Benchmark.Horizontal.TProgressbar",
            troughcolor="#dbe2ea",
            background=self.palette["primary"],
            lightcolor=self.palette["primary"],
            darkcolor=self.palette["primary"],
            bordercolor="#dbe2ea",
            thickness=14,
        )

        style.configure(
            "Result.Treeview",
            background=card_bg,
            fieldbackground=card_bg,
            foreground=text,
            rowheight=30,
            borderwidth=0,
            font=("Segoe UI", 10),
        )
        style.map(
            "Result.Treeview",
            background=[("selected", "#dbeafe")],
            foreground=[("selected", text)],
        )
        style.configure(
            "Result.Treeview.Heading",
            background=surface_bg,
            foreground=text,
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            padding=(10, 8),
        )

    def create_card(self, parent, title, description=None, expand=False, pady=(0, 16)):
        card = ttk.LabelFrame(parent, text=title, style="Card.TLabelframe", padding=18)
        card.pack(fill="both", expand=expand, pady=pady)
        if description:
            ttk.Label(
                card,
                text=description,
                style="CardHint.TLabel",
                wraplength=1040,
                justify="left",
            ).pack(anchor="w", pady=(0, 12))
        return card

    def create_inset_frame(self, parent, padding=(12, 10)):
        padx, pady = padding
        return tk.Frame(
            parent,
            bg=self.palette["surface_bg"],
            bd=0,
            highlightthickness=1,
            highlightbackground=self.palette["border"],
            padx=padx,
            pady=pady,
        )

    def build_value_panel(self, parent, row, column, title, textvariable, padx):
        ttk.Label(parent, text=title, style="FieldLabel.TLabel").grid(
            row=row,
            column=column,
            sticky="w",
            padx=padx,
            pady=(0, 6),
        )
        panel = self.create_inset_frame(parent)
        panel.grid(
            row=row + 1,
            column=column,
            sticky="ew",
            padx=padx,
            pady=(0, 12),
        )
        tk.Label(
            panel,
            textvariable=textvariable,
            bg=self.palette["surface_bg"],
            fg=self.palette["text"],
            font=("Segoe UI", 11),
        ).pack(anchor="w")
        return panel

    def build_ui(self):
        outer = self.build_scrollable_page(self.root, padding=20)

        hero = self.create_card(outer, "LLM Benchmark App", pady=(0, 18))
        ttk.Label(
            hero,
            text=(
                "Pick one model, choose suites and prompt categories, review the exact prompts, "
                "then run the benchmark."
            ),
            style="HeroSubtitle.TLabel",
            wraplength=1040,
            justify="left",
        ).pack(anchor="w")

        controls = self.create_card(outer, "Run Setup")
        top_grid = ttk.Frame(controls, style="Card.TFrame")
        top_grid.pack(fill="x", pady=(0, 12))
        for index in range(3):
            top_grid.columnconfigure(index, weight=1)

        ttk.Label(top_grid, text="Model", style="FieldLabel.TLabel").grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 12),
            pady=(0, 6),
        )
        self.model_box = ttk.Combobox(
            top_grid,
            state="readonly",
            textvariable=self.model_var,
            style="Card.TCombobox",
        )
        self.model_box.grid(
            row=1,
            column=0,
            sticky="ew",
            padx=(0, 12),
            pady=(0, 12),
        )
        self.model_box.bind("<<ComboboxSelected>>", self.on_model_selected)

        self.build_value_panel(top_grid, 0, 1, "Provider", self.provider_var, padx=(0, 12))
        self.build_value_panel(top_grid, 0, 2, "Version", self.version_var, padx=(0, 0))

        ttk.Label(controls, text="Profile", style="FieldLabel.TLabel").pack(anchor="w", pady=(0, 6))
        profile_row = ttk.Frame(controls, style="Card.TFrame")
        profile_row.pack(fill="x", pady=(0, 10))
        self.profile_box = ttk.Combobox(
            profile_row,
            state="readonly",
            textvariable=self.profile_var,
            style="Card.TCombobox",
        )
        self.profile_box.pack(side="left", fill="x", expand=True)
        self.profile_box.bind("<<ComboboxSelected>>", self.on_profile_selected)
        ttk.Button(
            profile_row,
            text="Manage Profiles",
            style="Secondary.TButton",
            command=self.open_manage_profiles,
        ).pack(side="left", padx=(10, 0))

        ttk.Label(
            controls,
            textvariable=self.profile_status_var,
            style="CardHint.TLabel",
            wraplength=1040,
            justify="left",
        ).pack(anchor="w", pady=(0, 12))

        ttk.Label(controls, text="Tests", style="FieldLabel.TLabel").pack(anchor="w", pady=(0, 6))
        suite_row = ttk.Frame(controls, style="Card.TFrame")
        suite_row.pack(fill="x")
        for suite_name in SUITE_ORDER:
            ttk.Checkbutton(
                suite_row,
                text=suite_name,
                style="Card.TCheckbutton",
                variable=self.suite_vars[suite_name],
                command=lambda name=suite_name: self.on_suite_toggled(name),
            ).pack(side="left", padx=(0, 12))

        ttk.Button(
            suite_row,
            text="Select All",
            style="Small.TButton",
            command=self.select_all_suites,
        ).pack(side="left", padx=(8, 4))
        ttk.Button(
            suite_row,
            text="Clear",
            style="Small.TButton",
            command=self.clear_suites,
        ).pack(side="left")

        info_box = self.create_card(outer, "Test Types")
        for suite_name in SUITE_ORDER:
            category_count = len(self.category_catalog[suite_name])
            prompt_count = sum(
                count_category_prompts(entry)
                for entry in self.category_catalog[suite_name]
            )
            panel = self.create_inset_frame(info_box, padding=(14, 10))
            panel.pack(fill="x", pady=(0, 8))
            tk.Label(
                panel,
                text=f"{suite_name}:",
                bg=self.palette["surface_bg"],
                fg=self.palette["text"],
                font=("Segoe UI", 10, "bold"),
            ).pack(anchor="w")
            tk.Label(
                panel,
                text=(
                    f"{SUITE_INFO[suite_name]['description']} "
                    f"Categories: {category_count}. Prompt turns: {prompt_count}."
                ),
                bg=self.palette["surface_bg"],
                fg=self.palette["muted"],
                wraplength=1000,
                justify="left",
                font=("Segoe UI", 10),
            ).pack(anchor="w", pady=(4, 0))

        self.build_test_review(outer)

        action_row = ttk.Frame(outer, style="App.TFrame")
        action_row.pack(fill="x", pady=(0, 12))
        action_row.columnconfigure(0, weight=1)

        self.run_button = ttk.Button(
            action_row,
            text="Run Benchmark",
            style="Primary.TButton",
            command=self.start_run,
        )
        self.run_button.grid(row=0, column=0, sticky="ew")

        self.open_report_button = ttk.Button(
            action_row,
            text="Open Report",
            style="Secondary.TButton",
            command=self.open_report,
            state="disabled",
        )
        self.open_report_button.grid(row=0, column=1, padx=(14, 12))

        self.open_results_button = ttk.Button(
            action_row,
            text="Open Results Folder",
            style="Secondary.TButton",
            command=self.open_results_folder,
            state="disabled",
        )
        self.open_results_button.grid(row=0, column=2)

        status_box = self.create_card(outer, "Run Status")
        self.status_banner = tk.Label(
            status_box,
            textvariable=self.status_var,
            anchor="w",
            justify="left",
            padx=14,
            pady=12,
            font=("Segoe UI", 11),
            bg=self.palette["neutral_bg"],
            fg=self.palette["neutral_text"],
            highlightthickness=1,
            highlightbackground=self.palette["neutral_border"],
        )
        self.status_banner.pack(fill="x", pady=(0, 12))

        self.progress = ttk.Progressbar(
            status_box,
            mode="determinate",
            maximum=1,
            value=0,
            style="Benchmark.Horizontal.TProgressbar",
        )
        self.progress.pack(fill="x", pady=(0, 10))
        ttk.Label(
            status_box,
            textvariable=self.progress_var,
            style="CardHint.TLabel",
        ).pack(anchor="w")

        results_row = ttk.Frame(outer, style="App.TFrame")
        results_row.pack(fill="both", expand=True)
        results_row.columnconfigure(0, weight=1)
        results_row.columnconfigure(1, weight=1)

        left = ttk.Frame(results_row, style="App.TFrame")
        right = ttk.Frame(results_row, style="App.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(0, weight=2)
        right.rowconfigure(1, weight=1)

        scores_frame = ttk.LabelFrame(left, text="Scores", style="Card.TLabelframe", padding=18)
        scores_frame.pack(fill="both", expand=True)

        self.score_tree = ttk.Treeview(
            scores_frame,
            style="Result.Treeview",
            columns=("metric", "value"),
            show="headings",
            height=12,
        )
        self.score_tree.heading("metric", text="Metric")
        self.score_tree.heading("value", text="Score")
        self.score_tree.column("metric", width=290, anchor="w")
        self.score_tree.column("value", width=100, anchor="center")
        self.score_tree.pack(fill="both", expand=True)

        summary_frame = ttk.LabelFrame(right, text="Summary", style="Card.TLabelframe", padding=18)
        summary_frame.grid(row=0, column=0, sticky="nsew")
        summary_panel = self.create_inset_frame(summary_frame, padding=(0, 0))
        summary_panel.pack(fill="both", expand=True)
        summary_scrollbar = ttk.Scrollbar(summary_panel, orient="vertical")
        self.summary_text = tk.Text(
            summary_panel,
            wrap="word",
            height=18,
            yscrollcommand=summary_scrollbar.set,
            font=("Consolas", 10),
            bg=self.palette["surface_bg"],
            fg=self.palette["text"],
            bd=0,
            relief="flat",
            padx=12,
            pady=12,
        )
        summary_scrollbar.configure(command=self.summary_text.yview)
        summary_scrollbar.pack(side="right", fill="y")
        self.summary_text.pack(side="left", fill="both", expand=True)
        self.summary_text.configure(state="disabled")

        log_frame = ttk.LabelFrame(right, text="Live Log", style="Card.TLabelframe", padding=18)
        log_frame.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        log_panel = self.create_inset_frame(log_frame, padding=(0, 0))
        log_panel.pack(fill="both", expand=True)
        log_scrollbar = ttk.Scrollbar(log_panel, orient="vertical")
        self.log_text = tk.Text(
            log_panel,
            wrap="word",
            height=9,
            yscrollcommand=log_scrollbar.set,
            font=("Consolas", 10),
            bg=self.palette["surface_bg"],
            fg=self.palette["text"],
            bd=0,
            relief="flat",
            padx=12,
            pady=12,
        )
        log_scrollbar.configure(command=self.log_text.yview)
        log_scrollbar.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)
        self.log_text.configure(state="disabled")

    def build_test_review(self, parent):
        review_frame = self.create_card(
            parent,
            "Test Review",
            description=(
                "Choose the prompt categories to run, then use the review pane to inspect "
                "the exact prompt sets and prompts included in the benchmark."
            ),
            expand=True,
        )

        review_body = ttk.Frame(review_frame, style="Card.TFrame")
        review_body.pack(fill="both", expand=True)
        review_body.columnconfigure(0, weight=1)
        review_body.columnconfigure(1, weight=2)
        review_body.rowconfigure(0, weight=1)

        left = ttk.Frame(review_body, style="Card.TFrame")
        right = ttk.Frame(review_body, style="Card.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        right.grid(row=0, column=1, sticky="nsew")

        for suite_name in SUITE_ORDER:
            suite_frame = ttk.LabelFrame(left, text=suite_name, style="Inset.TLabelframe", padding=12)
            suite_frame.pack(fill="x", pady=(0, 10))

            header_row = ttk.Frame(suite_frame, style="Inset.TFrame")
            header_row.pack(fill="x", pady=(0, 6))
            ttk.Button(
                header_row,
                text="All",
                style="Small.TButton",
                command=lambda name=suite_name: self.select_suite_categories(name),
            ).pack(side="left")
            ttk.Button(
                header_row,
                text="None",
                style="Small.TButton",
                command=lambda name=suite_name: self.clear_suite_categories(name),
            ).pack(side="left", padx=(4, 0))
            ttk.Label(
                header_row,
                text=(
                    f"{len(self.category_catalog[suite_name])} categories / "
                    f"{sum(count_category_prompts(entry) for entry in self.category_catalog[suite_name])} prompts"
                ),
                style="InsetHint.TLabel",
            ).pack(side="right")

            for entry in self.category_catalog[suite_name]:
                ttk.Checkbutton(
                    suite_frame,
                    style="Inset.TCheckbutton",
                    text=(
                        f"{entry['title']} "
                        f"({count_category_cases(entry)} sets / {count_category_prompts(entry)} prompts)"
                    ),
                    variable=self.category_vars[suite_name][entry["id"]],
                    command=lambda name=suite_name: self.on_category_selection_changed(name),
                ).pack(anchor="w", pady=2)

        ttk.Label(
            right,
            text=(
                "Selected categories are shown in this review. Every prompt listed here is exactly "
                "what the runner will use when you start the benchmark."
            ),
            style="CardHint.TLabel",
            wraplength=640,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        preview_panel = self.create_inset_frame(right, padding=(0, 0))
        preview_panel.pack(fill="both", expand=True)
        scrollbar = ttk.Scrollbar(preview_panel, orient="vertical")
        self.test_review_text = tk.Text(
            preview_panel,
            wrap="word",
            height=24,
            yscrollcommand=scrollbar.set,
            font=("Consolas", 10),
            bg=self.palette["surface_bg"],
            fg=self.palette["text"],
            bd=0,
            relief="flat",
            padx=12,
            pady=12,
        )
        scrollbar.configure(command=self.test_review_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.test_review_text.pack(side="left", fill="both", expand=True)
        self.refresh_test_review()

    def build_profile_key_inputs(self, parent):
        self.model_key_entries = {}
        table = ttk.Frame(parent, style="Card.TFrame")
        table.pack(fill="x")
        table.columnconfigure(0, weight=2)
        table.columnconfigure(1, weight=1)
        table.columnconfigure(2, weight=2)

        ttk.Label(table, text="Model", style="FieldLabel.TLabel").grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 12),
            pady=(0, 8),
        )
        ttk.Label(table, text="Key Name", style="FieldLabel.TLabel").grid(
            row=0,
            column=1,
            sticky="w",
            padx=(0, 12),
            pady=(0, 8),
        )
        ttk.Label(table, text="API Key", style="FieldLabel.TLabel").grid(
            row=0,
            column=2,
            sticky="w",
            pady=(0, 8),
        )

        row_index = 1
        for model in self.models:
            ttk.Separator(table, orient="horizontal").grid(
                row=row_index,
                column=0,
                columnspan=3,
                sticky="ew",
                pady=(0, 8),
            )
            row_index += 1

            ttk.Label(
                table,
                text=f"{model['id']} ({model['provider']} / {model['model']})",
                style="Card.TLabel",
                wraplength=280,
                justify="left",
            ).grid(
                row=row_index,
                column=0,
                sticky="nw",
                padx=(0, 12),
                pady=(0, 8),
            )

            env_name = model.get("api_key_env")
            if not env_name:
                ttk.Label(
                    table,
                    text="No API key required",
                    style="CardHint.TLabel",
                ).grid(
                    row=row_index,
                    column=1,
                    sticky="w",
                    padx=(0, 12),
                    pady=(0, 8),
                )
                ttk.Label(
                    table,
                    text="Built-in or local model",
                    style="CardHint.TLabel",
                ).grid(
                    row=row_index,
                    column=2,
                    sticky="w",
                    pady=(0, 8),
                )
            else:
                ttk.Label(
                    table,
                    text=env_name,
                    style="Card.TLabel",
                ).grid(
                    row=row_index,
                    column=1,
                    sticky="w",
                    padx=(0, 12),
                    pady=(0, 8),
                )
                entry = ttk.Entry(
                    table,
                    textvariable=self.model_key_vars[model["id"]],
                    show="*",
                    style="Card.TEntry",
                )
                entry.grid(
                    row=row_index,
                    column=2,
                    sticky="ew",
                    pady=(0, 8),
                )
                entry.bind("<Return>", self.on_api_key_submit)
                self.model_key_entries[model["id"]] = entry

            row_index += 1

    def build_scrollable_page(self, parent, padding):
        container = ttk.Frame(parent, style="App.TFrame")
        container.pack(fill="both", expand=True)

        canvas = tk.Canvas(
            container,
            highlightthickness=0,
            bd=0,
            bg=self.palette["page_bg"],
        )
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        content = ttk.Frame(canvas, style="App.TFrame", padding=padding)
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")

        content.bind(
            "<Configure>",
            lambda _event, current_canvas=canvas: current_canvas.configure(
                scrollregion=current_canvas.bbox("all")
            ),
        )
        canvas.bind(
            "<Configure>",
            lambda event, current_canvas=canvas, current_window=window_id: current_canvas.itemconfigure(
                current_window, width=event.width
            ),
        )
        self.register_scrollable_canvas(canvas, content)

        return content

    def register_scrollable_canvas(self, canvas, content):
        canvas._scroll_target_canvas = canvas
        content._scroll_target_canvas = canvas

        if self.mousewheel_bound:
            return

        self.root.bind_all("<MouseWheel>", self.on_mousewheel, add="+")
        self.root.bind_all("<Button-4>", self.on_mousewheel, add="+")
        self.root.bind_all("<Button-5>", self.on_mousewheel, add="+")
        self.mousewheel_bound = True

    def on_mousewheel(self, event):
        widget = event.widget
        if isinstance(widget, (tk.Text, tk.Listbox, ttk.Treeview)):
            return

        canvas = self.find_scroll_target_canvas(widget)
        if not canvas:
            return

        if getattr(event, "num", None) == 4:
            steps = -1
        elif getattr(event, "num", None) == 5:
            steps = 1
        else:
            delta = int(getattr(event, "delta", 0))
            if delta == 0:
                return
            steps = int(-delta / 120)
            if steps == 0:
                steps = -1 if delta > 0 else 1

        canvas.yview_scroll(steps, "units")

    def find_scroll_target_canvas(self, widget):
        current = widget
        while current is not None:
            canvas = getattr(current, "_scroll_target_canvas", None)
            if canvas is not None:
                return canvas
            current = getattr(current, "master", None)
        return None

    def update_model_details(self):
        model = self.current_model()
        if not model:
            self.provider_var.set("-")
            self.version_var.set("-")
            return
        self.provider_var.set(model["provider"])
        self.version_var.set(model["model"])

    def set_status_message(self, message, tone="neutral"):
        self.status_var.set(message)
        if not self.status_banner:
            return

        tone_map = {
            "neutral": (
                self.palette["neutral_bg"],
                self.palette["neutral_border"],
                self.palette["neutral_text"],
            ),
            "info": (
                self.palette["info_bg"],
                self.palette["info_border"],
                self.palette["info_text"],
            ),
            "success": (
                self.palette["success_bg"],
                self.palette["success_border"],
                self.palette["success_text"],
            ),
            "error": (
                self.palette["error_bg"],
                self.palette["error_border"],
                self.palette["error_text"],
            ),
        }
        background, border, foreground = tone_map.get(tone, tone_map["neutral"])
        self.status_banner.configure(
            bg=background,
            fg=foreground,
            highlightbackground=border,
        )

    def set_log_text(self, text):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        if text:
            self.log_text.insert("1.0", text)
        self.log_text.configure(state="disabled")

    def open_manage_profiles(self):
        if self.manage_profiles_window and self.manage_profiles_window.winfo_exists():
            self.manage_profiles_window.deiconify()
            self.manage_profiles_window.lift()
            self.manage_profiles_window.focus_force()
            self.populate_manage_profile_box()
            self.refresh_profile_controls()
            return

        window = tk.Toplevel(self.root)
        window.title("Manage Profiles")
        window.geometry("920x640")
        window.minsize(860, 520)
        window.configure(bg=self.palette["page_bg"])
        window.transient(self.root)
        window.protocol("WM_DELETE_WINDOW", self.close_manage_profiles)
        self.manage_profiles_window = window

        outer = self.build_scrollable_page(window, padding=18)
        dialog = self.create_card(
            outer,
            "Manage Profiles",
            description=(
                "Create, edit, and delete saved profiles. API keys saved here are stored locally on this "
                "device and reused the next time the app is opened. The main Run Setup page chooses which "
                "saved profile is active."
            ),
            expand=True,
            pady=(0, 0),
        )

        profile_row = ttk.Frame(dialog, style="Card.TFrame")
        profile_row.pack(fill="x", pady=(0, 10))
        ttk.Label(profile_row, text="Profile:", style="FieldLabel.TLabel").pack(side="left", padx=(0, 10))
        self.manage_profile_box = ttk.Combobox(
            profile_row,
            state="readonly",
            textvariable=self.manage_profile_var,
            style="Card.TCombobox",
        )
        self.manage_profile_box.pack(side="left", fill="x", expand=True)
        self.manage_profile_box.bind("<<ComboboxSelected>>", self.on_manage_profile_selected)
        ttk.Button(
            profile_row,
            text="New Profile",
            style="Secondary.TButton",
            command=self.new_profile,
        ).pack(side="left", padx=(8, 4))
        ttk.Button(
            profile_row,
            text="Delete",
            style="Secondary.TButton",
            command=self.delete_profile,
        ).pack(side="left")

        profile_name_row = ttk.Frame(dialog, style="Card.TFrame")
        profile_name_row.pack(fill="x", pady=(0, 10))
        ttk.Label(profile_name_row, text="Name:", style="FieldLabel.TLabel").pack(side="left", padx=(0, 24))
        self.profile_name_entry = ttk.Entry(
            profile_name_row,
            textvariable=self.profile_name_var,
            style="Card.TEntry",
        )
        self.profile_name_entry.pack(side="left", fill="x", expand=True)

        keys_frame = ttk.LabelFrame(dialog, text="Profile API Keys", style="Inset.TLabelframe", padding=12)
        keys_frame.pack(fill="x", pady=(0, 10))
        self.build_profile_key_inputs(keys_frame)

        action_row = ttk.Frame(dialog, style="Card.TFrame")
        action_row.pack(fill="x", pady=(0, 6))
        self.save_profile_button = ttk.Button(
            action_row,
            text="Save Profile",
            style="Primary.TButton",
            command=self.save_profile,
        )
        self.save_profile_button.pack(side="left")
        ttk.Button(
            action_row,
            text="Close",
            style="Secondary.TButton",
            command=self.close_manage_profiles,
        ).pack(side="left", padx=(10, 0))

        status_row = ttk.Frame(dialog, style="Card.TFrame")
        status_row.pack(fill="x", pady=(0, 6))
        ttk.Label(
            status_row,
            textvariable=self.profile_status_var,
            style="CardHint.TLabel",
            wraplength=920,
            justify="left",
        ).pack(anchor="w")

        self.populate_manage_profile_box()
        self.refresh_profile_controls()

    def close_manage_profiles(self):
        if self.manage_profiles_window and self.manage_profiles_window.winfo_exists():
            self.manage_profiles_window.destroy()
        self.manage_profiles_window = None
        self.model_key_entries = {}
        self.manage_profile_box = None
        self.profile_name_entry = None
        self.save_profile_button = None

    def populate_model_box(self):
        labels = [self.model_label(model) for model in self.available_models_for_active_profile()]
        self.model_box["values"] = labels
        current_id = self.model_var.get()
        if current_id in labels:
            self.model_box.set(current_id)
        elif labels:
            self.model_var.set(labels[0])
            self.model_box.set(labels[0])
        else:
            self.model_var.set("")
            self.model_box.set("")

        self.update_model_details()

    def populate_profile_box(self):
        profile_names = sorted(self.profile_store.get("profiles", {}).keys(), key=str.casefold)
        self.profile_box["values"] = profile_names

        selected = self.profile_var.get().strip()
        if selected not in profile_names:
            if profile_names:
                selected = self.profile_store.get("active_profile", "")
                if selected not in profile_names:
                    selected = profile_names[0]
            else:
                selected = ""

        self.profile_var.set(selected)
        self.profile_box.set(selected)

        if selected:
            self.profile_store["active_profile"] = selected
            save_profile_store(self.profile_store_path, self.profile_store)

        self.populate_model_box()

    def populate_manage_profile_box(self):
        if not self.manage_profile_box:
            return

        profile_names = sorted(self.profile_store.get("profiles", {}).keys(), key=str.casefold)
        self.manage_profile_box["values"] = profile_names

        selected = self.manage_profile_var.get().strip()
        if selected not in profile_names:
            if profile_names:
                selected = self.profile_var.get().strip()
                if selected not in profile_names:
                    selected = profile_names[0]
            else:
                selected = ""

        self.manage_profile_var.set(selected)
        self.manage_profile_box.set(selected)

        if selected:
            self.load_profile_into_editor(selected)
        else:
            self.profile_name_var.set("")
            for variable in self.model_key_vars.values():
                variable.set("")

    def default_model_id(self):
        for model in self.models:
            if model.get("enabled"):
                return model["id"]
        return self.models[0]["id"]

    def current_model(self):
        model_id = self.model_var.get()
        for model in self.models:
            if model["id"] == model_id:
                return model
        return None

    def model_label(self, model):
        return model["id"]

    def get_profile_model_key(self, profile, model):
        model_keys = profile.get("model_keys", {})
        if isinstance(model_keys, dict):
            key = str(model_keys.get(model["id"], "")).strip()
            if key:
                return key

        legacy_keys = profile.get("api_keys", {})
        env_name = model.get("api_key_env")
        if isinstance(legacy_keys, dict) and env_name:
            return str(legacy_keys.get(env_name, "")).strip()

        return ""

    def available_models_for_active_profile(self):
        profile_name = self.profile_var.get().strip()
        profile = self.profile_store.get("profiles", {}).get(profile_name)
        if not profile_name or not profile:
            return []

        available = []
        for model in self.models:
            if not model.get("api_key_env"):
                available.append(model)
                continue
            if self.get_profile_model_key(profile, model):
                available.append(model)
        return available

    def on_model_selected(self, _event):
        self.model_var.set(self.model_box.get().strip())
        self.update_model_details()
        self.refresh_profile_controls()

    def on_profile_selected(self, _event):
        profile_name = self.profile_box.get().strip()
        self.profile_var.set(profile_name)
        self.profile_store["active_profile"] = profile_name
        save_profile_store(self.profile_store_path, self.profile_store)
        self.populate_model_box()
        self.refresh_profile_controls()

    def on_manage_profile_selected(self, _event):
        profile_name = self.manage_profile_box.get().strip()
        self.manage_profile_var.set(profile_name)
        self.load_profile_into_editor(profile_name)
        self.refresh_profile_controls()

    def on_api_key_submit(self, _event):
        self.save_profile()

    def load_profile_into_editor(self, profile_name):
        profile = self.profile_store.get("profiles", {}).get(profile_name, {})
        self.profile_name_var.set(profile_name)
        for model in self.models:
            self.model_key_vars[model["id"]].set(self.get_profile_model_key(profile, model))

    def new_profile(self):
        self.manage_profile_var.set("")
        if self.manage_profile_box:
            self.manage_profile_box.set("")
        self.profile_name_var.set("")
        for variable in self.model_key_vars.values():
            variable.set("")
        self.refresh_profile_controls()
        if self.profile_name_entry:
            self.profile_name_entry.focus_set()

    def delete_profile(self):
        profile_name = self.manage_profile_var.get().strip()
        if not profile_name:
            messagebox.showerror("No Profile Selected", "Select a profile to delete.")
            return

        if not messagebox.askyesno("Delete Profile", f"Delete profile '{profile_name}' from this device?"):
            return

        profiles = self.profile_store.get("profiles", {})
        profiles.pop(profile_name, None)
        if self.profile_store.get("active_profile") == profile_name:
            self.profile_store["active_profile"] = ""
            self.profile_var.set("")
        save_profile_store(self.profile_store_path, self.profile_store)

        self.populate_profile_box()
        self.populate_manage_profile_box()
        self.refresh_profile_controls()
        self.log(f"Deleted profile {profile_name}.")

    def refresh_profile_controls(self):
        active_profile_name = self.profile_var.get().strip()
        active_profile = self.profile_store.get("profiles", {}).get(active_profile_name, {})
        available_models = self.available_models_for_active_profile()
        current_model = self.current_model()

        if not active_profile_name:
            self.profile_status_var.set(
                "Create or select a profile, then add API keys for the models you want that profile to use."
            )
            return

        keyed_models = []
        missing_models = []
        for model in self.models:
            if not model.get("api_key_env"):
                continue
            if self.get_profile_model_key(active_profile, model):
                keyed_models.append(model["id"])
            else:
                missing_models.append(model["id"])

        if not available_models:
            self.profile_status_var.set(
                f"Profile '{active_profile_name}' is active, but no runnable models are configured for it yet."
            )
            return

        message = (
            f"Profile '{active_profile_name}' can use: {', '.join(model['id'] for model in available_models)}."
        )
        if current_model and current_model not in available_models:
            message += " The current model is not available under this profile."
        if missing_models:
            message += f" Missing keys for: {', '.join(missing_models)}."
        self.profile_status_var.set(message)

    def save_profile(self):
        profile_name = self.profile_name_var.get().strip()
        if not profile_name:
            messagebox.showerror("Missing Profile Name", "Enter a profile name before saving.")
            return

        profiles = self.profile_store.setdefault("profiles", {})
        selected_name = self.manage_profile_var.get().strip()
        active_profile_name = self.profile_var.get().strip()

        if selected_name and selected_name != profile_name and profile_name in profiles:
            messagebox.showerror("Duplicate Profile Name", f"A profile named '{profile_name}' already exists.")
            return

        if selected_name and selected_name in profiles and selected_name != profile_name:
            profile_record = profiles.pop(selected_name)
        else:
            profile_record = profiles.get(profile_name, {})

        model_keys = dict(profile_record.get("model_keys", {}))
        for model in self.models:
            if not model.get("api_key_env"):
                continue
            value = self.model_key_vars[model["id"]].get().strip()
            if value:
                model_keys[model["id"]] = value
            else:
                model_keys.pop(model["id"], None)

        profiles[profile_name] = {"model_keys": model_keys}
        if active_profile_name == selected_name or not active_profile_name:
            self.profile_store["active_profile"] = profile_name
            self.profile_var.set(profile_name)
        save_profile_store(self.profile_store_path, self.profile_store)

        self.manage_profile_var.set(profile_name)
        self.populate_profile_box()
        self.populate_manage_profile_box()
        self.refresh_profile_controls()
        self.log(f"Saved profile {profile_name}.")
        messagebox.showinfo(
            "Profile Saved",
            (
                f"Profile '{profile_name}' was saved on this device.\n\n"
                f"Stored at:\n{self.profile_store_path}\n\n"
                "The saved API keys will be loaded again the next time you open the app."
            ),
        )

    def apply_profile_environment(self, profile_name, model_id):
        profile = self.profile_store.get("profiles", {}).get(profile_name, {})
        selected_model = next((model for model in self.models if model["id"] == model_id), None)
        if not selected_model:
            return

        env_name = selected_model.get("api_key_env")
        if not env_name:
            return

        value = self.get_profile_model_key(profile, selected_model)
        if value:
            os.environ[env_name] = value
        else:
            os.environ.pop(env_name, None)

    def selected_categories(self):
        selected = {}
        for suite_name in SUITE_ORDER:
            category_ids = [
                entry["id"]
                for entry in self.category_catalog[suite_name]
                if self.category_vars[suite_name][entry["id"]].get()
            ]
            if category_ids:
                selected[suite_name] = category_ids
        return selected

    def selected_suites(self):
        selected = self.selected_categories()
        return [name for name in SUITE_ORDER if name in selected]

    def on_suite_toggled(self, suite_name):
        enabled = self.suite_vars[suite_name].get()
        for entry in self.category_catalog[suite_name]:
            self.category_vars[suite_name][entry["id"]].set(enabled)
        self.refresh_test_review()

    def on_category_selection_changed(self, suite_name):
        self.sync_suite_var(suite_name)
        self.refresh_test_review()

    def sync_suite_var(self, suite_name):
        self.suite_vars[suite_name].set(
            any(
                self.category_vars[suite_name][entry["id"]].get()
                for entry in self.category_catalog[suite_name]
            )
        )

    def select_suite_categories(self, suite_name):
        self.suite_vars[suite_name].set(True)
        for entry in self.category_catalog[suite_name]:
            self.category_vars[suite_name][entry["id"]].set(True)
        self.refresh_test_review()

    def clear_suite_categories(self, suite_name):
        self.suite_vars[suite_name].set(False)
        for entry in self.category_catalog[suite_name]:
            self.category_vars[suite_name][entry["id"]].set(False)
        self.refresh_test_review()

    def select_all_suites(self):
        for suite_name in SUITE_ORDER:
            self.suite_vars[suite_name].set(True)
            for entry in self.category_catalog[suite_name]:
                self.category_vars[suite_name][entry["id"]].set(True)
        self.refresh_test_review()

    def clear_suites(self):
        for suite_name in SUITE_ORDER:
            self.suite_vars[suite_name].set(False)
            for entry in self.category_catalog[suite_name]:
                self.category_vars[suite_name][entry["id"]].set(False)
        self.refresh_test_review()

    def refresh_test_review(self):
        if not self.test_review_text:
            return

        selected = self.selected_categories()
        if not selected:
            lines = [
                "No prompt categories selected yet.",
                "",
                "Use the checkboxes on the left to choose at least one category.",
            ]
        else:
            lines = []
            for suite_name in SUITE_ORDER:
                selected_entries = [
                    entry
                    for entry in self.category_catalog[suite_name]
                    if self.category_vars[suite_name][entry["id"]].get()
                ]
                if not selected_entries:
                    continue

                lines.extend(
                    [
                        suite_name,
                        SUITE_INFO[suite_name]["description"],
                        (
                            f"Selected categories: {len(selected_entries)}  "
                            f"|  Prompt turns: {sum(count_category_prompts(entry) for entry in selected_entries)}"
                        ),
                        "",
                    ]
                )

                for entry in selected_entries:
                    lines.append(
                        f"[x] {entry['title']} "
                        f"({count_category_cases(entry)} prompt sets / {count_category_prompts(entry)} prompts)"
                    )
                    for case_index, case in enumerate(entry["cases"], start=1):
                        lines.append(
                            f"  Prompt set {case_index}: {case['title']} ({case['mode']})"
                        )
                        for prompt_index, prompt_text in enumerate(case["prompts"], start=1):
                            lines.append(f"    Prompt {prompt_index}: {prompt_text}")
                    lines.append("")

                lines.append("-" * 80)
                lines.append("")

        self.test_review_text.configure(state="normal")
        self.test_review_text.delete("1.0", "end")
        self.test_review_text.insert("1.0", "\n".join(lines).strip())
        self.test_review_text.configure(state="disabled")

    def start_run(self):
        if self.run_thread and self.run_thread.is_alive():
            return

        selected_category_ids = self.selected_categories()
        suites = [name for name in SUITE_ORDER if name in selected_category_ids]
        if not suites:
            messagebox.showerror("No Tests Selected", "Select at least one prompt category.")
            return

        model_id = self.model_box.get().strip()
        if not model_id:
            messagebox.showerror("No Model Selected", "Select a model from the list.")
            return

        model = self.current_model()
        if not model:
            messagebox.showerror("No Model Selected", "Select a model from the list.")
            return

        profile_name = self.profile_var.get().strip()
        profiles = self.profile_store.get("profiles", {})
        if not profile_name or profile_name not in profiles:
            messagebox.showerror(
                "Profile Required",
                "Create and select a profile before running the benchmark.",
            )
            return

        if model not in self.available_models_for_active_profile():
            messagebox.showerror(
                "Model Not Available",
                f"The active profile '{profile_name}' is not configured for model '{model_id}'.",
            )
            return

        env_name = model.get("api_key_env")
        if env_name and not self.get_profile_model_key(profiles[profile_name], model):
            messagebox.showerror(
                "Missing API Key",
                f"The active profile '{profile_name}' does not have a saved value for {env_name}.",
            )
            return

        self.apply_profile_environment(profile_name, model_id)

        self.last_result = None
        self.open_report_button.configure(state="disabled")
        self.open_results_button.configure(state="disabled")
        self.set_summary(
            "Benchmark is running. Scores and the generated report summary will appear here when the run finishes."
        )
        self.clear_scores()
        self.set_log_text("")
        selected_category_count = sum(len(items) for items in selected_category_ids.values())
        self.log(
            f"Starting benchmark for {model_id} using profile {profile_name} with "
            f"{selected_category_count} categories across: {', '.join(suites)}"
        )
        self.set_status_message("Running benchmark...", tone="info")
        self.run_started_at = time.monotonic()
        self.progress_total_units = 1
        self.progress_completed_units = 0
        self.progress_detail = "Preparing run"
        self.progress.configure(maximum=1, value=0)
        self.update_progress_display()
        self.run_button.configure(state="disabled")

        self.run_thread = threading.Thread(
            target=self.run_worker,
            args=(model_id, suites, selected_category_ids),
            daemon=True,
        )
        self.run_thread.start()

    def run_worker(self, model_id, suites, selected_category_ids):
        try:
            result = run_benchmark(
                config_path=self.config_path,
                model_id=model_id,
                selected_suites=suites,
                selected_category_ids=selected_category_ids,
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
                self.set_status_message(event["message"], tone="info")
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
        self.set_status_message("Benchmark finished.", tone="success")
        self.progress_detail = "Benchmark complete"
        self.update_progress_display(force_complete=True)
        self.run_started_at = None
        self.populate_scores(result["summary"])
        self.populate_summary(result)
        self.log(f"Report saved to {result['paths']['report_path']}")

    def fail_run(self, message):
        self.run_button.configure(state="normal")
        self.set_status_message("Benchmark failed.", tone="error")
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
            "Selected Prompt Categories:",
        ]
        for suite_name in summary["selected_suites"]:
            lines.append(f"{suite_name}:")
            for entry in summary["selected_categories"].get(suite_name, []):
                lines.append(
                    f"- {entry['category_title']} ({entry['case_count']} prompt sets / {entry['prompt_count']} prompts)"
                )

        lines.extend(
            [
                "",
                "Score Categories:",
            ]
        )
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


def default_profile_store_path():
    if os.name == "nt":
        base_dir = Path(os.getenv("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    else:
        base_dir = Path(os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base_dir / "llm-bench-app" / "profiles.json"


def load_profile_store(path):
    default_store = {"active_profile": "", "profiles": {}}
    if not path.exists():
        return default_store

    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_store

    if not isinstance(loaded, dict):
        return default_store

    profiles = loaded.get("profiles", {})
    if not isinstance(profiles, dict):
        profiles = {}

    clean_profiles = {}
    for profile_name, profile_value in profiles.items():
        if not isinstance(profile_name, str) or not isinstance(profile_value, dict):
            continue
        api_keys = profile_value.get("api_keys", {})
        if not isinstance(api_keys, dict):
            api_keys = {}
        model_keys = profile_value.get("model_keys", {})
        if not isinstance(model_keys, dict):
            model_keys = {}
        clean_profiles[profile_name] = {
            "api_keys": {str(key): str(value) for key, value in api_keys.items() if value},
            "model_keys": {str(key): str(value) for key, value in model_keys.items() if value},
        }

    active_profile = loaded.get("active_profile", "")
    if active_profile not in clean_profiles:
        active_profile = ""

    return {"active_profile": active_profile, "profiles": clean_profiles}


def save_profile_store(path, store):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2, ensure_ascii=True), encoding="utf-8")


def build_headless_category_selection(suites, category_ids):
    if not category_ids:
        return suites, None

    selection = {}
    unknown = []
    for category_id in category_ids:
        matched = False
        for suite_name in suites:
            suite_category_ids = [entry["id"] for entry in get_suite_categories(suite_name)]
            if category_id in suite_category_ids:
                selection.setdefault(suite_name, []).append(category_id)
                matched = True
                break
        if not matched:
            unknown.append(category_id)

    if unknown:
        raise ValueError(
            "Unknown category ids for the selected suites: " + ", ".join(unknown)
        )

    filtered_suites = [suite_name for suite_name in suites if suite_name in selection]
    if not filtered_suites:
        raise ValueError("No matching prompt categories were selected for the requested suites.")

    return filtered_suites, selection


def run_headless(config_path, model_id, suites, category_ids=None):
    suites, selected_category_ids = build_headless_category_selection(suites, category_ids)
    result = run_benchmark(
        config_path=config_path,
        model_id=model_id,
        selected_suites=suites,
        selected_category_ids=selected_category_ids,
    )
    print(f"Overall Benchmark Score: {result['summary']['overall_benchmark_score']:.1f}")
    for suite_name in result["summary"]["selected_suites"]:
        category_titles = [
            entry["category_title"]
            for entry in result["summary"]["selected_categories"].get(suite_name, [])
        ]
        print(f"{suite_name} categories: {', '.join(category_titles)}")
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
    parser.add_argument(
        "--category-ids",
        nargs="+",
        help="Optional prompt category ids to run in headless mode",
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
        return run_headless(args.config, args.model_id, args.tests, args.category_ids)

    root = tk.Tk()
    app = BenchmarkApp(root, args.config)
    del app
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
