#!/usr/bin/env python3
"""check_migrations.py — CI Gate enforcing Expand-Then-Contract migration discipline (E78).

Detects destructive database operations (RemoveField, DeleteModel) in migration files.
Fails if any destructive operation lacks an explicit approval marker:
    # ALLOW_DESTRUCTIVE: <approved reasoning>
"""
import ast
import re
import sys
from pathlib import Path

DESTRUCTIVE_OPERATIONS = {
    "RemoveField",
    "DeleteModel",
}

APPROVAL_PATTERN = re.compile(r"#\s*ALLOW_DESTRUCTIVE:\s*(.+)")


def check_migration_file(path: Path) -> list[str]:
    violations: list[str] = []
    text = path.read_text(encoding="utf-8")

    # Check if file has approval comment
    if APPROVAL_PATTERN.search(text):
        return []

    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as e:
        return [f"Syntax error in migration {path}: {e}"]

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            op_name = None
            if isinstance(func, ast.Attribute) and func.attr in DESTRUCTIVE_OPERATIONS:
                op_name = func.attr
            elif isinstance(func, ast.Name) and func.id in DESTRUCTIVE_OPERATIONS:
                op_name = func.id

            if op_name:
                violations.append(
                    f"{path}:{node.lineno} — Destructive operation '{op_name}' without approved marker '# ALLOW_DESTRUCTIVE: <reason>'."
                )

    return violations


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    backend_dir = repo_root / "backend"

    migration_files = list(backend_dir.glob("apps/*/migrations/*.py"))
    migration_files = [f for f in migration_files if f.name != "__init__.py"]

    all_violations: list[str] = []
    for mf in migration_files:
        violations = check_migration_file(mf)
        all_violations.extend(violations)

    if all_violations:
        print("FAIL (E78 Migration Discipline) — Destructive operations detected without approval:")
        for v in all_violations:
            print(f"  {v}")
        return 1

    print(f"PASSED (E78) — Scanned {len(migration_files)} migration files. No unapproved destructive operations.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
