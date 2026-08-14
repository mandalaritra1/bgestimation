#!/usr/bin/env python3
"""Write a fail-closed provenance manifest for one pre-unblinding campaign.

The script deliberately records files and runtime facts only.  It makes no
physics interpretation of the campaign inputs or results.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterable


EXPECTED_INPUT_ROOTS = 29


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def command_record(command: list[str], cwd: Path | None = None) -> dict[str, Any]:
    """Capture a version-control or runtime command without raising on failure."""
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"returncode": None, "stdout": "", "stderr": str(error)}
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def command_stdout(command: list[str], cwd: Path | None = None) -> str | None:
    result = command_record(command, cwd)
    if result["returncode"] != 0:
        return None
    return result["stdout"]


def combine_version_record() -> dict[str, Any]:
    """Capture Combine's banner even though v10 rejects ``--version``."""
    record = command_record(["combine", "--version"])
    banner = "\n".join((record["stdout"], record["stderr"]))
    match = re.search(r"\bv(\d+(?:\.\d+)+)\b", banner)
    record["parsed_version"] = match.group(1) if match else None
    return record


def git_record(path: Path) -> dict[str, Any]:
    """Return the repository identity and current tracked working-tree state."""
    root = command_stdout(["git", "rev-parse", "--show-toplevel"], path)
    if not root:
        return {
            "path": str(path),
            "repository_root": None,
            "head": None,
            "branch": None,
            "status": None,
            "diff_sha256": None,
        }
    repository = Path(root)
    diff = command_record(["git", "diff", "--binary", "HEAD"], repository)
    diff_bytes = (diff["stdout"] + "\n" + diff["stderr"]).encode("utf-8")
    return {
        "path": str(path),
        "repository_root": str(repository),
        "head": command_stdout(["git", "rev-parse", "HEAD"], repository),
        "branch": command_stdout(["git", "branch", "--show-current"], repository),
        "status": command_stdout(["git", "status", "--short", "--branch"], repository),
        "diff_sha256": hashlib.sha256(diff_bytes).hexdigest(),
        "diff_command_returncode": diff["returncode"],
    }


def classify_input(path: Path) -> str:
    """Classify by filename solely for inventory bookkeeping."""
    name = path.name.lower()
    if "zprime" in name:
        return "signal"
    if "data" in name:
        return "data"
    if "ttbar" in name:
        return "ttbar"
    return "other"


def iter_input_files(inputs_dir: Path) -> Iterable[Path]:
    for path in sorted(inputs_dir.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise ValueError(f"Refusing symlink in campaign inputs: {path}")
        if path.is_file():
            yield path


def capture_inputs(inputs_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    files: list[dict[str, Any]] = []
    classes: dict[str, int] = {}
    root_count = 0
    for path in iter_input_files(inputs_dir):
        is_root = path.suffix.lower() == ".root"
        classification = classify_input(path) if is_root else "non_root"
        classes[classification] = classes.get(classification, 0) + 1
        if is_root:
            root_count += 1
        files.append(
            {
                "path": path.relative_to(inputs_dir).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "is_root": is_root,
                "classification": classification,
            }
        )
    if root_count != EXPECTED_INPUT_ROOTS:
        raise ValueError(
            f"Expected exactly {EXPECTED_INPUT_ROOTS} input ROOT files in "
            f"{inputs_dir}, found {root_count}"
        )
    return files, {
        "all_files": len(files),
        "root_files": root_count,
        "non_root_files": len(files) - root_count,
        "classification": dict(sorted(classes.items())),
    }


def capture_source_hashes(repo: Path) -> dict[str, Any]:
    requested = [
        repo / "ttbar.py",
        repo / "run3" / "validate_expected_limit.py",
        repo / "run3" / "validate_fit_result.py",
    ]
    preunblind = repo / "run3" / "preunblind"
    if preunblind.exists():
        requested.extend(path for path in preunblind.rglob("*") if path.is_file())

    result: dict[str, Any] = {}
    for path in sorted(set(requested), key=lambda item: item.as_posix()):
        relative = path.relative_to(repo).as_posix()
        if not path.is_file():
            result[relative] = {"missing": True}
            continue
        result[relative] = {
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    return result


def find_git_root(path: Path) -> Path | None:
    root = command_stdout(["git", "rev-parse", "--show-toplevel"], path)
    return Path(root) if root else None


def capture_twodalphabet() -> dict[str, Any]:
    record: dict[str, Any] = {"source_path": None, "git": None, "version": None}
    spec = importlib.util.find_spec("TwoDAlphabet")
    if spec and spec.origin:
        source_path = Path(spec.origin).resolve()
        record["source_path"] = str(source_path)
        source_root = find_git_root(source_path.parent)
        if source_root:
            record["git"] = git_record(source_root)

    for distribution in ("TwoDAlphabet", "2DAlphabet"):
        try:
            record["version"] = importlib.metadata.version(distribution)
            record["distribution"] = distribution
            break
        except importlib.metadata.PackageNotFoundError:
            continue
    return record


def atomic_json_dump(output: Path, payload: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    repo = args.repo.resolve()
    campaign = args.campaign.resolve()
    inputs_dir = campaign / "inputs"
    if not repo.is_dir():
        parser.error(f"--repo is not a directory: {repo}")
    if not campaign.is_dir():
        parser.error(f"--campaign is not a directory: {campaign}")
    if not inputs_dir.is_dir():
        parser.error(f"missing required campaign input directory: {inputs_dir}")

    try:
        inputs, input_counts = capture_inputs(inputs_dir)
    except ValueError as error:
        print(f"MANIFEST REFUSED: {error}", file=sys.stderr)
        return 2

    payload = {
        "captured_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "campaign": str(campaign),
        "repo": git_record(repo),
        "inputs": {"directory": str(inputs_dir), "counts": input_counts, "files": inputs},
        "source_hashes": capture_source_hashes(repo),
        "environment": {
            "CMSSW_BASE": os.environ.get("CMSSW_BASE"),
            "SCRAM_ARCH": os.environ.get("SCRAM_ARCH"),
        },
        "runtime": {
            "combine": combine_version_record(),
            "root_config": command_record(["root-config", "--version"]),
            "python3": command_record(["python3", "--version"]),
        },
        "twodalphabet": capture_twodalphabet(),
    }
    atomic_json_dump(args.output, payload)
    print(f"Wrote provenance manifest: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
