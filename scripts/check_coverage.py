import json
import sys
from pathlib import Path


def main() -> int:
    report_path = Path("coverage.json")
    if len(sys.argv) > 1:
        report_path = Path(sys.argv[1])
    data = json.loads(report_path.read_text(encoding="utf-8"))
    totals = data.get("totals", {})
    covered_lines = totals.get("covered_lines", 0)
    num_statements = totals.get("num_statements", 0)
    covered_branches = totals.get("covered_branches", 0)
    num_branches = totals.get("num_branches", 0)
    line_coverage = (covered_lines / num_statements * 100) if num_statements else 100.0
    branch_coverage = (covered_branches / num_branches * 100) if num_branches else 100.0
    min_line = 90.0
    min_branch = 85.0
    if len(sys.argv) > 2:
        min_line = float(sys.argv[2])
    if len(sys.argv) > 3:
        min_branch = float(sys.argv[3])
    if line_coverage < min_line or branch_coverage < min_branch:
        print(f"Line coverage {line_coverage:.2f}% < {min_line:.2f}% or branch coverage {branch_coverage:.2f}% < {min_branch:.2f}%")
        return 1
    print(f"Line coverage {line_coverage:.2f}%, branch coverage {branch_coverage:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
