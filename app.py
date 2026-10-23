#!/usr/bin/env python3
"""OtzyvTut Review Studio — Автоматическая станция пакетного сбора, SEO-рерайта и публикации.
Powered by antigravity-3.8-pro via Agent-Master OpenAI-compatible endpoint.
"""
import os, sys, json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from engine import collector, rewriter, exporter, autofinder, batch_runner, llm

PORT = 8795
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

def get_settings():
    return {
        "api_base": llm.DEFAULT_API_BASE,
        "api_key": llm.DEFAULT_API_KEY,
        "model": llm.DEFAULT_MODEL,
        "default_tone": "negative_only"
    }

STATE = {
    "audit": {},
    "raw_reviews": [],
    "rewritten_reviews": [],
    "company_name": "",
    "company_id": "",
    "last_sql": "",
    "batch_report": {}
}

class StudioHandler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            ui_path = os.path.join(BASE_DIR, "ui.html")
            with open(ui_path, "r", encoding="utf-8") as f:
                content = f.read().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        elif self.path == "/api/state":
            self._json({
                "settings": get_settings(),
                "state": STATE
            })
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        body = self._body()

        # АВТОПОИСК ВАРИАНТОВ
        if self.path == "/api/autofind":
            niche = body.get("niche") or "all"
            only_active = bool(body.get("only_active", True))
            only_anomalies = bool(body.get("only_anomalies", True))
            limit = int(body.get("limit") or 25)

            results = autofinder.get_ranked_candidates(
                niche=niche,
                only_active=only_active,
                only_anomalies=only_anomalies,
                limit=limit
            )
            self._json({"ok": True, "candidates": results})

        # АНАЛИЗ И СБОР ПО ОДНОЙ КОМПАНИИ
        elif self.path == "/api/analyze_company":
            name = (body.get("company_name") or "").strip()
            site = (body.get("site_url") or "").strip()
            cid = body.get("company_id")

            if not name:
                self._json({"error": "Название компании не передано"}, 400)
                return

            res = collector.collect_and_audit(name, site)
            STATE["company_name"] = name
            STATE["company_id"] = str(cid) if cid else ""
            STATE["audit"] = res.get("audit", {})
            STATE["raw_reviews"] = res.get("items", [])
            STATE["rewritten_reviews"] = []
            STATE["last_sql"] = ""

            self._json({
                "ok": True,
                "audit": res.get("audit"),
                "total": len(res.get("items", [])),
                "reviews": res.get("items", [])[:100]
            })

        # РЕРАЙТ ВЫБРАННЫХ ОТЗЫВОВ ОДНОЙ КОМПАНИИ
        elif self.path == "/api/rewrite":
            selected_ids = body.get("selected_indices") or []
            tone_filter = body.get("tone_filter") or "negative_only"
            target_company_id = body.get("company_id") or STATE.get("company_id")

            raw_list = STATE.get("raw_reviews", [])
            to_process = []
            for idx in selected_ids:
                if 0 <= idx < len(raw_list):
                    to_process.append(raw_list[idx])

            if not to_process:
                to_process = raw_list[:5]

            results = []
            for i, r in enumerate(to_process):
                try:
                    rewritten = rewriter.rewrite_review(
                        raw_review=r,
                        tone_filter=tone_filter,
                        index_offset=i
                    )
                    results.append(rewritten)
                except Exception as e:
                    print("Error rewriting review:", e)

            STATE["rewritten_reviews"] = results
            STATE["company_id"] = str(target_company_id) if target_company_id else ""

            if target_company_id:
                try:
                    cid = int(target_company_id)
                    STATE["last_sql"] = exporter.build_sql_dump(cid, results)
                except Exception:
                    pass

            self._json({
                "ok": True,
                "rewritten": results,
                "sql": STATE.get("last_sql", "")
            })

        # ПАКЕТНЫЙ АВТО-ПРОГОН ПО НЕСКОЛЬКИМ КОМПАНИЯМ
        elif self.path == "/api/batch_run":
            companies = body.get("companies") or []
            tone = body.get("tone_filter") or "negative_only"
            count_per = int(body.get("reviews_per_company") or 4)

            if not companies:
                self._json({"error": "Выберите хотя бы одну компанию для пачки"}, 400)
                return

            report = batch_runner.process_batch(
                company_names_or_candidates=companies,
                tone_filter=tone,
                reviews_per_company=count_per
            )
            STATE["batch_report"] = report
            STATE["last_sql"] = report.get("combined_sql", "")
            self._json({"ok": True, "report": report})

        else:
            self.send_response(404)
            self.end_headers()

def run():
    print(f"=== OtzyvTut Review Studio (Default LLM: {llm.DEFAULT_MODEL}) ===")
    print(f"Сервер слушает на http://127.0.0.1:{PORT}")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), StudioHandler)
    server.serve_forever()

if __name__ == "__main__":
    run()
