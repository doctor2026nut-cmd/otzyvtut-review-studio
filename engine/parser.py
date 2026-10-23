"""Парсер донора vidhuk.ua: факты карточек компаний (название, описание,
рейтинг, число отзывов, просмотры). Тексты чужих отзывов не собираются —
только факты о компании, как сигнал спроса и основа редакционных текстов."""
import json, os, random, re, time
import requests

from . import categories

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITEMAP_CACHE = os.path.join(BASE, "data", "vidhuk_sitemap_organizations.xml")
SITEMAP_INDEX = "https://vidhuk.ua/sitemap.xml"

_session = requests.Session()
_session.headers.update({"User-Agent": UA})

def fetch(url, timeout=40):
    try:
        r = _session.get(url, timeout=timeout)
        return r.text if r.status_code == 200 else ""
    except Exception:
        return ""

def get_sitemap_urls(refresh=False):
    """URL всех карточек организаций донора (кэш в data/, чтобы не дёргать донора лишний раз)."""
    if not refresh and os.path.exists(SITEMAP_CACHE):
        xml = open(SITEMAP_CACHE, encoding="utf-8", errors="replace").read()
    else:
        xml = ""
        idx = fetch(SITEMAP_INDEX)
        subs = re.findall(r"<loc>([^<]*organizations[^<]*)</loc>", idx)
        parts = []
        for s in subs:
            parts.append(fetch(s))
            time.sleep(0.5)
        xml = "\n".join(parts) if parts else idx
        if "<urlset" in xml or "<sitemapindex" in xml:
            os.makedirs(os.path.dirname(SITEMAP_CACHE), exist_ok=True)
            with open(SITEMAP_CACHE, "w", encoding="utf-8") as f:
                f.write(xml)
    return re.findall(r"<loc>(https://(?:www\.)?vidhuk\.ua/[^<]+)</loc>", xml)

def descr_block_text(html, name):
    i = html.find('id="descr"')
    if i < 0:
        return ""
    seg = html[i:i + 9000]
    txt = re.sub(r"<[^>]+>", " ", seg)
    for a, b in [("&laquo;", "«"), ("&raquo;", "»"), ("&ndash;", "–"), ("&#39;", "'"),
                 ("&quot;", '"'), ("&nbsp;", " "), ("&amp;", "&")]:
        txt = txt.replace(a, b)
    txt = re.sub(r"&[a-z#0-9]+;", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    txt = re.split(r"детальніше|Рейтинг\s*[\d.,]+\s*з\s*5", txt)[0].strip()
    txt = re.sub(r'^id="descr"[^>]*>\s*', "", txt)
    if name and txt.lower().startswith(name.lower()):
        txt = txt[len(name):].strip(" -—:").strip()
    txt = re.split(r"\sПерейти на сайт\b", txt)[0].strip()
    return txt

def parse_card(url, html):
    m = re.search(r'application/ld\+json">(.*?)</script>', html, re.S)
    if not m:
        return None
    try:
        ld = json.loads(m.group(1))
    except Exception:
        return None
    if not isinstance(ld, dict) or "name" not in ld:
        return None
    name = (ld.get("name") or "").strip()
    views = None
    vm = re.search(r'rtngviews">\s*/\s*([\d\s]+)\s*переглядів', html)
    if not vm:
        vm = re.search(r'([\d][\d\s]{2,})\s*переглядів', html)
    if vm:
        views = int(vm.group(1).replace(" ", ""))
    agg = ld.get("aggregateRating") or {}
    desc_ld = re.sub(r"\s+", " ", (ld.get("description") or "")).strip()
    desc_full = descr_block_text(html, name)
    if desc_full.count("Рейтинг:") >= 2 or "Відгуки про роботодавців" in desc_full:
        desc_full = ""
    if "document.getElementById" in desc_full or "var canvas" in desc_full:
        m2 = re.search(re.escape(name.split('/')[0].strip()) + r"\s+(це|—|-)", desc_full)
        desc_full = desc_full[m2.start():] if m2 else ""
    description = desc_full if len(desc_full) > len(desc_ld) else desc_ld
    if description.count("Рейтинг:") >= 2:
        description = desc_ld if desc_ld.count("Рейтинг:") < 2 else ""
    stub = len(description) < 60
    try:
        rating = float(agg.get("ratingValue")) if agg.get("ratingValue") else None
    except Exception:
        rating = None
    try:
        reviews = int(agg.get("reviewCount")) if agg.get("reviewCount") else None
    except Exception:
        reviews = None
    return {
        "donor_url": url, "name": name,
        "description": "" if stub else description[:1200],
        "rating": rating, "reviews": reviews, "views": views,
    }

def detector_a(card):
    """Детектор «идеальной репутации»: высокий рейтинг при большом числе отзывов."""
    return (card.get("rating") or 0) >= 4.8 and (card.get("reviews") or 0) >= 20

def parse_niche(niche, limit=40, progress=None):
    """Собрать до limit карточек ниши. Возвращает список карточек для очереди."""
    cfg = categories.NICHES.get(niche)
    if not cfg:
        raise ValueError(f"Неизвестная ниша: {niche}")
    urls = get_sitemap_urls()
    if not urls:
        raise RuntimeError("Не удалось получить карту сайта донора (vidhuk.ua недоступен?)")
    keys = cfg["keywords"]
    random.shuffle(urls)
    found = []
    checked = 0
    for url in urls:
        if len(found) >= limit:
            break
        slug = url.lower()
        if not any(k in slug for k in keys):
            continue
        html = fetch(url)
        checked += 1
        if progress:
            progress(f"Проверено карточек: {checked}, найдено в нишу: {len(found)}")
        if not html:
            continue
        card = parse_card(url, html)
        if not card or categories.denied(card["name"]):
            continue
        n = card["name"].lower()
        if not any(k in n or k in slug for k in keys):
            continue
        card["niche"] = niche
        card["term_id"] = categories.assign_category(card["name"], niche)
        card["detector_a"] = detector_a(card)
        found.append(card)
        time.sleep(random.uniform(1.0, 2.0))
    # детектор A первыми, затем по просмотрам (спрос)
    found.sort(key=lambda c: (not c["detector_a"], -(c.get("views") or 0)))
    return found
