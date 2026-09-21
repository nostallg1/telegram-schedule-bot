import requests
from bs4 import BeautifulSoup
import logging
import re
import time
import random
import os
import html

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
# ТИЖНІ: чисельник / знаменник / поточний (за позицією в слоті)
# =====================================================================
# Сайт не приймає тип тижня в запиті і не підписує його всередині карток, тому розділяємо самі.
# Слот = один заголовок <h3> ("N пара") у межах дня, під ним лежать контейнери пар:
#   * 1 контейнер   -> пара щотижня                      (week = None)
#   * 2 контейнери  -> ВЕРХНІЙ = чисельник ('chys'), НИЖНІЙ = знаменник ('znam')
#   * 3+ контейнерів -> структура незрозуміла, тому не вгадуємо: пари вважаємо щотижневими
# id (наприклад, "group_full") тип тижня НЕ визначає: сайт ставить його майже на кожну пару.
# Клас week_color підсвічує контейнер, що відбувається ЗАРАЗ; він потрібен лише для фільтра "Поточний тиждень".
# Позицію рахуємо ДО фільтра підгрупи, щоб пара не "перепливла" з верхньої половини на всю клітинку.

WEEK_COLOR_CLASS = "week_color"
WEEK_FILTERS = ("chys", "znam", "cur")          # усе інше (None) = "Всі тижні"
EMPTY_MSG = "📭 Для вибраних підгрупи та тижня пар не знайдено."

def _has_class(el, name):
    return name in (el.get('class') or [])

def _is_inside(node, container):
    return any(p is container for p in node.parents)

def lesson_units(row):
    """
    Контейнери пар усередині одного рядка (.stud_schedule). Якщо рядок містить кілька блоків
    (верхня/нижня половина), кожен береться окремо, навіть порожній, щоб не збилась позиція.
    Якщо блок один, одиницею є сам рядок.
    """
    contents = row.find_all('div', class_='group_content')
    if len(contents) >= 2:
        return contents
    blocks = row.find_all('div', id=re.compile(r'^(sub)?group', re.IGNORECASE))
    blocks = [b for b in blocks if not any(o is not b and _is_inside(b, o) for o in blocks)]  # лише зовнішні
    if len(blocks) >= 2:
        return blocks
    return [row]

def is_current_week(unit, all_units, boundary):
    """
    True, якщо контейнер підсвічений класом week_color: на ньому самому, всередині нього
    або на обгортці, що містить лише цей контейнер (обгортка, спільна з іншими, нічого не означає).
    """
    if _has_class(unit, WEEK_COLOR_CLASS) or unit.find(class_=WEEK_COLOR_CLASS) is not None:
        return True
    for parent in unit.parents:
        if parent is boundary or getattr(parent, 'name', None) in (None, '[document]'):
            break
        if any(u is not unit and _is_inside(u, parent) for u in all_units):
            break
        if _has_class(parent, WEEK_COLOR_CLASS):
            return True
    return False

def slot_number(unit):
    """Номер пари з найближчого попереднього <h3> ("1 пара" -> 1). Без номера - ключ за самим тегом."""
    h3 = unit.find_previous('h3')
    if h3 is None:
        return None
    m = re.search(r'\d+', h3.get_text())
    return int(m.group()) if m else id(h3)

def assign_week_types(lessons):
    """Групує пари за (день, номер пари) і проставляє l['week'] = 'chys' | 'znam' | None (None = щотижня)."""
    slots = {}
    for l in lessons:
        slots.setdefault((l['day'], l['slot']), []).append(l)
    for group in slots.values():
        if len(group) == 2:
            group[0]['week'] = 'chys'      # верхній контейнер
            group[1]['week'] = 'znam'      # нижній контейнер
        else:
            for l in group:
                l['week'] = None           # один контейнер на всю клітинку (або незрозуміла структура)

def week_visible(lesson, week_filter):
    """Чи показувати пару при вибраному фільтрі. Пари "щотижня" (week is None) видно завжди."""
    if week_filter == 'chys':
        return lesson['week'] in ('chys', None)
    if week_filter == 'znam':
        return lesson['week'] in ('znam', None)
    if week_filter == 'cur':
        return lesson['current'] or lesson['week'] is None
    return True                            # "Всі тижні"

def _describe(el):
    if el is None:
        return None
    return f"{el.name}#{el.get('id') or ''}.{'.'.join(el.get('class', []) or [])}"

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

    if week_filter not in WEEK_FILTERS:
        week_filter = None      # None = "Всі тижні"

    html_lessons = 0            # скільки пар знайдено в HTML-режимі (щоб не плутати "нема пар" з "нема розмітки")

    # === ВАРІАНТ 1: HTML ===
    days = content_div.find_all('div', class_='view-grouping')
    if days:
        # Крок 1: збираємо всі контейнери пар (разом з порожніми половинами, щоб позиція верх/низ була точною)
        lessons = []
        for day_block in days:
            header = day_block.find('span', class_='view-grouping-header')
            raw_day = header.get_text(strip=True) if header else ""
            day_name = get_standard_day_name(raw_day)
            if not day_name: continue

            units = [(row, u) for row in day_block.find_all('div', class_='stud_schedule') for u in lesson_units(row)]
            unit_els = [u for _, u in units]
            for row, unit in units:
                content = unit
                if unit is row:
                    content = row.find('div', class_='group_content') or row
                num_header = unit.find_previous('h3')
                lessons.append({
                    'day': day_name,
                    'slot': slot_number(unit),
                    'num': num_header.get_text(strip=True) if num_header else "?",
                    'text': content.get_text(separator=" ", strip=True).strip(),
                    'current': is_current_week(unit, unit_els, day_block),
                    'week': None,
                    'dbg': (_describe(unit), _describe(unit.parent)),
                })

        # Крок 2: верх/низ по слотах, і лише потім підгрупа
        assign_week_types(lessons)
        filled = [l for l in lessons if l['text']]
        html_lessons = len(filled)
        visible = [l for l in filled if not is_excluded_subgroup(l['text'], subgroup)]

        # Діагностика (видно в логах хостингу)
        logger.info("WEEKS group=%s filter=%s контейнерів=%s непорожніх=%s чис=%s знам=%s щотижня=%s week_color=%s структура=%s",
                    group_name, week_filter, len(lessons), html_lessons,
                    sum(l['week'] == 'chys' for l in filled), sum(l['week'] == 'znam' for l in filled),
                    sum(l['week'] is None for l in filled), sum(l['current'] for l in lessons),
                    [l['dbg'] for l in lessons[:3]])

        # Крок 3: фільтр тижня і текст по днях
        for l in visible:
            if not week_visible(l, week_filter): continue
            day = l['day']
            if day not in schedule_data:
                schedule_data[day] = f"📅 <b>{day}</b> ({html.escape(group_name)})\n\n"
            week_mark = " <i>(чис.)</i>" if l['week'] == 'chys' else (" <i>(знам.)</i>" if l['week'] == 'znam' else "")
            schedule_data[day] += f"⏰ <b>{l['num']} пара</b>{week_mark}\n📖 {html.escape(l['text'])}\n──────────────\n"

    # === ВАРІАНТ 2: Текст (Fallback) ===
    # Лише якщо в HTML пар не знайшлось взагалі. Якщо вони були, але фільтр (підгрупа/тиждень) усе сховав,
    # запасний режим запускати не можна: він не вміє фільтрувати тижні й показав би зайве.
    if not schedule_data and not html_lessons:
        # Текстовий режим: контейнерів верх/низ тут немає, тож тижні розділити неможливо.
        # Не переривамо роботу: показуємо розклад як є (аварійний режим для нестандартної сторінки).
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
        return {"Info": EMPTY_MSG}

    if not schedule_data:
        # --- ДІАГНОСТИКА ---
        # Ми повертаємо шматок тексту, щоб побачити, ЩО САМЕ там написано
        raw_preview = content_div.get_text(separator="\n", strip=True)[:400]
        return {"Info": f"📭 Розклад порожній. Ось що бачить бот:\n\n<pre>{html.escape(raw_preview)}</pre>"}

    return schedule_data
