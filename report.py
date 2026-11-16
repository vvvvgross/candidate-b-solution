"""CLI and local HTTP adapter for the same calculation module."""
import argparse
import json
import mimetypes
import sys
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from accounting import COLUMNS, DataError, build_report, csv_text, load_data, parse_date, serialized

ROOT = Path(__file__).resolve().parent


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, data_dir, **kwargs):
        self.data_dir = data_dir
        super().__init__(*args, **kwargs)

    def respond(self, status, body, content_type, filename=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        request = urlsplit(self.path)
        try:
            if request.path in ("/api/report", "/api/csv"):
                params = parse_qs(request.query)
                as_of = parse_date(params.get("date", [""])[0])
                report = build_report(load_data(self.data_dir), as_of)
                if request.path == "/api/report":
                    self.respond(200, json.dumps(serialized(report), ensure_ascii=False).encode(), "application/json; charset=utf-8")
                else:
                    name = params.get("table", ["works"])[0]
                    if name not in COLUMNS:
                        raise DataError("Неизвестная таблица CSV")
                    self.respond(200, csv_text(report, name).encode("utf-8-sig"), "text/csv; charset=utf-8", f"{name}-{as_of}.csv")
                return
            dist = (ROOT / "frontend" / "dist").resolve()
            target = (dist / ("index.html" if request.path == "/" else request.path.lstrip("/"))).resolve()
            if not target.is_relative_to(dist) or not target.is_file():
                self.respond(404, b"Not found", "text/plain")
                return
            self.respond(200, target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        except DataError as exc:
            self.respond(400, json.dumps({"error": str(exc)}, ensure_ascii=False).encode(), "application/json; charset=utf-8")
        except OSError:
            self.respond(500, b'{"error":"File read failed"}', "application/json")


def main():
    parser = argparse.ArgumentParser(description="Отчёт по авансам и оплате работ")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--date", help="Дата включительно: YYYY-MM-DD")
    parser.add_argument("--out-dir", type=Path, default=Path("output"))
    parser.add_argument("--serve", action="store_true", help="Запустить локальный веб-интерфейс")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        if args.serve:
            load_data(args.data_dir)
            if not (ROOT / "frontend" / "dist" / "index.html").is_file():
                raise DataError("Нет сборки интерфейса. Выполните сборку по README.md")
            server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, data_dir=args.data_dir))
            print(f"Отчёт: http://127.0.0.1:{args.port} | данные: {args.data_dir.resolve()}", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
        else:
            if not args.date:
                parser.error("для CLI нужен --date YYYY-MM-DD")
            report = build_report(load_data(args.data_dir), parse_date(args.date))
            sources = {(args.data_dir / name).resolve() for name in
                       ("contracts.csv", "works.csv", "payments.csv")}
            targets = {(args.out_dir / name).resolve() for name in
                       ("contracts.csv", "works.csv", "allocations.csv", "report.json")}
            if sources & targets:
                raise DataError("Папка результата пересекается с исходными CSV; выберите другую --out-dir")
            args.out_dir.mkdir(parents=True, exist_ok=True)
            for name in COLUMNS:
                (args.out_dir / f"{name}.csv").write_text(csv_text(report, name), encoding="utf-8-sig", newline="")
            (args.out_dir / "report.json").write_text(json.dumps(serialized(report), ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Отчёт на {args.date}: {args.out_dir.resolve()}")
            for warning in report["warnings"]:
                print(f"Внимание: {warning}")
    except (DataError, OSError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
