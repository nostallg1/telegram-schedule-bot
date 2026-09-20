import requests
from bs4 import BeautifulSoup
import logging
import re
import time
import random
import os
import html
from datetime import datetime, timedelta, timezone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "https://student.lpnu.ua"
SCRAPER_API_KEY = os.environ.get('SCRAPER_API_KEY', None)

# --- CONFIG ---
DAY_MAP = {
    "Понеділок": ["пн", "пон", "mon"],
    "Вівторок":  ["вт", "вів", "bt", "vt", "tue"],
    "Середа":    ["ср", "сер", "cp", "wed"],
    "Четвер":    ["чт", "чет", "thu"],
    "П'ятниця":  ["пт", "пят", "fri"],
    "Субота":    ["сб", "суб", "sat"],
    "Неділя":    ["нд", "нед", "sun"]
}

def get_standard_day_name(line):
    clean_line = re.sub(r'[^\w]', '', line).lower()
    for standard_name, variants in DAY_MAP.items():
        for variant in variants:
            if clean_line.startswith(variant):
                return standard_name
    return None

# =====================================================================
# ТИЖНІ: чисельник / знаменник
# =====================================================================
# Сайт НЕ приймає тип тижня в запиті (форма має лише група / семестр / половина семестру),
# тому завжди приходять пари обох тижнів разом, а вибір фільтруємо самі.
#
# Як влаштована розмітка (за описом з самої сторінки):
#   <div id="group_full" class="week_color"> ... </div>
# Клас `week_color` (зелене підсвічування) стоїть на парах ПОТОЧНОГО тижня.
# Пари іншого (альтернативного) тижня цього класу не мають.
#
# Звідси логіка:
#   * пара з week_color        -> відбувається цього тижня
#   * пара без week_color      -> відбувається лише в ІНШИЙ тиждень
#   * слот (номер пари) містить і підсвічену, і непідсвічену пару -> це чергування тижнів
#   * одна підсвічена пара в слоті -> вважаємо, що вона щотижня (показуємо в обох тижнях)
# Щоб перетворити "поточний/інший" на "чисельник/знаменник", треба знати, який тип у поточного тижня
# (див. infer_current_week): з розмітки сторінки, а якщо її там немає - зі змінної WEEK_ANCHOR.

WEEK_COLOR_CLASS = "week_color"

# Додаткові структурні позначки в class/id (не текст на сторінці), якщо сайт їх десь використовує.
_CHYS_PREFIXES = ("chys", "chis", "numer")
_ZNAM_PREFIXES = ("znam", "denom")
_CHYS_EXACT = {"week_1", "week-1", "week1", "odd"}
_ZNAM_EXACT = {"week_2", "week-2", "week2", "even"}

def _opposite(week):
    return {'chys': 'znam', 'znam': 'chys'}.get(week)

def _has_class(el, name):
    return name in (el.get('class') or [])

def _slot_key(row):
    """Слот = заголовок "N пара" (h3), під яким стоїть пара."""
    h3 = row.find_previous('h3')
    return id(h3) if h3 is not None else None

def _own_wrappers(row, boundary):
    """
    Батьківські контейнери, що належать лише цій парі/слоту (не спільні з іншими слотами).
    Дозволяє знайти week_color, навіть якщо клас стоїть на обгортці навколо пари.
    """
    for parent in row.parents:
        if parent is boundary or getattr(parent, 'name', None) in (None, '[document]'):
            break
        slots = {_slot_key(r) for r in parent.find_all('div', class_='stud_schedule')}
        if len(slots) > 1:
            break
        yield parent

def is_current_week(row, boundary):
    """True, якщо пара підсвічена класом week_color (сам рядок, вкладений блок або його обгортка)."""
    if _has_class(row, WEEK_COLOR_CLASS) or row.find(class_=WEEK_COLOR_CLASS) is not None:
        return True
    return any(_has_class(p, WEEK_COLOR_CLASS) for p in _own_wrappers(row, boundary))

def _element_tokens(el):
    tokens = list(el.get('class', []) or [])
    if el.get('id'):
        tokens.append(el.get('id'))
    for attr in ('data-week', 'week'):
        val = el.get(attr)
        if val:
            tokens.extend(re.split(r'[\s,;]+', str(val)))
    return tokens

def _tokens_week(tokens):
    found = set()
    for t in tokens:
        t = str(t).strip().lower()
        if not t:
            continue
        parts = [p for p in re.split(r'[_\-\s]+', t) if p]
        if t in _CHYS_EXACT or any(p.startswith(_CHYS_PREFIXES) for p in parts):
            found.add('chys')
        if t in _ZNAM_EXACT or any(p.startswith(_ZNAM_PREFIXES) for p in parts):
            found.add('znam')
    return found

def explicit_week(row, boundary):
    """'chys' / 'znam', якщо в class/id самої пари прямо вказано тип тижня, інакше None."""
    found = set()
    for el in [row, *_own_wrappers(row, boundary), *row.find_all(True)]:
        found |= _tokens_week(_element_tokens(el))
    return next(iter(found)) if len(found) == 1 else None

def _today():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Kyiv")).date()
    except Exception:
        return (datetime.now(timezone.utc) + timedelta(hours=3)).date()

def _week_from_anchor():
    """
    WEEK_ANCHOR=YYYY-MM-DD - будь-яка дата, що потрапляє в тиждень-ЧИСЕЛЬНИК (напр. початок семестру).
    Тижні чергуються: парна відстань від якірного тижня = чисельник, непарна = знаменник.
    """
    raw = os.environ.get("WEEK_ANCHOR", "").strip()
    if not raw:
        return None
    try:
        anchor = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        logger.warning("WEEK_ANCHOR=%r має бути у форматі YYYY-MM-DD", raw)
        return None
    today = _today()
    monday = lambda d: d - timedelta(days=d.weekday())
    weeks = (monday(today) - monday(anchor)).days // 7
    return 'chys' if weeks % 2 == 0 else 'znam'

def infer_current_week(lessons):
    """
    Який тип має ПОТОЧНИЙ тиждень: ('chys' | 'znam' | None, звідки).
    1) з розмітки сторінки: пара з явним типом + week_color каже, що цей тип зараз активний;
    2) зі змінної WEEK_ANCHOR (дата в тижні-чисельнику).
    """
    any_current = any(l['current'] for l in lessons)
    votes = {'chys': 0, 'znam': 0}
    for l in lessons:
        w = l['explicit']
        if not w:
            continue
        if l['current']:
            votes[w] += 1
        elif any_current:
            votes[_opposite(w)] += 1
    if votes['chys'] != votes['znam']:
        return ('chys' if votes['chys'] > votes['znam'] else 'znam'), 'сторінка'
    anchored = _week_from_anchor()
    if anchored:
        return anchored, 'WEEK_ANCHOR'
    return None, None

def assign_weeks(lessons, current_week, page_has_current):
    """Проставляє кожній парі l['week'] = 'chys' | 'znam' | None (None = показувати в обох тижнях)."""
    slots = {}
    for l in lessons:
        slots.setdefault((l['day'], l['slot']), []).append(l)
    for group in slots.values():
        mixed = any(l['current'] for l in group) and any(not l['current'] for l in group)
        for l in group:
            if l['explicit']:
                l['week'] = l['explicit']
            elif current_week is None or not page_has_current:
                l['week'] = None
            elif not l['current']:
                l['week'] = _opposite(current_week)   # не підсвічена = лише альтернативний тиждень
            elif mixed:
                l['week'] = current_week              # підсвічена поруч з непідсвіченою = поточний тиждень
            else:
                l['week'] = None                      # єдина підсвічена пара = щотижня

def week_excluded(lesson_week, week_filter):
    """Чи треба сховати пару при вибраному фільтрі тижня."""
    if not week_filter or not lesson_week:
        return False
    return lesson_week != week_filter

# --- ЗАПИТ ---
def make_request(group_name, semester, duration):
    schedule_url = f"{BASE_URL}/students_schedule"
    params = {
        "studygroup_abbrname": group_name,
        "semestr": semester,
        "semestrduration": duration
    }

    if SCRAPER_API_KEY:
        payload = {
            'api_key': SCRAPER_API_KEY,
            'url': schedule_url + '?' + requests.compat.urlencode(params),
            'render': 'true' # Важливо для JS
        }
        response = requests.get('http://api.scraperapi.com', params=payload, timeout=60)
    else:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': BASE_URL + '/',
        }
        time.sleep(1 + random.random())
        with requests.Session() as session:
            session.headers.update(headers)
            response = session.get(schedule_url, params=params, timeout=15)

    return response

# --- ПАРСЕР ---
def fetch_schedule_dict(group_name, semester="1", duration="1", subgroup=None, week_filter=None):

    # 1. Запит (Перша половина)
    try:
        response = make_request(group_name, semester, "1")
        if response.status_code != 200: return {"Info": f"❌ HTTP Error {response.status_code}"}
    except Exception as e:
        return {"Info": "❌ Помилка з'єднання."}

    soup = BeautifulSoup(response.text, 'html.parser')
    content_div = soup.find('div', class_='view-content')

    # 2. Якщо пусто -> Друга половина (Duration=2)
    if not content_div or not content_div.get_text(strip=True):
        try:
            response_2 = make_request(group_name, semester, "2")
            if response_2.status_code == 200:
                soup_2 = BeautifulSoup(response_2.text, 'html.parser')
                if soup_2.find('div', class_='view-content'):
                    soup = soup_2
                    content_div = soup.find('div', class_='view-content')
        except: pass

    if not content_div:
        if "не знайдено" in soup.text.lower():
            return {"Info": f"❌ Групу <b>{html.escape(group_name)}</b> не знайдено."}
        # DEBUG: Якщо контенту немає, покажемо заголовок сторінки
        title = soup.title.string if soup.title else "No Title"
        return {"Info": f"❌ Не вдалося отримати дані. Заголовок сторінки: {title}"}

    schedule_data = {}

    # --- Фільтр підгруп ---
    def is_excluded_subgroup(text, current_subgroup):
        if not current_subgroup: return False
        ex_sub = str(3 - int(current_subgroup))
        patterns = [rf"\({ex_sub}\)", rf"підгр\.\s*{ex_sub}", rf"{ex_sub}\s*п/г", rf"підгрупа\s*{ex_sub}"]
        text_lower = text.lower()
        for p in patterns:
            if re.search(p, text_lower, re.IGNORECASE):
                our_sub = str(current_subgroup)
                if not re.search(rf"\({our_sub}\)", text_lower): return True
        return False

    week_info_missing = False   # true, якщо тип тижня визначити не вдалося (фільтр тижня нічого не змінить)
    html_lessons = 0            # скільки пар знайдено в HTML-режимі (щоб не плутати "нема пар" з "нема розмітки")

    # === ВАРІАНТ 1: HTML ===
    days = content_div.find_all('div', class_='view-grouping')
    if days:
        # Крок 1: збираємо всі пари сторінки з ознакою "підсвічена (week_color)"
        lessons = []
        for day_block in days:
            header = day_block.find('span', class_='view-grouping-header')
            raw_day = header.get_text(strip=True) if header else ""
            day_name = get_standard_day_name(raw_day)
            if not day_name: continue

            for row in day_block.find_all('div', class_='stud_schedule'):
                content = row.find('div', class_='group_content')
                if not content: content = row
                num_header = row.find_previous('h3')
                lessons.append({
                    'day': day_name,
                    'slot': _slot_key(row),
                    'num': num_header.get_text(strip=True) if num_header else "?",
                    'text': content.get_text(separator=" ", strip=True).strip(),
                    'current': is_current_week(row, day_block),
                    'explicit': explicit_week(row, day_block),
                    'week': None,
                })

        html_lessons = len(lessons)
        page_has_current = any(l['current'] for l in lessons)
        page_has_explicit = any(l['explicit'] for l in lessons)
        current_week, source = infer_current_week(lessons)

        # Крок 2: підгрупа, потім тип тижня (чергування визначаємо серед пар, які користувач бачить)
        visible = [l for l in lessons if not is_excluded_subgroup(l['text'], subgroup)]
        assign_weeks(visible, current_week, page_has_current)

        week_known = page_has_explicit or (page_has_current and current_week is not None)
        week_info_missing = bool(week_filter) and not week_known

        # Діагностика (видно в логах хостингу)
        logger.info(
            "WEEKS group=%s filter=%s lessons=%s week_color=%s явний_тип=%s поточний_тиждень=%s(%s) зразки=%s",
            group_name, week_filter, len(lessons), sum(l['current'] for l in lessons),
            sum(bool(l['explicit']) for l in lessons), current_week, source,
            [(l['day'], l['num'], l['current'], l['week']) for l in lessons[:4]]
        )
        if page_has_current and current_week is None and not page_has_explicit:
            logger.warning("Є підсвічені пари (week_color), але невідомо, чи поточний тиждень - чисельник чи знаменник. "
                           "Задайте змінну WEEK_ANCHOR=YYYY-MM-DD (дата в тижні-чисельнику).")

        # Крок 3: формуємо текст по днях
        for l in visible:
            if week_excluded(l['week'], week_filter): continue
            day = l['day']
            if day not in schedule_data:
                schedule_data[day] = f"📅 <b>{day}</b> ({html.escape(group_name)})\n\n"
            week_mark = " <i>(чис.)</i>" if l['week'] == 'chys' else (" <i>(знам.)</i>" if l['week'] == 'znam' else "")
            schedule_data[day] += f"⏰ <b>{l['num']} пара</b>{week_mark}\n📖 {html.escape(l['text'])}\n──────────────\n"

    # === ВАРІАНТ 2: Текст (Fallback) ===
    # Лише якщо в HTML пар не знайшлось взагалі. Якщо вони були, але фільтр (підгрупа/тиждень) усе сховав,
    # запасний режим запускати не можна: він не вміє фільтрувати тижні й показав би зайве.
    if not schedule_data and not html_lessons:
        # У текстовому режимі немає ні week_color, ні класів, тому тиждень визначити неможливо
        week_info_missing = bool(week_filter)
        raw_text = content_div.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
        current_day = None
        temp_schedule = {}

        day_pattern = re.compile(r'^(Понеділок|Вівторок|Середа|Четвер|П\'ятниця|Субота|Неділя|Пн|Вт|Ср|Чт|Пт|Сб|Нд)\b', re.IGNORECASE)

        for line in lines:
            match = day_pattern.match(line)
            if match:
                current_day = get_standard_day_name(match.group(0))
                if current_day and current_day not in temp_schedule: temp_schedule[current_day] = []
                # Перевірка на "Пн 1 Математика"
                rem = line[len(match.group(0)):].strip()
                if rem and re.match(r'^[1-8]', rem):
                     temp_schedule[current_day].append({'num': rem[0], 'text': rem[1:].strip()})
                continue

            if current_day and re.match(r'^[1-8][\.\)\s]?', line):
                pair_num = line[0]
                text = line[1:].strip(" .)")
                temp_schedule[current_day].append({'num': pair_num, 'text': text})
                continue

            if current_day and current_day in temp_schedule and temp_schedule[current_day]:
                temp_schedule[current_day][-1]['text'] += " " + line

        for day, pairs in temp_schedule.items():
            day_text = f"📅 <b>{day}</b> ({html.escape(group_name)})\n\n"
            has = False
            for p in pairs:
                if is_excluded_subgroup(p['text'], subgroup): continue
                day_text += f"⏰ <b>{p['num']} пара</b>\n📖 {html.escape(p['text'])}\n──────────────\n"
                has = True
            if has: schedule_data[day] = day_text

    if not schedule_data and html_lessons:
        return {"Info": "📭 Для вибраних підгрупи та тижня пар не знайдено."}

    if not schedule_data:
        # --- ДІАГНОСТИКА ---
        # Ми повертаємо шматок тексту, щоб побачити, ЩО САМЕ там написано
        raw_preview = content_div.get_text(separator="\n", strip=True)[:400]
        return {"Info": f"📭 Розклад порожній. Ось що бачить бот:\n\n<pre>{html.escape(raw_preview)}</pre>"}

    # Службовий прапорець для бота: тип тижня визначити не вдалося, тому показано всі пари
    if week_info_missing:
        schedule_data["_week_unmarked"] = True

    return schedule_data
