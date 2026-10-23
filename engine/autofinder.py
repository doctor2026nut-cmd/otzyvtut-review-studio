"""Модуль автоматического сканирования и ранжирования компаний:
1. Загрузка пулов кандидатов и базы сайта.
2. Проверка свежей активности (2025-2026), накруток (рейтинг ≥4.8 при массе отзывов).
3. Поиск несоответствий/разрыва рейтингов (мягкие vs жесткие площадки).
4. Автоматическая выдача подборки компаний по фильтрам пользователя.
"""
import os, json, re
from .detector import analyze_reputation_anomalies
from . import reviews as base_reviews

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KIT_DIR = os.path.join(BASE_DIR, "OtzyvTut_Parser_Kit")

def get_ranked_candidates(niche="all", only_active=True, only_anomalies=False, min_reviews=5, limit=20):
    """
    Автоматически сканирует базу кандидатов и выявляет лучшие варианты.
    niche: 'all', 'mfo', 'courses', 'invest', 'existing_site'
    """
    candidates = []

    # 1. Загрузка из пулов кандидатов
    pools = []
    if niche in ("all", "mfo"):
        pools.append(("Финансы / МФО", os.path.join(KIT_DIR, "candidates_mfo.jsonl")))
    if niche in ("all", "courses"):
        pools.append(("Курсы / Онлайн-школы", os.path.join(KIT_DIR, "candidates_courses.jsonl")))
    if niche in ("all", "invest"):
        pools.append(("Инвестиции / Крипто", os.path.join(KIT_DIR, "candidates_invest.jsonl")))

    for pool_label, path in pools:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    c = json.loads(line)
                    rev_cnt = int(c.get("reviews") or 0)
                    rating = float(c.get("rating") or 0)
                    views = int(c.get("views") or 0)

                    if rev_cnt < min_reviews:
                        continue

                    is_suspicious_perfect = (rating >= 4.8 and rev_cnt >= 15)

                    if only_anomalies and not is_suspicious_perfect:
                        continue

                    candidates.append({
                        "name": c.get("name"),
                        "niche": pool_label,
                        "rating": rating,
                        "reviews_count": rev_cnt,
                        "views": views,
                        "site": c.get("site", ""),
                        "donor_url": c.get("donor_url", ""),
                        "is_suspicious_perfect": is_suspicious_perfect,
                        "is_existing": False,
                        "company_id": None
                    })
                except Exception:
                    continue

    # 2. Также подтягиваем активные карточки с самого сайта (если интересно наполнить отзывы к ним)
    act_path = os.path.join(KIT_DIR, "docs", "activity_rows.json")
    if niche in ("all", "existing_site") and os.path.exists(act_path):
        with open(act_path, "r", encoding="utf-8") as f:
            rows = json.load(f)
            for r in rows:
                y25 = int(r.get("y2025") or 0)
                y26 = int(r.get("y2026") or 0)
                is_active = (y25 > 0 or y26 > 0)
                neg = int(r.get("neg") or 0)

                if only_active and not is_active:
                    continue
                if only_anomalies and neg == 0:
                    continue

                candidates.append({
                    "name": r.get("title"),
                    "niche": "Карточка на OtzyvTut",
                    "rating": 0,
                    "reviews_count": int(r.get("total") or 0),
                    "views": int(r.get("views") or 0),
                    "site": "",
                    "donor_url": "",
                    "is_suspicious_perfect": False,
                    "is_existing": True,
                    "company_id": r.get("id"),
                    "has_real_negative": neg > 0,
                    "active_years": f"2025: {y25}, 2026: {y26}"
                })

    # Сортируем: сначала подозрительные накрутки и активные компании с высоким числом отзывов/просмотров
    def sort_score(x):
        sc = 0
        if x.get("is_suspicious_perfect"): sc += 5000
        if x.get("has_real_negative"): sc += 3000
        sc += x.get("views", 0) * 2 + x.get("reviews_count", 0) * 10
        return sc

    candidates.sort(key=sort_score, reverse=True)
    return candidates[:limit]
