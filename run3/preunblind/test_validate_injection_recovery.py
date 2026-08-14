#!/usr/bin/env python3
"""Synthetic tests for the blinded injection-recovery validator."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("validate_injection_recovery.py")
SPEC = importlib.util.spec_from_file_location("validate_injection_recovery", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class InjectionRecoveryValidatorTest(unittest.TestCase):
    def make_campaign(self, directory: Path) -> tuple[Path, Path]:
        matrix = []
        root = directory / "asimov"
        points = [(width, 1000 + 100 * index) for width in (1, 10, 30) for index in range(4)]
        for width, mass in points:
            for label, scale in (("bkg", 0.0), ("half", 0.5), ("one", 1.0), ("two", 2.0)):
                injected = 0.2 * scale
                row = {
                    "width_percent": width,
                    "mass_GeV": mass,
                    "rMax": 2.0,
                    "injection_label": label,
                    "injected_r": injected,
                    "median_expected_r95": 0.2,
                    "start_zero": 0.0,
                    "start_injected": injected,
                    "start_high": 0.6,
                    "start_high_definition": "min(0.5*rMax,3*median_expected_r95)",
                }
                matrix.append(row)
                for start_label, start_key in MODULE.EXPECTED_STARTS:
                    path = root / f"w{width}" / f"m{mass}" / label / f"fit_{start_label}.json"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    payload = {
                        "metadata": {
                            "width_percent": str(width),
                            "mass_GeV": str(mass),
                            "rMax": "2.0",
                            "injection_label": label,
                            "injected_r": str(injected),
                            "start_label": start_label,
                            "start_r": str(row[start_key]),
                        },
                        "fit": {"status": 0, "cov_qual": 3, "edm": 1.0e-4},
                        "r": {
                            "name": "r", "value": injected, "error": 0.1,
                            "min": 0.0, "max": 2.0, "constant": False,
                            "boundary": {
                                "accessible": True,
                                "outside_bounds": False,
                                "at_min": injected == 0.0,
                                "at_max": False,
                                "near_min": injected == 0.0,
                                "near_max": False,
                            },
                        },
                    }
                    path.write_text(json.dumps(payload))
        matrix_path = directory / "matrix.json"
        matrix_path.write_text(json.dumps(matrix))
        return matrix_path, root

    def run_validator(self, matrix: Path, root: Path, output: Path) -> int:
        return MODULE.main(
            [
                "--matrix-json", str(matrix),
                "--injections-root", str(root),
                "--output", str(output),
            ]
        )

    def test_accepts_complete_consistent_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            matrix, root = self.make_campaign(directory)
            output = directory / "report.json"
            self.assertEqual(self.run_validator(matrix, root, output), 0)
            report = json.loads(output.read_text())
            self.assertTrue(report["accepted"])
            self.assertEqual(report["n_rows"], 48)
            self.assertIn("max_abs_recovery_pull", report["thresholds"])

    def test_rejects_biased_nonzero_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            matrix, root = self.make_campaign(directory)
            path = root / "w1" / "m1000" / "one" / "fit_zero.json"
            payload = json.loads(path.read_text())
            payload["r"]["value"] = 0.8
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(MODULE.ValidationError, "recovery pull"):
                self.run_validator(matrix, root, directory / "report.json")

    def test_rejects_start_dependence_even_when_each_recovery_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            matrix, root = self.make_campaign(directory)
            for start_label, value in (("zero", 0.25), ("injected", 0.15), ("high", 0.2)):
                path = root / "w1" / "m1000" / "one" / f"fit_{start_label}.json"
                payload = json.loads(path.read_text())
                payload["r"]["value"] = value
                payload["r"]["error"] = 0.02
                path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(MODULE.ValidationError, "fails invariance"):
                self.run_validator(matrix, root, directory / "report.json")

    def test_rejects_large_one_sided_background_excursion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            matrix, root = self.make_campaign(directory)
            path = root / "w1" / "m1000" / "bkg" / "fit_zero.json"
            payload = json.loads(path.read_text())
            payload["r"]["value"] = 0.4
            payload["r"]["error"] = 0.1
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(MODULE.ValidationError, "background injection"):
                self.run_validator(matrix, root, directory / "report.json")

    def test_background_uses_asymmetric_upper_error_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            matrix, root = self.make_campaign(directory)
            for start_label, _ in MODULE.EXPECTED_STARTS:
                path = root / "w1" / "m1000" / "bkg" / f"fit_{start_label}.json"
                payload = json.loads(path.read_text())
                payload["r"]["value"] = 0.4
                payload["r"]["error"] = 0.1
                payload["r"]["error_high"] = 0.2
                path.write_text(json.dumps(payload))
            output = directory / "report.json"
            self.assertEqual(self.run_validator(matrix, root, output), 0)
            report = json.loads(output.read_text())
            result = report["rows"][0]["fits"]["zero"]
            self.assertEqual(result["one_sided_upper_error"], 0.2)

    def test_rejects_missing_harvested_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            matrix, root = self.make_campaign(directory)
            (root / "w1" / "m1000" / "bkg" / "fit_zero.json").unlink()
            with self.assertRaisesRegex(MODULE.ValidationError, "missing harvested fit JSON"):
                self.run_validator(matrix, root, directory / "report.json")

    def test_rejects_duplicate_matrix_row(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            matrix, root = self.make_campaign(directory)
            rows = json.loads(matrix.read_text())
            rows[1] = rows[0]
            matrix.write_text(json.dumps(rows))
            with self.assertRaisesRegex(MODULE.ValidationError, "duplicate injection matrix row"):
                self.run_validator(matrix, root, directory / "report.json")

    def test_rejects_bad_fit_quality_and_nonfinite_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            matrix, root = self.make_campaign(directory)
            path = root / "w1" / "m1000" / "one" / "fit_zero.json"
            payload = json.loads(path.read_text())
            payload["fit"]["status"] = 1
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(MODULE.ValidationError, "failed fit quality"):
                self.run_validator(matrix, root, directory / "report.json")

            payload["fit"]["status"] = 0
            payload["r"]["value"] = float("nan")
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(MODULE.ValidationError, "not finite"):
                self.run_validator(matrix, root, directory / "report.json")

    def test_rejects_fixed_or_boundary_limited_nonzero_r(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            matrix, root = self.make_campaign(directory)
            path = root / "w1" / "m1000" / "one" / "fit_zero.json"
            payload = json.loads(path.read_text())
            payload["r"]["constant"] = True
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(MODULE.ValidationError, "r floated"):
                self.run_validator(matrix, root, directory / "fixed.json")

            payload["r"]["constant"] = False
            payload["r"]["boundary"]["near_min"] = True
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(MODULE.ValidationError, "near its lower bound"):
                self.run_validator(matrix, root, directory / "boundary.json")


if __name__ == "__main__":
    unittest.main()
