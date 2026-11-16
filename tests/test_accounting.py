import copy
import csv
import io
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from accounting import DataError, build_report, cents, csv_text, load_data, money, parse_date

ROOT = Path(__file__).resolve().parents[1]


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.data = load_data(ROOT / "data")

    def report(self, day="2026-11-10"):
        return build_report(self.data, parse_date(day))

    def test_control_date(self):
        report = self.report()
        d1, d2 = report["contracts"]
        self.assertEqual((d1["net_paid"], d1["unallocated"], d1["remaining"], d1["funding_needed"]),
                         (31500000, 1500000, 20000000, 18500000))
        self.assertEqual((d2["net_paid"], d2["unallocated"], d2["remaining"], d2["funding_needed"]),
                         (7500000, 2500000, 4000000, 1500000))
        works = {w["work_id"]: w for w in report["works"]}
        self.assertEqual(works["W-14"]["paid"], 10000000)
        self.assertEqual(works["W-13"]["remaining"], 0)
        self.assertEqual(works["W-23"]["status"], "planned")
        self.assertEqual(works["W-23"]["paid"], 0)
        self.assertEqual(d1["discrepancy"], 10000000)

    def test_refund_date_inclusive(self):
        self.assertEqual(self.report("2026-09-09")["contracts"][0]["net_paid"], 35000000)
        self.assertEqual(self.report("2026-09-10")["contracts"][0]["net_paid"], 30000000)

    def test_acceptance_and_future_payment(self):
        report = self.report("2026-11-11")
        self.assertEqual(report["works"][-1]["paid"], 2500000)
        self.assertEqual(report["works"][-1]["remaining"], 1500000)
        report = self.report("2026-11-12")
        self.assertEqual(report["works"][-1]["paid"], 4000000)
        self.assertEqual(report["contracts"][-1]["unallocated"], 500000)

    def test_cancellation_date_inclusive(self):
        before = self.report("2026-10-11")["works"][2]
        after = self.report("2026-10-12")["works"][2]
        self.assertEqual((before["status"], before["remaining"]), ("planned", 10000000))
        self.assertEqual((after["status"], after["remaining"]), ("cancelled", 0))

    def test_direct_payment_before_acceptance(self):
        work = self.report("2026-10-25")["works"][3]
        self.assertEqual((work["status"], work["paid"], work["remaining"]), ("planned", 1500000, 8500000))

    def test_no_signed_contracts(self):
        self.assertEqual(self.report("2026-08-24")["contracts"], [])

    def test_queue_never_counts(self):
        self.assertEqual(self.report("2027-01-01")["contracts"][0]["net_paid"], 31500000)

    def test_cancelled_target_and_overpayment_stay_targeted(self):
        payment = self.data["payments"][2]
        payment["work_id"] = "W-13"
        report = self.report()
        self.assertEqual(report["works"][2]["excess"], 1500000)
        self.assertEqual(report["contracts"][0]["unallocated"], 0)
        self.assertEqual(report["contracts"][0]["funding_needed"], 20000000)
        payment["work_id"] = "W-14"
        payment["amount"] = 12000000
        report = self.report()
        self.assertEqual(report["works"][3]["remaining"], 0)
        self.assertEqual(report["works"][3]["excess"], 2000000)
        self.assertEqual(report["contracts"][0]["unallocated"], 10000000)

    def test_every_day_preserves_every_kopeck(self):
        for offset in range(110):
            report = build_report(self.data, date(2026, 8, 24) + timedelta(days=offset))
            for contract in report["contracts"]:
                self.assertEqual(contract["net_paid"], contract["work_paid"] + contract["unallocated"])
                self.assertEqual(contract["net_paid"], sum(a["amount"] for a in report["allocations"]
                                                         if a["contract_id"] == contract["contract_id"]))

    def test_order_does_not_change_report(self):
        expected = self.report()
        for rows in self.data.values():
            rows.reverse()
        self.assertEqual(expected, self.report())

    def test_small_amounts_and_tie_break(self):
        self.data["contracts"] = [self.data["contracts"][1]]
        self.data["works"] = self.data["works"][-3:]
        for work in self.data["works"]:
            work.update(price=3, completed_at=date(2026, 10, 1))
        payment = copy.deepcopy(self.data["payments"][4])
        payment["amount"] = 5
        self.data["payments"] = [payment]
        self.assertEqual([w["paid"] for w in self.report()["works"]], [3, 2, 0])

    def test_csv_strings_and_escaping(self):
        self.data["contracts"][0]["contractor"] = '=SUM(1,2)'
        rows = list(csv.DictReader(io.StringIO(csv_text(self.report(), "contracts"))))
        self.assertEqual(rows[0]["net_paid"], "315000.00")
        self.assertEqual(rows[0]["contractor"], "'=SUM(1,2)")
        self.assertEqual(rows[1]["contractor"], "Иван Петров, дизайнер")

    def test_validation_has_file_and_line(self):
        with tempfile.TemporaryDirectory() as folder:
            for path in (ROOT / "data").glob("*.csv"):
                (Path(folder) / path.name).write_bytes(path.read_bytes())
            path = Path(folder) / "payments.csv"
            path.write_text(path.read_text().replace("D-1,W-14", "D-2,W-14"))
            with self.assertRaisesRegex(DataError, "payments.csv, строка 4"):
                load_data(folder)

    def test_money_and_date_validation(self):
        self.assertEqual(cents("0.01"), 1)
        self.assertEqual(cents("9007199254740993.01"), 900719925474099301)
        self.assertEqual(money(-1), "-0.01")
        for invalid in ("1.001", "nan", "1e3", "-1", "1,00", ""):
            with self.assertRaises(DataError):
                cents(invalid)
        for invalid in ("2026-2-01", "2026-02-30", "20261110"):
            with self.assertRaises(DataError):
                parse_date(invalid)


if __name__ == "__main__":
    unittest.main()
