"""Детектор активности и аномалий репутации.
1. Проверка живой активности (свежие отзывы 2025-2026, рабочий сайт).
2. Детектор разрыва рейтингов / накруток (расхождение между мягкими и строгими площадками).
3. Детектор «идеальной репутации» (накрутка: рейтинг 4.9-5.0 при подозрительных паттернах).
"""
import re, time, requests
from datetime import datetime

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

def check_site_alive(url, timeout=7):
    """Проверка доступности и признаков активности сайта (2025-2026)."""
    if not url:
        return False, "Сайт не указан"
    if not url.startswith("http"):
        url = "https://" + url
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout, allow_redirects=True)
        if r.status_code >= 400:
            return False, f"Код {r.status_code}"
        text = r.text
        has_fresh_year = bool(re.search(r"202[56]", text))
        if has_fresh_year:
            return True, "Активен (упоминается 2025/2026)"
        return True, "Доступен (код 200)"
    except Exception as e:
        return False, f"Недоступен ({type(e).__name__})"

def analyze_reputation_anomalies(items, sources_used=None, site_donor_rating=None, site_donor_count=0):
    """
    items: список словарей отзывов (rate, source, date, text, author)
    sources_used: список использованных источников
    """
    report = {
        "is_active_fresh": False,
        "latest_review_date": None,
        "total_collected": len(items or []),
        "is_suspicious_perfect": False,
        "rating_gap_detected": False,
        "gap_details": "",
        "signals": []
    }

    if not items:
        if sources_used:
            report["signals"].append(f"Проверены источники: {', '.join(sources_used)}, но новых отзывов не найдено.")
        return report

    # Группируем по источникам
    by_source = {}
    for r in items:
        src = r.get("source", "other").lower()
        by_source.setdefault(src, []).append(r)

    source_stats = {}
    for src, revs in by_source.items():
        scores = [r.get("rate") for r in revs if r.get("rate") and r.get("rate") > 0]
        avg = sum(scores)/len(scores) if scores else 0
        source_stats[src] = {
            "count": len(revs),
            "avg": round(avg, 2),
            "rated_count": len(scores)
        }

    # 1. Свежесть активности
    dates = []
    for r in items:
        d_str = r.get("date") or ""
        if re.search(r"202[56]", d_str):
            report["is_active_fresh"] = True
        m = re.search(r"(\d{4})[.\-/](\d{2})[.\-/](\d{2})", d_str)
        if m:
            dates.append(m.group(0))

    if dates:
        dates.sort(reverse=True)
        report["latest_review_date"] = dates[0]

    # 2. Детектор идеальной репутации (накрутка)
    if site_donor_rating and site_donor_rating >= 4.8 and site_donor_count >= 15:
        report["is_suspicious_perfect"] = True
        report["signals"].append("Идеальный рейтинг (≥4.8 при ≥15 отзывах) — признак заказных накруток")

    # 3. Разрыв рейтингов между мягкими (vidhuk, otzovik) и жесткими (moshennik, vnutri, minfin, dou)
    soft_scores = []
    hard_scores = []
    for src, st in source_stats.items():
        if any(w in src for w in ("vidhuk", "otzovik")) and st["avg"] > 0:
            soft_scores.append(st["avg"])
        elif any(w in src for w in ("moshennik", "vnutri", "minfin", "dou")) and st["avg"] > 0:
            hard_scores.append(st["avg"])

    if soft_scores and hard_scores:
        avg_soft = sum(soft_scores) / len(soft_scores)
        avg_hard = sum(hard_scores) / len(hard_scores)
        diff = avg_soft - avg_hard
        if diff >= 1.5:
            report["rating_gap_detected"] = True
            report["gap_details"] = f"Разрыв рейтингов {diff:.1f}★: Мягкие площадки {avg_soft:.1f}★ против независимых {avg_hard:.1f}★"
            report["signals"].append(report["gap_details"])

    # Сигнал из moshennik.eu
    for src, st in source_stats.items():
        if "moshennik" in src and st["count"] > 0:
            report["signals"].append(f"Внимание: {st['count']} жалоб в базе moshennik.eu!")

    return report
