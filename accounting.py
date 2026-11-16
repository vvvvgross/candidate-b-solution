"""Pure report calculation. All monetary values are integer kopecks."""
import csv
import io
import re
from datetime import date
from pathlib import Path


class DataError(ValueError):
    pass


SCHEMAS = {
    "contracts": "contract_id contractor amount signed_at".split(),
    "works": "work_id contract_id title price status completed_at cancelled_at".split(),
    "payments": "payment_id contract_id work_id purpose amount status created_at paid_at refunded_at".split(),
}


def parse_date(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise DataError(f"Неверная дата: {value!r}; ожидается YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DataError(f"Неверная дата: {value!r}") from exc


def cents(value):
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", value):
        raise DataError(f"Неверная сумма: {value!r}; нужны неотрицательные рубли, до 2 знаков")
    rubles, _, fraction = value.partition(".")
    return int(rubles) * 100 + int(fraction.ljust(2, "0"))


def money(value):
    sign = "-" if value < 0 else ""
    return f"{sign}{abs(value) // 100}.{abs(value) % 100:02d}"


def load_data(folder):
    result = {}
    for name, fields in SCHEMAS.items():
        path = Path(folder) / f"{name}.csv"
        rows = []
        seen = set()
        try:
            with path.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream, strict=True)
                if reader.fieldnames != fields:
                    raise DataError(f"{path.name}: ожидаются колонки {', '.join(fields)}")
                for row in reader:
                    location = f"{path.name}, строка {reader.line_num}"
                    try:
                        if None in row or any(v is None for v in row.values()):
                            raise DataError("число значений не совпадает с числом колонок")
                        row = {k: v.strip() for k, v in row.items()}
                        key = row[fields[0]]
                        if not key or key in seen:
                            raise DataError(f"пустой или повторный идентификатор {key!r}")
                        seen.add(key)
                        for column in fields:
                            if column in ("amount", "price"):
                                row[column] = cents(row[column])
                            elif column.endswith("_at"):
                                row[column] = parse_date(row[column]) if row[column] else None
                        row["_location"] = location
                        rows.append(row)
                    except DataError as exc:
                        raise DataError(f"{location}: {exc}") from exc
        except (OSError, UnicodeError, csv.Error) as exc:
            raise DataError(f"{path.name}: {exc}") from exc
        result[name] = rows
    validate(result)
    return result


def validate(data):
    contracts = {r["contract_id"]: r for r in data["contracts"]}
    works = {r["work_id"]: r for r in data["works"]}

    def require(condition, row, message):
        if not condition:
            raise DataError(f"{row['_location']}: {message}")

    for row in data["contracts"]:
        require(row["signed_at"] and row["contractor"], row, "нужны дата подписания и подрядчик")
    for row in data["works"]:
        require(row["contract_id"] in contracts, row, "неизвестный договор")
        require(row["title"], row, "пустое название работы")
        status = row["status"]
        require(status in ("done", "planned", "cancelled"), row, "неизвестный статус работы")
        require(bool(row["completed_at"]) == (status == "done"), row, "статус не согласуется с completed_at")
        require(bool(row["cancelled_at"]) == (status == "cancelled"), row, "статус не согласуется с cancelled_at")
        for key in ("completed_at", "cancelled_at"):
            require(not row[key] or row[key] >= contracts[row["contract_id"]]["signed_at"], row, "событие работы раньше договора")
    for row in data["payments"]:
        require(row["contract_id"] in contracts, row, "неизвестный договор")
        if row["work_id"]:
            work = works.get(row["work_id"])
            require(work and work["contract_id"] == row["contract_id"], row, "неизвестная работа или работа другого договора")
        status = row["status"]
        require(status in ("paid", "queued", "refunded"), row, "неизвестный статус платежа")
        require(row["created_at"], row, "нет даты создания платежа")
        require(bool(row["paid_at"]) == (status in ("paid", "refunded")), row, "статус не согласуется с paid_at")
        require(bool(row["refunded_at"]) == (status == "refunded"), row, "статус не согласуется с refunded_at")
        require(row["created_at"] >= contracts[row["contract_id"]]["signed_at"], row, "платёж создан раньше договора")
        require(not row["paid_at"] or row["paid_at"] >= row["created_at"], row, "оплата раньше создания платежа")
        require(not row["refunded_at"] or row["refunded_at"] >= row["paid_at"], row, "возврат раньше оплаты")


def build_report(data, as_of):
    contracts, works, allocations, warnings = [], [], [], []
    for contract in sorted(data["contracts"], key=lambda r: r["contract_id"]):
        if contract["signed_at"] > as_of:
            continue
        cid = contract["contract_id"]
        current = []
        for source in sorted(data["works"], key=lambda r: r["work_id"]):
            if source["contract_id"] != cid:
                continue
            status = "planned"
            if source["completed_at"] and source["completed_at"] <= as_of:
                status = "done"
            if source["cancelled_at"] and source["cancelled_at"] <= as_of:
                status = "cancelled"
            current.append(dict(source, status=status, paid=0))
        by_id = {r["work_id"]: r for r in current}
        payments = sorted((r for r in data["payments"] if r["contract_id"] == cid
                           and r["paid_at"] and r["paid_at"] <= as_of),
                          key=lambda r: (r["paid_at"], r["payment_id"]))
        gross = sum(r["amount"] for r in payments)
        refunded = sum(r["amount"] for r in payments if r["refunded_at"] and r["refunded_at"] <= as_of)
        active = [r for r in payments if not r["refunded_at"] or r["refunded_at"] > as_of]

        def allocate(payment, work_id, amount, kind):
            if amount:
                allocations.append(dict(as_of=as_of.isoformat(), contract_id=cid,
                                        payment_id=payment["payment_id"], work_id=work_id,
                                        kind=kind, amount=amount))

        for payment in active:
            if payment["work_id"]:
                by_id[payment["work_id"]]["paid"] += payment["amount"]
                allocate(payment, payment["work_id"], payment["amount"], "direct")
        eligible = sorted((r for r in current if r["status"] == "done"),
                          key=lambda r: (r["completed_at"], r["work_id"]))
        unallocated = 0
        for payment in active:
            if payment["work_id"]:
                continue
            rest = payment["amount"]
            for work in eligible:
                assigned = min(rest, max(work["price"] - work["paid"], 0))
                work["paid"] += assigned
                rest -= assigned
                allocate(payment, work["work_id"], assigned, "allocated")
            unallocated += rest
            allocate(payment, "", rest, "unallocated")
        for work in current:
            effective = 0 if work["status"] == "cancelled" else work["price"]
            work["remaining"] = max(effective - work["paid"], 0)
            work["excess"] = max(work["paid"] - effective, 0)
            if work["excess"]:
                warnings.append(f"{cid} / {work['work_id']}: целевая переплата или платёж на отменённую работу {money(work['excess'])} ₽; не перераспределён.")
            works.append({k: work[k] for k in ("contract_id", "work_id", "title", "status", "price", "paid", "remaining", "excess")} | {"as_of": as_of.isoformat()})
        effective = sum(r["price"] for r in current if r["status"] != "cancelled")
        remaining = sum(r["remaining"] for r in current)
        discrepancy = contract["amount"] - effective
        if discrepancy:
            warnings.append(f"{cid}: сумма договора отличается от стоимости действующих работ на {money(discrepancy)} ₽. Подтвердите состав работ и сумму договора.")
        contracts.append(dict(as_of=as_of.isoformat(), contract_id=cid, contractor=contract["contractor"],
                              amount=contract["amount"], active_price=effective, discrepancy=discrepancy,
                              gross_paid=gross, refunded=refunded, net_paid=gross-refunded,
                              work_paid=sum(r["paid"] for r in current), unallocated=unallocated,
                              remaining=remaining, funding_needed=max(remaining-unallocated, 0),
                              excess=sum(r["excess"] for r in current),
                              contract_balance=contract["amount"]-(gross-refunded)))
    return dict(as_of=as_of.isoformat(), contracts=contracts, works=works, allocations=allocations, warnings=warnings)


MONEY_FIELDS = set("price paid remaining excess amount active_price discrepancy gross_paid refunded net_paid work_paid unallocated funding_needed contract_balance".split())
COLUMNS = {
    "works": "as_of contract_id work_id title status price paid remaining excess".split(),
    "contracts": "as_of contract_id contractor amount active_price discrepancy gross_paid refunded net_paid work_paid unallocated remaining funding_needed excess contract_balance".split(),
    "allocations": "as_of contract_id payment_id work_id kind amount".split(),
}


def serialized(report):
    return {**report, **{name: [{k: money(v) if k in MONEY_FIELDS else v for k, v in row.items()}
                              for row in report[name]] for name in COLUMNS}}


def csv_text(report, name):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=COLUMNS[name])
    writer.writeheader()
    for row in serialized(report)[name]:
        # Prevent spreadsheet formula execution in source-controlled text fields.
        writer.writerow({k: "'" + v if k not in MONEY_FIELDS and isinstance(v, str)
                         and v.startswith(("=", "+", "-", "@")) else v for k, v in row.items()})
    return stream.getvalue()
