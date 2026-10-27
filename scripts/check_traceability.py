#!/usr/bin/env python3
"""
check_traceability.py — Traceability gate for the Laptop Productivity Monitoring SaaS.

Default mode:
  Fails if any row in TRACEABILITY.md has no prompt assigned.

--final mode:
  Also fails if any row is not 'done' or 'limitation', has no test path,
  or points to a test file that does not exist.
  Additionally verifies that a test named test_E## exists for each of the
  100 edge cases E01–E100.

Usage:
  python scripts/check_traceability.py
  python scripts/check_traceability.py --final
"""

from __future__ import annotations

import argparse
import io
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Ensure UTF-8 output on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


# ── Configuration ─────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parent.parent
TRACEABILITY_FILE = REPO_ROOT / "TRACEABILITY.md"
EDGE_CASE_IDS = [f"E{i:02d}" for i in range(1, 101)]

VALID_STATUSES = {"todo", "done", "limitation"}
FINAL_REQUIRED_STATUSES = {"done", "limitation"}


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class Row:
    id: str
    description: str
    section: str
    prompt: str
    code_path: str
    test_path: str
    status: str
    line_number: int
    section_name: str  # e.g. "Requirements", "Edge Cases", "Acceptance Criteria"


# ── Parser ────────────────────────────────────────────────────────────────────

def parse_table_rows(content: str) -> list[Row]:
    """Parse all table rows from TRACEABILITY.md."""
    rows: list[Row] = []
    current_section = "Unknown"
    line_number = 0

    for line in content.splitlines():
        line_number += 1
        stripped = line.strip()

        # Detect section headings
        if stripped.startswith("## "):
            current_section = stripped[3:].strip()
            continue

        # Skip non-table lines
        if not stripped.startswith("|"):
            continue

        # Skip header rows (contain 'ID' as first cell)
        if re.match(r'^\|\s*ID\s*\|', stripped):
            continue
        # Skip separator rows (all cells are dashes)
        if re.match(r'^\|[-|\s:]+\|\s*$', stripped):
            continue

        parts = [p.strip() for p in stripped.split("|")]
        # Remove leading/trailing empty strings from split
        parts = [p for p in parts if p != ""]

        # Requirements and Edge Cases: 7 columns (may be fewer due to encoding)
        # | ID | Req/EC | Spec | Prompt | Code Path | Test Path | Status |
        if len(parts) >= 2:
            row_id = parts[0]
            # Skip rows that don't look like IDs
            if not re.match(r'^(REQ-|E\d{2}|AC-|RC-)', row_id):
                continue

            description = parts[1] if len(parts) > 1 else ""
            section = parts[2] if len(parts) > 2 else ""
            prompt = parts[3] if len(parts) > 3 else ""
            code_path = parts[4] if len(parts) > 4 else ""
            test_path = parts[5] if len(parts) > 5 else ""
            status = parts[6] if len(parts) > 6 else (parts[4] if len(parts) > 4 else "")

            rows.append(Row(
                id=row_id,
                description=description,
                section=section,
                prompt=prompt,
                code_path=code_path,
                test_path=test_path,
                status=status.lower().strip(),
                line_number=line_number,
                section_name=current_section,
            ))

    return rows


# ── Checks ────────────────────────────────────────────────────────────────────

def check_prompt_assigned(rows: list[Row]) -> list[str]:
    """Fail if any row has no prompt assigned."""
    errors: list[str] = []
    for row in rows:
        if not row.prompt or row.prompt in ("", "-"):
            errors.append(
                f"Line ~{row.line_number}: [{row.id}] '{row.description[:60]}' has no prompt assigned."
            )
    return errors


def check_final(rows: list[Row], repo_root: Path) -> list[str]:
    """Final gate: status must be done/limitation, test path must exist."""
    errors: list[str] = []

    for row in rows:
        # Status check
        if row.status not in FINAL_REQUIRED_STATUSES:
            errors.append(
                f"Line ~{row.line_number}: [{row.id}] status='{row.status}' — must be 'done' or 'limitation'."
            )

        # Test path must be present
        if not row.test_path or row.test_path in ("", "-"):
            errors.append(
                f"Line ~{row.line_number}: [{row.id}] has no test path."
            )
        else:
            # Verify the test file(s) exist
            for test_file in row.test_path.split(","):
                test_file = test_file.strip()
                if not test_file or test_file == "-":
                    continue
                # Strip any line anchors like #L123
                test_file_path = test_file.split("#")[0]
                full_path = repo_root / test_file_path
                if not full_path.exists():
                    errors.append(
                        f"Line ~{row.line_number}: [{row.id}] test file does not exist: {test_file_path}"
                    )

    return errors


def check_edge_case_tests(repo_root: Path) -> list[str]:
    """Verify that a test named test_E## exists for each of the 100 edge cases."""
    errors: list[str] = []

    # Collect all test files in tests/ and backend/tests/ and agent/tests/
    test_dirs = [
        repo_root / "tests",
        repo_root / "backend",
        repo_root / "agent",
    ]

    # Find all Python test files
    test_files: list[Path] = []
    for test_dir in test_dirs:
        if test_dir.exists():
            test_files.extend(test_dir.rglob("test_*.py"))
            test_files.extend(test_dir.rglob("*_test.py"))

    # Build a set of all function names found
    found_tests: set[str] = set()
    for tf in test_files:
        try:
            content = tf.read_text(encoding="utf-8", errors="ignore")
            # Find all function definitions named test_E##*
            matches = re.findall(r'def (test_E\d{2}[^\s(]*)', content)
            found_tests.update(matches)
        except Exception:
            pass

    # Check each edge case
    for ec_id in EDGE_CASE_IDS:
        pattern = f"test_{ec_id}"
        matching = [t for t in found_tests if t.startswith(pattern)]
        if not matching:
            errors.append(f"[{ec_id}] No test function named test_{ec_id}_* found in any test file.")

    return errors


# ── Reporting ─────────────────────────────────────────────────────────────────

def print_summary(rows: list[Row]) -> None:
    """Print counts per prompt and status."""
    from collections import Counter

    prompt_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()

    for row in rows:
        prompt_counts[row.prompt or "(unassigned)"] += 1
        status_counts[row.status or "(empty)"] += 1

    print("\n-- Counts by prompt ------------------------------------------")
    for prompt, count in sorted(prompt_counts.items()):
        print(f"  {prompt:<20} {count:>4} rows")

    print("\n-- Counts by status ------------------------------------------")
    for status, count in sorted(status_counts.items()):
        print(f"  {status:<15} {count:>4} rows")

    print(f"\n  Total rows: {len(rows)}")

    # Edge case coverage
    ec_rows = [r for r in rows if re.match(r'^E\d{2}$', r.id)]
    done_ec = [r for r in ec_rows if r.status in FINAL_REQUIRED_STATUSES]
    print("\n-- Edge case coverage ----------------------------------------")
    print(f"  {len(done_ec)}/{len(ec_rows)} edge cases done or limitation")
    print(f"  {len(ec_rows) - len(done_ec)} still todo")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Traceability gate for Laptop Productivity Monitoring SaaS"
    )
    parser.add_argument(
        "--final",
        action="store_true",
        help="Final gate: also check status, test paths, and edge case test functions",
    )
    args = parser.parse_args()

    if not TRACEABILITY_FILE.exists():
        print(f"ERROR: {TRACEABILITY_FILE} not found.", file=sys.stderr)
        return 1

    content = TRACEABILITY_FILE.read_text(encoding="utf-8")
    rows = parse_table_rows(content)

    if not rows:
        print("ERROR: No traceability rows found. Is TRACEABILITY.md formatted correctly?", file=sys.stderr)
        return 1

    all_errors: list[str] = []

    # Always check: every row must have a prompt
    prompt_errors = check_prompt_assigned(rows)
    all_errors.extend(prompt_errors)

    if args.final:
        # Check status and test file existence
        final_errors = check_final(rows, REPO_ROOT)
        all_errors.extend(final_errors)

        # Check edge case test functions
        ec_test_errors = check_edge_case_tests(REPO_ROOT)
        all_errors.extend(ec_test_errors)

    print_summary(rows)

    if all_errors:
        print(f"\n-- ERRORS ({len(all_errors)}) ------------------------------------------")
        for error in all_errors:
            print(f"  FAIL: {error}")
        print(f"\nFAILED -- {len(all_errors)} error(s). Fix them and re-run.")
        return 1
    else:
        mode = "final" if args.final else "default"
        print(f"\nPASSED ({mode} mode) -- All traceability checks passed.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
