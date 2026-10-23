"""Модуль пакетной сквозной обработки:
1. Берет выбранные компании (или автоматически находит активные с накрутками).
2. Спарсивает свежие факты/отзывы/жалобы с доноров.
3. Прогоняет через LLM antigravity-3.8-pro в пакетном режиме с заданной тональностью.
4. Автоматически формирует готовый SQL-пакет публикации для базы wp_reviews с дедупликацией.
"""
import os, sys, json, time
from . import collector, rewriter, exporter, autofinder

def process_batch(company_names_or_candidates, tone_filter="negative_only", reviews_per_company=5, status_moderation=1):
    """
    company_names_or_candidates: список названий или словарей компаний
    tone_filter: 'negative_only', 'positive_only', 'all', 'neutral_only'
    reviews_per_company: сколько отзывов генерировать на компанию (обычно 3-7)
    """
    report = {
        "processed_companies": [],
        "total_reviews_generated": 0,
        "combined_sql": "",
        "items": []
    }

    all_rewritten = []
    sql_blocks = []

    for item in company_names_or_candidates:
        if isinstance(item, dict):
            name = item.get("name")
            site = item.get("site", "")
            cid = item.get("company_id")
        else:
            name = str(item).strip()
            site = ""
            cid = None

        if not name:
            continue

        print(f"[Batch] Сбор и аудит компании: {name}...")
        col_res = collector.collect_and_audit(name, site_url=site)
        raw_items = col_res.get("items", [])

        # Если отзывов на донорах нет или мало, но компания целевая, отбираем факты
        if not raw_items:
            print(f"[Batch] Нет прямых отзывов по {name}, пропускаем.")
            continue

        # Фильтруем оригиналы под тональность
        if tone_filter == "negative_only":
            candidates_raw = [r for r in raw_items if (r.get("rating") or r.get("rate") or 0) in (1.0, 2.0)]
            if not candidates_raw:
                # Берем любые с жестких площадок или первые для рерайта в критическом ключе
                candidates_raw = raw_items[:reviews_per_company]
            else:
                candidates_raw = candidates_raw[:reviews_per_company]
        else:
            candidates_raw = raw_items[:reviews_per_company]

        company_rewritten = []
        for i, raw_rev in enumerate(candidates_raw):
            try:
                res = rewriter.rewrite_review(raw_rev, tone_filter=tone_filter, index_offset=i)
                company_rewritten.append(res)
                all_rewritten.append({**res, "company_name": name, "company_id": cid})
            except Exception as e:
                print(f"[Batch] Ошибка рерайта отзыва для {name}: {e}")

        if company_rewritten:
            # Если есть ID, генерируем SQL
            target_id = cid or 302 # fallback
            sql_chunk = exporter.build_sql_dump(target_id, company_rewritten, status_moderation=status_moderation)
            sql_blocks.append(sql_chunk)

        report["processed_companies"].append({
            "company": name,
            "company_id": cid,
            "collected": len(raw_items),
            "generated": len(company_rewritten)
        })

    report["total_reviews_generated"] = len(all_rewritten)
    report["items"] = all_rewritten
    report["combined_sql"] = "\n\n".join(sql_blocks)
    return report
