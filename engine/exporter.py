"""Экспорт готовых уникализированных отзывов в формате SQL и HTML."""
import html

def escape_sql(val):
    if val is None:
        return "NULL"
    s = str(val)
    s = s.replace("\\", "\\\\").replace("'", "''")
    return f"'{s}'"

def build_sql_dump(company_id, rewritten_reviews, status_moderation=1):
    """
    Генерирует готовый чистый SQL-файл для вставки в таблицу wp_reviews.
    company_id: int ID компании в WordPress
    rewritten_reviews: list словарей (author_name, rate, title, text, pluses, minuses, date_added)
    status_moderation: 1 (опубликован) или 0 (на модерации)
    """
    if not company_id:
        raise ValueError("Не указан ID компании (company_id)")

    sql_lines = [
        "-- OtzyvTut Review Studio: Пакет импорта уникализированных отзывов",
        f"-- ID компании: {company_id}, количество: {len(rewritten_reviews)}",
        "INSERT INTO `wp_reviews` (`company_id`, `author_name`, `author_id`, `review_rate`, `review_title`, `review_text`, `review_pluses`, `review_minuses`, `review_parent_id`, `is_representative_of_company`, `is_hidden`, `is_spam`, `status_moderation`, `date_added`) VALUES"
    ]

    values = []
    for r in rewritten_reviews:
        author = escape_sql(r.get("author_name", "Клиент"))
        rate = int(r.get("rate") or 5)
        title = escape_sql(r.get("title", "Отзыв"))
        text = escape_sql(r.get("text", ""))
        plus = escape_sql(r.get("pluses", ""))
        minus = escape_sql(r.get("minuses", ""))
        date_add = escape_sql(r.get("date_added", "2026-10-21 12:00:00"))
        mod = int(status_moderation)

        row = f"({company_id}, {author}, 0, {rate}, {title}, {text}, {plus}, {minus}, 0, 0, 0, 0, {mod}, {date_add})"
        values.append(row)

    if not values:
        return "-- Список отзывов пуст."

    sql_body = ",\n".join(values) + ";"
    sql_lines.append(sql_body)
    return "\n".join(sql_lines)
