import os
import sys
import subprocess
import difflib

try:
    from deepdiff import DeepDiff
    HAS_DEEPDIFF = True
except ImportError:  # pragma: no cover - optional dependency
    HAS_DEEPDIFF = False


def run_command(cmd: list[str]) -> None:
    """Run command via subprocess and raise on failure."""
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def compare_files(output_path: str, benchmark_path: str) -> bool:
    """Return True if files differ and print diff."""
    if HAS_DEEPDIFF:
        import json
        with open(output_path) as f_out, open(benchmark_path) as f_bench:
            data_out = json.load(f_out)
            data_bench = json.load(f_bench)
        diff = DeepDiff(data_bench, data_out, ignore_order=True)
        if diff:
            print(f"Differences for {os.path.basename(output_path)}:")
            print(diff)
            return True
        return False
    else:
        with open(output_path) as f_out, open(benchmark_path) as f_bench:
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
            print("\n".join(diff_lines))
            return True
        return False


def main() -> None:
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
            print(f"Benchmark file missing: {bench_path}")
            diff_found = True
            continue
        if compare_files(out_path, bench_path):
            diff_found = True

    if diff_found:
        sys.exit(1)


if __name__ == "__main__":
    main()
