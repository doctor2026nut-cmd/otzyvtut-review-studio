"""Сбор отзывов о компании из открытых источников — экран мониторинга.
Источники: vidhuk.ua (клиенты и сотрудники, структурированные данные страниц),
minfin.com.ua (страницы компаний и их отзывы), vnutri.org (отзывы сотрудников).
Собранное — аналитика для владельца: что и кто пишет, тональность, темы жалоб,
всплески. Это экран просмотра, а не импорт на сайт."""
import json, re, time, random
from collections import Counter
import requests

from . import parser as parser_mod

UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")}
_session = requests.Session()
_session.headers.update(UA)

def fetch(url, timeout=40):
    try:
        r = _session.get(url, timeout=timeout)
        return r.text if r.status_code == 200 else ""
    except Exception:
        return ""

# ---------- поиск карточки по названию ----------
TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e", "є": "ye",
    "ж": "zh", "з": "z", "и": "y", "і": "i", "ї": "yi", "й": "y", "к": "k", "л": "l",
    "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ь": "",
    "ю": "yu", "я": "ya", "ы": "y", "э": "e", "ё": "e", "ъ": "",
}

def tokens_of(text):
    # разделяем CamelCase: «ШвидкоГроші» -> «Швидко Гроші»
    text = re.sub(r"(?<=[a-zа-яіїєґ])(?=[A-ZА-ЯІЇЄҐ])", " ", (text or ""))
    text = text.lower()
    lat = "".join(TRANSLIT.get(ch, ch) for ch in text)
    return [t for t in re.split(r"[^a-z0-9]+", lat) if len(t) >= 3]

def _slug_score(slug, tokens):
    """Нечёткий скор: транслит источников гуляет (и=i/y, г=h/g), поэтому
    сравниваем токены с частями слага по похожести строк."""
    from difflib import SequenceMatcher
    parts = slug.split("-")
    score = 0.0
    for t in tokens:
        best = max([SequenceMatcher(None, t, p).ratio() for p in parts] + [0])
        if best >= 0.78:
            score += best
    concat = SequenceMatcher(None, "".join(tokens), slug.replace("-", "")).ratio()
    return score + (0.5 if concat >= 0.8 else 0)

def find_vidhuk(query):
    """Лучшая карточка vidhuk по названию компании. Возвращает базовый URL без /otzyvy-*."""
    tokens = tokens_of(query)
    if not tokens:
        return None
    urls = parser_mod.get_sitemap_urls()
    best, best_score = None, 0.0
    for u in urls:
        m = re.match(r"(https://(?:www\.)?vidhuk\.ua/uk/[^/]+)/otzyvy-klientov", u)
        if not m:
            continue
        slug = m.group(1).rsplit("/", 1)[-1]
        sc = _slug_score(slug, tokens)
        if sc > best_score:
            best, best_score = m.group(1), sc
    need = 0.78 * max(1, len(tokens) - 0.5)
    return best if best_score >= need else None

def find_vnutri(query):
    tokens = tokens_of(query)
    if not tokens:
        return None
    best, best_score = None, 0.0
    for sm in ("post-sitemap.xml", "post-sitemap2.xml", "post-sitemap3.xml"):
        xml = fetch(f"https://www.vnutri.org/{sm}")
        for u in re.findall(r"<loc>(https://www\.vnutri\.org/[^<]+)</loc>", xml):
            slug = u.rstrip("/").rsplit("/", 1)[-1]
            sc = _slug_score(slug, tokens)
            if sc > best_score:
                best, best_score = u, sc
    need = 0.78 * max(1, len(tokens) - 0.5)
    return best if best_score >= need else None

# ---------- vidhuk ----------
def _ld_reviews(html):
    for m in re.finditer(r'application/ld\+json">(.*?)</script>', html, re.S):
        try:
            ld = json.loads(m.group(1))
        except Exception:
            continue
        if isinstance(ld, dict) and isinstance(ld.get("review"), list):
            return ld["review"]
    return []

def vidhuk_reviews(base_url, kind, max_pages, progress=None):
    """kind: 'klientov' (клиенты) или 'sotrudnikov' (сотрудники)."""
    out, seen = [], set()
    for page in range(1, max_pages + 1):
        url = f"{base_url}/otzyvy-{kind}" + (f"?page={page}" if page > 1 else "")
        html = fetch(url)
        if not html:
            break
        revs = _ld_reviews(html)
        if not revs:
            break
        new = 0
        for r in revs:
            body = (r.get("reviewBody") or "").strip()
            author = ((r.get("author") or {}).get("name") or "").strip()
            key = (author, body[:80])
            if key in seen:
                continue
            seen.add(key)
            new += 1
            rating = (r.get("reviewRating") or {}).get("ratingValue")
            out.append({
                "source": "vidhuk.ua" + (" (сотрудники)" if kind == "sotrudnikov" else ""),
                "author": author, "rating": float(rating) if rating else None,
                "date": (r.get("datePublished") or "")[:10],
                "title": (r.get("name") or "").strip(), "text": body, "url": url,
            })
        if progress:
            progress(f"vidhuk ({kind}): страница {page}, собрано {len(out)}")
        if new == 0:
            break
        time.sleep(random.uniform(0.8, 1.6))
    return out

# ---------- minfin ----------
def minfin_reviews(company_url, max_pages, progress=None):
    base = company_url.rstrip("/")
    if "/review" not in base:
        base = base + "/review/"
    else:
        base = base + "/"
    first = fetch(base)
    if not first:
        return []
    links = []
    for l in re.findall(r'href="(/ua/company/[^"]+/review/\d+/)"', first):
        if l not in links:
            links.append(l)
    pages = [first]
    for p in range(2, max_pages + 1):
        html = fetch(base + f"?page={p}")
        if not html:
            break
        got = [l for l in re.findall(r'href="(/ua/company/[^"]+/review/\d+/)"', html) if l not in links]
        if not got:
            break
        links += got
        pages.append(html)
        time.sleep(random.uniform(0.6, 1.2))
    out = []
    months = {"січня": "01", "лютого": "02", "березня": "03", "квітня": "04", "травня": "05",
              "червня": "06", "липня": "07", "серпня": "08", "вересня": "09", "жовтня": "10",
              "листопада": "11", "грудня": "12", "января": "01", "февраля": "02", "марта": "03",
              "апреля": "04", "мая": "05", "июня": "06", "июля": "07", "августа": "08",
              "сентября": "09", "октября": "10", "ноября": "11", "декабря": "12"}
    for l in links[:120]:
        html = fetch("https://minfin.com.ua" + l)
        if not html:
            continue
        # точный блок schema.org UserReview, встроенный в страницу отзыва
        i = html.find('"UserReview"')
        seg = html[i:i + 6000] if i >= 0 else ""
        body = author = date = ""
        rating = None
        if seg:
            bm = re.search(r'"reviewBody"\s*:\s*"((?:[^"\\]|\\.)*)"', seg)
            if bm:
                body = bm.group(1).encode().decode("unicode_escape", errors="replace") \
                    if "\\u" in bm.group(1) else bm.group(1)
                body = re.sub(r"\s+", " ", body).strip()
            am = re.search(r'"author"\s*:\s*\{[^}]*"name"\s*:\s*"([^"]{1,60})"', seg)
            author = am.group(1).strip() if am else ""
            dm = re.search(r'"datePublished"\s*:\s*"(\d{1,2})\s+([а-яіїєґ]+)\s+(\d{4})', seg)
            if dm and dm.group(2) in months:
                date = f"{dm.group(3)}-{months[dm.group(2)]}-{int(dm.group(1)):02d}"
            rm = re.search(r'"ratingValue"\s*:\s*"?([\d.]+)', seg)
            if rm:
                rating = float(rm.group(1))
        if not body:  # запасной вариант: самый длинный абзац
            paras = [re.sub(r"<[^>]+>", " ", p).strip() for p in re.findall(r"<p[^>]*>(.*?)</p>", html, re.S)]
            paras = [re.sub(r"\s+", " ", p) for p in paras if len(p) > 60]
            body = max(paras, key=len) if paras else ""
        tm = re.search(r"<h1[^>]*>([^<]{3,140})</h1>", html)
        title = tm.group(1).strip() if tm else ""
        if body:
            out.append({"source": "minfin.com.ua", "author": author, "rating": rating,
                        "date": date, "title": title, "text": body[:1500],
                        "url": "https://minfin.com.ua" + l})
        if progress and len(out) % 10 == 0:
            progress(f"minfin: собрано {len(out)}")
        time.sleep(random.uniform(0.4, 0.9))
    return out

# ---------- vnutri ----------
def vnutri_reviews(company_url, max_pages, progress=None):
    out = []
    for page in range(1, max_pages + 1):
        url = company_url.rstrip("/") + (f"/comment-page-{page}/" if page > 1 else "/")
        html = fetch(url)
        if not html or "commentlist" not in html:
            break
        items = re.findall(r'<li[^>]*class="[^"]*comment[^"]*"[^>]*>(.*?)</li>', html, re.S)
        new = 0
        for it in items:
            am = re.search(r'class="[^"]*comment-author[^"]*"[^>]*>(.*?)</', it, re.S) or \
                 re.search(r"<cite[^>]*>([^<]+)</cite>", it)
            author = re.sub(r"<[^>]+>", "", am.group(1)).strip() if am else ""
            dm = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", it)
            date = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}" if dm else ""
            paras = [re.sub(r"<[^>]+>", " ", p).strip() for p in re.findall(r"<p>(.*?)</p>", it, re.S)]
            body = max([re.sub(r"\s+", " ", p) for p in paras], key=len) if paras else ""
            if body and len(body) > 15:
                out.append({"source": "vnutri.org (сотрудники)", "author": author,
                            "rating": None, "date": date, "title": "", "text": body[:1500], "url": url})
                new += 1
        if progress:
            progress(f"vnutri: страница {page}, собрано {len(out)}")
        if new == 0:
            break
        time.sleep(random.uniform(0.8, 1.4))
    return out

MONTHS_UA = {"січня": "01", "лютого": "02", "березня": "03", "квітня": "04", "травня": "05",
             "червня": "06", "липня": "07", "серпня": "08", "вересня": "09", "жовтня": "10",
             "листопада": "11", "грудня": "12", "января": "01", "февраля": "02", "марта": "03",
             "апреля": "04", "мая": "05", "июня": "06", "июля": "07", "августа": "08",
             "сентября": "09", "октября": "10", "ноября": "11", "декабря": "12"}

def _clean(html_frag):
    import html as _h
    t = re.sub(r"<[^>]+>", " ", html_frag or "")
    return re.sub(r"\s+", " ", _h.unescape(t)).strip()

# ---------- moshennik.eu ----------
def moshennik_reviews(company_url, max_pages=1, progress=None):
    html = fetch(company_url)
    if not html:
        return []
    out = []
    for block in re.split(r'<div id="[^"]+" class="comment">', html)[1:]:
        am = re.search(r'class="author">(.*?)</div>', block, re.S)
        author = _clean(am.group(1)) if am else ""
        dm = re.search(r'class="date">\s*/\s*(\d{2})\.(\d{2})\.(\d{4})', block)
        date = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}" if dm else ""
        bm = re.search(r'class="description wrap">(.*?)</div>', block, re.S)
        body = _clean(bm.group(1)) if bm else ""
        # отметка автора: «против» (мошенник) или «за»
        rating = None
        if 'alt="против"' in block:
            rating = 1.0
        elif 'alt="за"' in block:
            rating = 5.0
        if body:
            out.append({"source": "moshennik.eu", "author": author, "rating": rating,
                        "date": date, "title": "", "text": body[:1500], "url": company_url})
    if progress:
        progress(f"moshennik: собрано {len(out)}")
    return out

def find_moshennik(query):
    """Поиск карточек по названию через собственный поиск сайта. До 2 лучших совпадений."""
    import urllib.parse
    html = fetch("https://moshennik.eu/?query=" + urllib.parse.quote(query))
    if not html:
        return []
    tokens = set(tokens_of(query))
    scored = []
    seen = set()
    for href, inner in re.findall(r'href="([^"]*company\.php\?name=[^"]+)"[^>]*>(.*?)</a>', html, re.S):
        url = href if href.startswith("http") else "https://moshennik.eu" + ("" if href.startswith("/") else "/") + href
        if url in seen:
            continue
        seen.add(url)
        slug = url.rsplit("=", 1)[-1]
        t = set(tokens_of(slug)) | set(tokens_of(_clean(inner)))
        score = len(tokens & t)
        if score:
            scored.append((score, url))
    scored.sort(key=lambda x: -x[0])
    return [u for _, u in scored[:2]]

# ---------- DOU (jobs.dou.ua) ----------
def dou_reviews(company_url, max_pages=1, progress=None):
    html = fetch(company_url)
    if not html:
        return []
    out = []
    for block in re.findall(r'<div class="b-comment[^"]*">(.*?)(?=<div class="b-comment|\Z)', html, re.S):
        am = re.search(r'class="avatar"[^>]*>\s*<div class="g-avatar"[^>]*>\s*<img[^>]*title="([^"]+)"', block) or \
             re.search(r'<a class="avatar"[^>]*>([^<]{2,60})</a>', block)
        author = am.group(1).strip() if am else ""
        dm = re.search(r'class="comment-link"[^>]*>(\d{1,2})\s+([а-яіїєґ]+)\s+(\d{4})', block)
        date = ""
        if dm and dm.group(2) in MONTHS_UA:
            date = f"{dm.group(3)}-{MONTHS_UA[dm.group(2)]}-{int(dm.group(1)):02d}"
        tm = re.search(r'<div class="l-text b-typo">(.*?)</div>', block, re.S)
        body = _clean(tm.group(1)) if tm else ""
        if body and len(body) > 20:
            out.append({"source": "dou.ua (сотрудники)", "author": author, "rating": None,
                        "date": date, "title": "", "text": body[:1500], "url": company_url})
    if progress:
        progress(f"dou: собрано {len(out)}")
    return out

def find_dou(query):
    tokens = tokens_of(query)
    if not tokens:
        return None
    xml = fetch("https://jobs.dou.ua/sitemap.xml")
    urls = re.findall(r"<loc>(https://jobs\.dou\.ua/companies/[^/<]+/)</loc>", xml)
    best, best_score = None, 0.0
    for u in urls:
        slug = u.rstrip("/").rsplit("/", 1)[-1]
        sc = _slug_score(slug, tokens)
        if sc > best_score:
            best, best_score = u, sc
    need = 0.78 * max(1, len(tokens) - 0.5)
    return (best + "reviews/") if best and best_score >= need else None

# ---------- otzovik.com ----------
def otzovik_reviews(company_url, max_pages=1, progress=None):
    html = fetch(company_url)
    if not html:
        return []
    out = []
    items = re.findall(r'itemprop="review".*?(?=itemprop="review"|\Z)', html, re.S)
    for it in items[:30]:
        am = re.search(r'itemprop="name">([^<]{2,60})<', it)
        author = am.group(1).strip() if am else ""
        rm = re.search(r'rating-score[^>]*title="[^"]*:\s*([\d.]+)"', it)
        rating = float(rm.group(1)) if rm else None
        dm = re.search(r'itemprop="datePublished"[^>]*content="(\d{4}-\d{2}-\d{2})"', it) or \
             re.search(r'(\d{4}-\d{2}-\d{2})[T ]', it)
        date = dm.group(1) if dm else ""
        um = re.search(r'itemprop="url" href="(https://otzovik\.com/review_\d+\.html)"', it)
        tm = re.search(r'class="review-title[^"]*">\s*<a[^>]*>([^<]{3,140})</a>', it) or \
             re.search(r'itemprop="headline"[^>]*>([^<]{3,140})<', it)
        title = tm.group(1).strip() if tm else ""
        bm = re.search(r'itemprop="reviewBody"[^>]*>(.*?)</div>', it, re.S) or \
             re.search(r'class="review-body[^"]*">(.*?)</div>', it, re.S)
        body = _clean(bm.group(1)) if bm else ""
        if not body and um:  # полный текст — на странице отзыва
            page = fetch(um.group(1))
            if page:
                pb = re.search(r'class="review-body[^"]*">(.*?)</div>', page, re.S) or \
                     re.search(r'itemprop="reviewBody"[^>]*>(.*?)</div>', page, re.S)
                body = _clean(pb.group(1)) if pb else ""
                time.sleep(random.uniform(0.4, 0.8))
        if body or title:
            out.append({"source": "otzovik.com", "author": author, "rating": rating,
                        "date": date, "title": title, "text": body[:1500],
                        "url": um.group(1) if um else company_url})
    if progress:
        progress(f"otzovik: собрано {len(out)}")
    return out

# ---------- сбор и сводка ----------
def collect(query, max_pages=5, progress=None):
    """query — название компании или прямая ссылка на её карточку у источника."""
    items, sources_used, note = [], [], ""
    q = (query or "").strip()
    if q.startswith("http"):
        if "vidhuk" in q:
            base = re.sub(r"/otzyvy-\w+.*$", "", q)
            items += vidhuk_reviews(base, "klientov", max_pages, progress)
            items += vidhuk_reviews(base, "sotrudnikov", max_pages, progress)
            sources_used += ["vidhuk.ua"]
        elif "minfin" in q:
            items += minfin_reviews(q, max_pages, progress)
            sources_used += ["minfin.com.ua"]
        elif "vnutri" in q:
            items += vnutri_reviews(q, max_pages, progress)
            sources_used += ["vnutri.org"]
        elif "moshennik" in q:
            items += moshennik_reviews(q, max_pages, progress)
            sources_used += ["moshennik.eu"]
        elif "dou.ua" in q:
            items += dou_reviews(q, max_pages, progress)
            sources_used += ["dou.ua"]
        elif "otzovik" in q:
            items += otzovik_reviews(q, max_pages, progress)
            sources_used += ["otzovik.com"]
        else:
            raise ValueError("Ссылка не похожа на известный источник (vidhuk.ua, minfin.com.ua, vnutri.org, moshennik.eu, dou.ua, otzovik.com)")
    else:
        base = find_vidhuk(q)
        if base:
            items += vidhuk_reviews(base, "klientov", max_pages, progress)
            items += vidhuk_reviews(base, "sotrudnikov", 2, progress)
            sources_used.append("vidhuk.ua")
        vn = find_vnutri(q)
        if vn:
            items += vnutri_reviews(vn, 3, progress)
            sources_used.append("vnutri.org")
        for murl in find_moshennik(q):
            items += moshennik_reviews(murl, 1, progress)
            if "moshennik.eu" not in sources_used:
                sources_used.append("moshennik.eu")
        du = find_dou(q)
        if du:
            items += dou_reviews(du, 1, progress)
            sources_used.append("dou.ua")
        if not items:
            note = ("По названию ничего не нашлось. Для Minfin, Otzovik и точного результата вставь прямую ссылку "
                    "на карточку компании на источнике.")
    items.sort(key=lambda r: r.get("date") or "", reverse=True)
    return {"query": q, "items": items[:500], "sources": sources_used, "note": note,
            "summary": summarize(items)}

STOP = set("""і в не на у та що це як з до за по для від про при без більш дуже коли його її їх ми ви він вона вони
и в не на у что это как с к по для от про при без более очень когда его её их мы вы он она они
the a an and or of to in is are was were with for on at by it this that""".split())

SOURCE_TIERS = {
    "moshennik.eu": ("Строгая", "чёрный список мошенников, модерация жалоб"),
    "dou.ua (сотрудники)": ("Строгая", "отзывы только с подтверждённых аккаунтов специалистов"),
    "minfin.com.ua": ("Средняя", "модерация, отзывы привязаны к банковским продуктам"),
    "vidhuk.ua": ("Мягкая", "открытая публикация"),
    "vnutri.org": ("Мягкая", "открытые комментарии сотрудников"),
    "otzovik.com": ("Мягкая", "отзывы открыто продаются на биржах"),
}
SOFT_SOURCES = {s for s, (t, _) in SOURCE_TIERS.items() if t == "Мягкая"}

def gap_detector(items):
    """Разрыв рейтингов между площадками разной строгости: мягкие площадки, где отзывы
    покупаются, против модерируемых и чёрного списка. Внутренний сигнал, не обвинение."""
    per = {}
    for i in items:
        src = i["source"]
        d = per.setdefault(src, {"source": src, "tier": SOURCE_TIERS.get(src, ("?", ""))[0],
                                 "tier_note": SOURCE_TIERS.get(src, ("?", ""))[1],
                                 "count": 0, "rated": 0, "sum": 0.0, "against": 0})
        d["count"] += 1
        if i.get("rating"):
            d["rated"] += 1
            d["sum"] += i["rating"]
            if src == "moshennik.eu" and i["rating"] <= 2:
                d["against"] += 1
    detail = []
    for d in per.values():
        d = dict(d)
        d["avg"] = round(d["sum"] / d["rated"], 2) if d["rated"] else None
        d.pop("sum")
        detail.append(d)
    detail.sort(key=lambda x: -x["count"])

    def wavg(pred):
        rs = [i for i in items if i.get("rating") and pred(i["source"])]
        return (round(sum(i["rating"] for i in rs) / len(rs), 2), len(rs)) if rs else (None, 0)

    soft_avg, soft_n = wavg(lambda s: s in SOFT_SOURCES)
    med_avg, med_n = wavg(lambda s: s == "minfin.com.ua")
    mosh = per.get("moshennik.eu", {})
    mosh_rated = mosh.get("rated", 0)
    against_share = round(mosh.get("against", 0) / mosh_rated, 2) if mosh_rated else None

    signals, level = [], "none"
    if soft_avg is not None and med_avg is not None and soft_n >= 5 and med_n >= 5:
        gap = round(soft_avg - med_avg, 2)
        if gap >= 1.2:
            signals.append(f"Мягкие площадки дают в среднем {soft_avg}, модерируемый Minfin — {med_avg}: разрыв {gap}.")
            level = "strong" if gap >= 1.8 else "notice"
    else:
        gap = None
    if against_share is not None and mosh_rated >= 4 and against_share >= 0.7 and soft_avg is not None and soft_avg >= 4.2:
        signals.append(f"На moshennik.eu {mosh.get('against', 0)} из {mosh_rated} отметок — «мошенник» ({round(against_share * 100)}%), а на мягких площадках средний рейтинг {soft_avg}.")
        level = "strong"
    if soft_avg is not None and soft_avg >= 4.8 and soft_n >= 20 and ((med_avg is not None and med_avg <= 3.5) or (against_share is not None and against_share >= 0.5)):
        signals.append(f"На мягких площадках почти идеальная картинка: {soft_avg} по {soft_n} отзывам, а на строгих источниках заметно хуже.")
        level = "strong"
    titles = {"strong": "СИЛЬНЫЙ СИГНАЛ РАЗРЫВА: репутация на мягких площадках сильно лучше, чем на строгих",
              "notice": "Заметный разрыв рейтингов между площадками",
              "none": "Разрыва рейтингов между площадками не видно"}
    return {"level": level, "title": titles[level], "signals": signals,
            "gap_soft_vs_medium": gap, "per_source": detail}

def summarize(items):
    rated = [i for i in items if i.get("rating")]
    neg = [i for i in items if i.get("rating") and i["rating"] <= 2]
    pos = [i for i in items if i.get("rating") and i["rating"] >= 4]
    by_source = Counter(i["source"] for i in items)
    by_day = Counter(i["date"] for i in items if i.get("date"))
    bursts = by_day.most_common(3)
    words = Counter()
    for i in neg:
        for w in re.findall(r"[a-zа-яіїєґ]{4,}", (i.get("text") or "").lower()):
            if w not in STOP:
                words[w] += 1
    norm = Counter(re.sub(r"\s+", " ", (i.get("text") or "").lower())[:120] for i in items)
    dupes = sum(c - 1 for c in norm.values() if c > 1)
    return {
        "total": len(items),
        "avg_rating": round(sum(i["rating"] for i in rated) / len(rated), 2) if rated else None,
        "negative": len(neg), "positive": len(pos),
        "neg_share": round(100 * len(neg) / len(rated)) if rated else None,
        "by_source": dict(by_source),
        "burst_days": [{"date": d, "count": c} for d, c in bursts if c >= 3],
        "top_complaint_words": [w for w, _ in words.most_common(12)],
        "duplicate_texts": dupes,
        "gap_detector": gap_detector(items),
    }
