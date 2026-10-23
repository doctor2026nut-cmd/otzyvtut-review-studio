"""SEO-оптимизированный модуль рерайта отзывов и вакансий через antigravity-3.8-pro.
Формирует уникальный текст от первого лица, заголовок, структурированные
плюсы и минусы, реалистичное имя автора и органический разброс дат.
"""
import re, json, random
from datetime import datetime, timedelta
from .llm import call_llm

SYSTEM_PROMPT = """
Ты — профессиональный редактор пользовательского контента для независимого сайта отзывов OtzyvTut.com.
Твоя задача — взять реальный отзыв о компании или описание условий работы/вакансии из открытых источников и сделать глубокий, 100% уникальный SEO-рерайт от первого лица.

КРИТИЧЕСКИЕ ТРЕБОВАНИЯ:
1. 100% УНИКАЛЬНОСТЬ: Не копировать фразы из оригинала. Перефразируй суть, сохраняя реальные факты ситуации (сроки, суммы, обращение в поддержку, поведение менеджеров, реальные условия труда, задержки выплат).
2. ЖИВОЙ ЯЗЫК: Текст должен звучать естественно, как реальный клиент или соискатель (живой человек со своими эмоциями: легкое недовольство, сдержанная радость, конструктив). Без канцеляризмов и шаблонных фраз.
3. ЧЕТКАЯ СТРУКТУРА:
   - title: Цепкий релевантный заголовок (3-7 слов), отражающий суть отзыва.
   - text: Основной текст отзыва (от 250 до 600 символов, 3-5 предложений).
   - pluses: 1-2 кратких плюса (если отзыв сугубо негативный, напиши 'Не обнаружил' или минимальный факт, например 'Быстрый ответ').
   - minuses: 1-2 кратких минуса (если отзыв сугубо позитивный, напиши 'Не заметил' или мелкий нюанс, например 'Пришлось немного подождать').
   - author_name: Реалистичное славянское имя автора (например: Максим В., Елена, Артем Смирнов, Дмитро, Наталья).
   - rate: Оценка (число от 1 до 5), соответствующая тону отзыва.

ОТВЕТ ДОЛЖЕН БЫТЬ ТОЛЬКО В ФОРМАТЕ ЧИСТОГО JSON без markdown оберток (без ```json ... ```):
{
  "title": "Заголовок отзыва",
  "text": "Текст отзыва...",
  "pluses": "Плюсы через запятую",
  "minuses": "Минусы через запятую",
  "author_name": "Имя Автора",
  "rate": 1
}
"""

def generate_safe_date(index_offset=0, max_days_back=120):
    """Генерирует естественную дату в прошлом с разбросом (чтобы не было спам-всплеска)."""
    base_date = datetime.now()
    days_back = random.randint(3, 10) + (index_offset * random.randint(4, 12))
    days_back = min(days_back, max_days_back)
    review_dt = base_date - timedelta(days=days_back, hours=random.randint(1, 23), minutes=random.randint(1, 59))
    return review_dt.strftime("%Y-%m-%d %H:%M:%S")

def rewrite_review(raw_review, tone_filter="negative_only", index_offset=0):
    """
    raw_review: dict со свойствами (text, rate, author, source, date)
    tone_filter: 'all', 'positive_only', 'negative_only', 'neutral_only'
    """
    orig_text = raw_review.get("text") or ""
    orig_rate = raw_review.get("rating") or raw_review.get("rate") or 1
    orig_author = raw_review.get("author") or "Клиент"

    target_instruction = ""
    if tone_filter == "negative_only":
        target_instruction = "Сделай отзыв строго критическим/негативным (оценка 1 или 2), с четким акцентом на претензии, невыполнение условий и обман со стороны компании."
    elif tone_filter == "positive_only":
        target_instruction = "Сделай отзыв положительным (оценка 4 или 5), с акцентом на качественный сервис."
    elif tone_filter == "neutral_only":
        target_instruction = "Сделай отзыв взвешенным (оценка 3), где есть как плюсы, так и очевидные минусы."

    prompt = f"""
Исходный отзыв/факт с внешней площадки ({raw_review.get('source', 'интернет')}):
Автор: {orig_author}
Оценка: {orig_rate}
Текст:
{orig_text}

{target_instruction}

Сделай глубокий рерайт по правилам и верни ТОЛЬКО JSON.
"""

    raw_out = call_llm(prompt, system_instruction=SYSTEM_PROMPT, temperature=0.7)

    # Очистка от ```json
    raw_out = re.sub(r"^```(?:json)?\s*", "", raw_out)
    raw_out = re.sub(r"\s*```$", "", raw_out).strip()

    try:
        parsed = json.loads(raw_out)
    except Exception:
        m_title = re.search(r'"title":\s*"([^"]+)"', raw_out)
        m_text = re.search(r'"text":\s*"([^"]+)"', raw_out)
        m_plus = re.search(r'"pluses":\s*"([^"]+)"', raw_out)
        m_minus = re.search(r'"minuses":\s*"([^"]+)"', raw_out)
        m_author = re.search(r'"author_name":\s*"([^"]+)"', raw_out)
        m_rate = re.search(r'"rate":\s*(\d+)', raw_out)
        parsed = {
            "title": m_title.group(1) if m_title else "Претензия к компании",
            "text": m_text.group(1) if m_text else orig_text[:300],
            "pluses": m_plus.group(1) if m_plus else "Нет",
            "minuses": m_minus.group(1) if m_minus else "Нарушение условий договора",
            "author_name": m_author.group(1) if m_author else "Игорь С.",
            "rate": int(m_rate.group(1)) if m_rate else 1
        }

    parsed["date_added"] = generate_safe_date(index_offset=index_offset)
    parsed["original_source"] = raw_review.get("source", "web")
    return parsed
