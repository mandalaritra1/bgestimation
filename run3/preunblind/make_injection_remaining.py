#!/usr/bin/env python3
"""Create a non-overwriting remaining-row matrix from validated completed rows."""

from __future__ import annotations

import argparse
from pathlib import Path


def rows(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text().splitlines() if line.strip() and not line.lstrip().startswith("#")]


def identity(line: str) -> tuple[int, int, str]:
    fields = line.split()
    if len(fields) != 8:
        raise ValueError(f"expected eight columns: {line!r}")
    return int(fields[0]), int(fields[1]), fields[3]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--completed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError(f"refusing to overwrite remaining matrix: {args.output}")
    full = rows(args.matrix)
    completed = rows(args.completed)
    full_ids = [identity(line) for line in full]
    completed_ids = [identity(line) for line in completed]
    if len(full) != 48 or len(set(full_ids)) != 48:
        raise ValueError("full injection matrix is not 48 unique point-label rows")
    if len(completed) != 1 or len(set(completed_ids)) != 1:
        raise ValueError("current completion contract requires exactly one completed canary")
    completed_id = completed_ids[0]
    matching = [line for line in full if identity(line) == completed_id]
    if matching != completed:
        raise ValueError("completed canary row does not exactly match full matrix")
    remaining = [line for line in full if identity(line) != completed_id]
    if len(remaining) != 47 or len({identity(line) for line in remaining}) != 47:
        raise ValueError("remaining injection matrix is not exactly 47 unique rows")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        handle.write("".join(f"{line}\n" for line in remaining))
    print(f"INJECTION_REMAINING_OK rows={len(remaining)} excluded={completed_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
