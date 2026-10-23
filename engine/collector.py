"""Сборщик отзывов и проверка компаний по 6 площадкам."""
import sys, os
from . import reviews as base_reviews
from .detector import analyze_reputation_anomalies, check_site_alive

def collect_and_audit(company_name, site_url=None, only_active_2025_2026=False, only_with_anomalies=False):
    """
    1. Ищет и собирает отзывы по компании со всех доступных источников.
    2. Проверяет активность сайта (2025/2026).
    3. Выполняет аудит накруток и разрыва рейтингов.
    4. Фильтрует по критериям (только свежие/активные / только с накрутками).
    """
    raw_data = base_reviews.collect(company_name)
    items = raw_data.get("items", [])
    sources_used = raw_data.get("sources", [])

    # Проверка сайта если передан
    site_alive, site_status = (False, "Не проверялся")
    if site_url:
        site_alive, site_status = check_site_alive(site_url)

    # Аудит аномалий
    audit = analyze_reputation_anomalies(items, sources_used=sources_used)
    audit["site_alive"] = site_alive
    audit["site_status"] = site_status

    # Фильтр 1: Только активные и живые компании (2025-2026)
    if only_active_2025_2026 and not audit["is_active_fresh"] and not site_alive:
        return {
            "skipped": True,
            "reason": "Компания не проявила признаков активности в 2025-2026 годах (отзывы устарели, сайт молчит)",
            "audit": audit,
            "items": []
        }

    # Фильтр 2: Только компании с подозрениями на накрутку / разрывом рейтингов
    if only_with_anomalies and not audit["rating_gap_detected"] and not audit["is_suspicious_perfect"] and len(audit["signals"]) == 0:
        return {
            "skipped": True,
            "reason": "У компании нет подозрительных аномалий или разрыва рейтингов",
            "audit": audit,
            "items": []
        }

    return {
        "skipped": False,
        "company": company_name,
        "summary": raw_data.get("summary", {}),
        "audit": audit,
        "items": items,
        "sources": sources_used
    }
