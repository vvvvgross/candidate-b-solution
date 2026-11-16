import csv
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def run_cli(self, cwd, *args):
        return subprocess.run([sys.executable, str(ROOT / "report.py"), *args],
                              cwd=cwd, capture_output=True, text=True)

    def test_run_from_another_directory_and_csv_matches_json(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.run_cli(folder, "--date", "2026-11-10")
            self.assertEqual(result.returncode, 0, result.stderr)
            output = Path(folder) / "output"
            report = json.loads((output / "report.json").read_text())
            for table in ("works", "contracts", "allocations"):
                with (output / f"{table}.csv").open(encoding="utf-8-sig", newline="") as stream:
                    self.assertEqual(list(csv.DictReader(stream)), report[table])
            self.assertEqual([r["net_paid"] for r in report["contracts"]], ["315000.00", "75000.00"])
            self.assertEqual([r["paid"] for r in report["works"]],
                             ["100000.00", "100000.00", "0.00", "100000.00", "0.00", "0.00", "20000.00", "30000.00", "0.00"])

    def test_invalid_date_and_missing_date_do_not_create_output(self):
        with tempfile.TemporaryDirectory() as folder:
            for args in ((), ("--date", "2026-02-30")):
                result = self.run_cli(folder, *args)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(result.stderr)
                self.assertFalse((Path(folder) / "output").exists())

    def test_output_cannot_overwrite_input(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder) / "data"
            shutil.copytree(ROOT / "data", data)
            original = {p.name: p.read_bytes() for p in data.iterdir()}
            result = self.run_cli(folder, "--date", "2026-11-10", "--data-dir", str(data), "--out-dir", str(data))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("исходными CSV", result.stderr)
            self.assertEqual(original, {p.name: p.read_bytes() for p in data.iterdir()})


if __name__ == "__main__":
    unittest.main()
