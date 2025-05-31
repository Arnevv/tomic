import os
import sys
import subprocess
import difflib
from loguru import logger

from tomic.logging import setup_logging

try:
    from deepdiff import DeepDiff
    HAS_DEEPDIFF = True
except ImportError:  # pragma: no cover - optional dependency
    HAS_DEEPDIFF = False


def run_command(cmd: list[str]) -> None:
    """Run command silently and raise on failure."""
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        logger.error(result.stdout)
        result.check_returncode()


def compare_files(output_path: str, benchmark_path: str) -> bool:
    """Return True if files differ and print diff."""
    if HAS_DEEPDIFF:
        import json
        with open(output_path, encoding="utf-8") as f_out, open(benchmark_path, encoding="utf-8") as f_bench:
            data_out = json.load(f_out)
            data_bench = json.load(f_bench)
        diff = DeepDiff(data_bench, data_out, ignore_order=True)
        if diff:
            logger.info("Differences for %s:", os.path.basename(output_path))
            logger.info(diff)
            return True
        return False
    else:
        with open(output_path, encoding="utf-8") as f_out, open(benchmark_path, encoding="utf-8") as f_bench:
            out_lines = f_out.read().splitlines()
            bench_lines = f_bench.read().splitlines()
        diff_lines = list(
            difflib.unified_diff(
                bench_lines,
                out_lines,
                fromfile=benchmark_path,
                tofile=output_path,
                lineterm="",
            )
        )
        if diff_lines:
            diff_only = [
                line
                for line in diff_lines
                if line.startswith(("+", "-"))
                and not line.startswith(("+++", "---"))
            ]
            logger.info("Differences for %s:", os.path.basename(output_path))
            logger.info("\n".join(diff_only))
            return True
        return False


def main() -> None:
    setup_logging()
    logger.info("🚀 Start regression run")
    os.environ["TOMIC_TODAY"] = "2025-05-29"
    os.makedirs("regression_output", exist_ok=True)

    run_command([
        "python",
        "strategy_dashboard.py",
        "regression_input/positions_benchmark.json",
        "regression_input/account_info_benchmark.json",
        "--json-output",
        "regression_output/strategy_dashboard_output.json",
    ])

    run_command([
        "python",
        "performance_analyzer.py",
        "regression_input/journal_benchmark.json",
        "--json-output",
        "regression_output/performance_analyzer_output.json",
    ])

    diff_found = False
    for name in os.listdir("regression_output"):
        out_path = os.path.join("regression_output", name)
        bench_path = os.path.join("benchmarks", name)
        if not os.path.exists(bench_path):
            logger.error("Benchmark file missing: %s", bench_path)
            diff_found = True
            continue
        if compare_files(out_path, bench_path):
            diff_found = True

    if diff_found:
        logger.warning("Regression FAILED")
        sys.exit(1)
    logger.success("Regression PASSED")


if __name__ == "__main__":
    main()

