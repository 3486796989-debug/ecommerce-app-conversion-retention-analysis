"""One-click runner for the full e-commerce analysis project.

This file combines the two original steps:
1. Run the pandas/NumPy analysis pipeline.
2. Generate matplotlib charts, the HTML report, README, and notebook.

Example:
    python scripts/run_full_ecommerce_project.py \
        --zip-path "C:/path/to/archive.zip" \
        --project-root .
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from types import ModuleType


def load_script_module(script_path: Path, module_name: str) -> ModuleType:
    """Load a Python script whose file name is not import-friendly."""
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {script_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_full_project(
    zip_path: Path,
    project_root: Path,
    data_dir: Path | None = None,
    report_dir: Path | None = None,
    chunksize: int = 500_000,
    max_rows_per_file: int | None = None,
) -> None:
    project_root = project_root.resolve()
    scripts_dir = project_root / "scripts"
    data_dir = data_dir or project_root / "data" / "processed"
    report_dir = report_dir or project_root / "report"

    analysis_module = load_script_module(scripts_dir / "01_run_pandas_analysis.py", "pandas_analysis_pipeline")
    report_module = load_script_module(scripts_dir / "02_generate_report.py", "report_generation_pipeline")

    print("[step 1/2] Running pandas analysis pipeline...", flush=True)
    analysis_module.analyze(
        zip_path=zip_path,
        output_dir=data_dir,
        chunksize=chunksize,
        max_rows_per_file=max_rows_per_file,
    )

    print("[step 2/2] Generating charts and report...", flush=True)
    report_module.generate(
        data_dir=data_dir,
        report_dir=report_dir,
        project_root=project_root,
    )

    print("[complete] Full e-commerce analysis project finished.", flush=True)
    print(f"Processed data: {data_dir}", flush=True)
    print(f"Report: {report_dir / 'ecommerce_conversion_retention_report.html'}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the full e-commerce conversion and retention analysis project.")
    parser.add_argument("--zip-path", required=True, type=Path, help="Path to the raw ZIP archive.")
    parser.add_argument("--project-root", default=Path("."), type=Path, help="Project root directory.")
    parser.add_argument("--data-dir", default=None, type=Path, help="Optional output directory for processed tables.")
    parser.add_argument("--report-dir", default=None, type=Path, help="Optional output directory for report assets.")
    parser.add_argument("--chunksize", default=500_000, type=int, help="Rows per pandas chunk.")
    parser.add_argument("--max-rows-per-file", default=None, type=int, help="Optional row cap for fast testing.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_full_project(
        zip_path=args.zip_path,
        project_root=args.project_root,
        data_dir=args.data_dir,
        report_dir=args.report_dir,
        chunksize=args.chunksize,
        max_rows_per_file=args.max_rows_per_file,
    )
