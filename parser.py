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
# РОЗМІТКА student.lpnu.ua (перевірено на реальній сторінці)
# =====================================================================
# <div class="view-content">
#   <span class="view-grouping-header">Пн</span>          <- день (div.view-grouping-обгортки може не бути)
#   <h3>1</h3>                                             <- номер пари
#   <div class="stud_schedule">
#     <div class="views-row"><div id='group_znam' class='week_color'><div class='group_content'>...пара...</div></div></div>
#     <div class="views-row"><div id='group_chys'><div class='group_content'>...пара...</div></div></div>
#   </div>
#
# id контейнера каже ВСЕ: "хто" + "коли".
#   хто:   group_...  = вся група          sub_1_... = підгрупа 1          sub_2_... = підгрупа 2
#   коли:  ..._full   = щотижня            ..._chys  = чисельник           ..._znam  = знаменник
# Приклади: group_full, group_chys, group_znam, sub_1_full, sub_2_full (sub_N_chys / sub_N_znam за тим же принципом).
# Порядок у розмітці НЕ визначає тиждень: у слоті може першим стояти group_znam, а другим group_chys.
# Клас week_color на контейнері = ця пара відбувається на ПОТОЧНОМУ тижні (у тому числі group_full).
#
# Якщо в контейнері немає жодного з маркерів (сторінка нестандартна), діє запасна логіка за позицією:
#   * 2 рядки в слоті -> ВЕРХНІЙ = чисельник, НИЖНІЙ = знаменник; 1 рядок -> щотижня; 3+ -> не вгадуємо (щотижня).
#   * Дві колонки поруч без id (float / width:50% / col-* / flex): перша = підгрупа 1, друга = підгрупа 2.
#   * Підгрупа без структури: маркери "(1)" / "(2)" у тексті пари.
# Позицію рахуємо ДО фільтра підгрупи (порожні контейнери теж рахуються).

WEEK_COLOR_CLASS = "week_color"
WEEK_FILTERS = ("chys", "znam", "cur")          # усе інше (None) = "Всі тижні"
EMPTY_MSG = "📭 Для вибраних підгрупи та тижня пар не знайдено."

SUB_RE = re.compile(r'(?<![a-z0-9])sub(?:group)?[_\-]?([12])(?![0-9])', re.IGNORECASE)
FULL_ID_RE = re.compile(r'^group', re.IGNORECASE)          # id="group_full", "group_chys", ...
WEEK_ID_RE = re.compile(r'(?<![a-z0-9])(chys|znam|full)(?![a-z0-9])', re.IGNORECASE)   # group_chys, sub_1_znam, sub_2_full ...
COL_CLASS_RE = re.compile(r'(?<![a-z])(?:col|column|left|right|half|inline|float|cell|flex)(?![a-z])', re.IGNORECASE)
COL_STYLE_RE = re.compile(r'float\s*:\s*(?:left|right)|display\s*:\s*(?:inline|table-cell|flex)', re.IGNORECASE)
WIDTH_RE = re.compile(r'(?<![\w-])width\s*:\s*(\d+(?:\.\d+)?)\s*%', re.IGNORECASE)
PARENT_COL_RE = re.compile(r'(?<![a-z])(?:flex|columns?|cols|grid|table)(?![a-z])|display\s*:\s*(?:flex|grid|table)', re.IGNORECASE)

def _has_class(el, name):
    return name in (el.get('class') or [])

def _is_inside(node, container):
    return any(p is container for p in node.parents)

def explicit_subgroup(el):
    """'1' / '2', якщо id або class самого елемента містить sub_1 / sub_2 (sub-1, sub1, subgroup_2 ...), інакше None."""
    for token in [el.get('id') or ''] + list(el.get('class') or []):
        m = SUB_RE.search(token)
        if m:
            return m.group(1)
    return None

def explicit_week(unit, row):
    """
    'chys' | 'znam' | 'full' | None за id/class контейнера пари (group_chys, sub_1_znam, group_full ...).
    Шукаємо на самому елементі, на обгортках усередині рядка та (якщо контейнер один) на нащадках.
    None = сторінка не каже, який це тиждень.
    """
    def scan(el):
        for token in [el.get('id') or ''] + list(el.get('class') or []):
            m = WEEK_ID_RE.search(token)
            if m:
                return m.group(1).lower()
        return None

    node = unit
    while node is not None and node is not row and getattr(node, 'name', None) not in (None, '[document]'):
        found = scan(node)
        if found:
            return found
        node = node.parent
    for el in unit.find_all(True):
        found = scan(el)
        if found:
            return found
    return None

def is_full_width(unit, row):
    """True, якщо пара лежить у контейнері з id="group_..." (на всю ширину): сам елемент, предок у межах рядка або нащадок."""
    node = unit
    while node is not None and node is not row and getattr(node, 'name', None) not in (None, '[document]'):
        if FULL_ID_RE.match(node.get('id') or ''):
            return True
        node = node.parent
    return unit.find(id=FULL_ID_RE) is not None

def _column_hint_own(el):
    style = el.get('style') or ''
    for m in WIDTH_RE.finditer(style):
        if float(m.group(1)) < 100:
            return True
    if COL_STYLE_RE.search(style):
        return True
    classes = el.get('class') or []
    if any(re.search(r'(?:^|[_\-])(?:12|full)$', c, re.IGNORECASE) for c in classes):
        return False                       # col-12 / *_full: на всю ширину
    return any(COL_CLASS_RE.search(c) or re.search(r'(?:^|[_\-])(?:col|span)[_\-]?[a-z]*[_\-]?\d', c, re.IGNORECASE) for c in classes)

def _column_hint(el):
    """Ознаки того, що блок стоїть у колонці (поруч з іншим), а не на всю ширину: на самому блоці або на його обгортці."""
    return _column_hint_own(el) or (el.parent is not None and _column_hint_own(el.parent))

def _parent_columns(el):
    parent = el.parent
    if parent is None:
        return False
    return bool(PARENT_COL_RE.search(parent.get('style') or '') or any(PARENT_COL_RE.search(c) for c in (parent.get('class') or [])))

def lesson_units(row):
    """
    Контейнери пар усередині одного рядка (.stud_schedule) у порядку розмітки: [(елемент, підгрупа, джерело)].
    Джерело підгрупи: 'id' (sub_1 / sub_2), 'column' (ліва/права колонка без id), 'full' (group_full, для обох), 'none' (невідомо).
    Порожні контейнери теж повертаються, щоб позиція верх/низ і ліво/право не збивалась.
    """
    order = {id(el): i for i, el in enumerate(row.descendants)}
    labeled = [el for el in row.find_all(True) if explicit_subgroup(el)]
    labeled = [b for b in labeled if not any(o is not b and _is_inside(b, o) for o in labeled)]      # лише зовнішні

    if labeled:
        # решта пар у цьому ж рядку (наприклад, лекція на всю ширину): поза колонками підгруп і не є їх обгорткою
        cands = row.find_all('div', class_='group_content') + row.find_all('div', id=FULL_ID_RE)
        cands = [c for c in cands
                 if not any(_is_inside(c, l) or l is c for l in labeled) and not any(_is_inside(l, c) for l in labeled)]
        cands = [c for c in cands if not any(o is not c and _is_inside(c, o) for o in cands)]
        units = [(el, explicit_subgroup(el), 'id') for el in labeled]
        units += [(el, None, 'full' if is_full_width(el, row) else 'none') for el in cands]
        units.sort(key=lambda u: order.get(id(u[0]), 0))
        return units

    base = row.find_all('div', class_='group_content')
    if len(base) < 2:
        blocks = row.find_all('div', id=re.compile(r'^(sub)?group', re.IGNORECASE))
        blocks = [b for b in blocks if not any(o is not b and _is_inside(b, o) for o in blocks)]
        base = blocks if len(blocks) >= 2 else [row]
    units = [[el, None, 'full' if is_full_width(el, row) else 'none'] for el in base]

    # Дві колонки поруч без id: перша = підгрупа 1, друга = підгрупа 2 (лише для блоків не з id="group_...")
    if len(units) == 2 and all(u[2] != 'full' for u in units) and all(_column_hint(u[0]) or _parent_columns(u[0]) for u in units):
        units[0][1], units[0][2] = '1', 'column'
        units[1][1], units[1][2] = '2', 'column'
    return [tuple(u) for u in units]

def row_is_current(row_units, all_units, boundary):
    """
    True, якщо рядок підсвічений класом week_color: на самому контейнері, всередині нього або на обгортці,
    що містить лише контейнери цього рядка (обгортка, спільна з іншими рядками, нічого не означає).
    """
    others = [u for u in all_units if not any(u is r for r in row_units)]
    for unit in row_units:
        if _has_class(unit, WEEK_COLOR_CLASS) or unit.find(class_=WEEK_COLOR_CLASS) is not None:
            return True
        for parent in unit.parents:
            if parent is boundary or getattr(parent, 'name', None) in (None, '[document]'):
                break
            if any(_is_inside(o, parent) for o in others):
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

def build_rows(slot_lessons):
    """
    Розкладає пари слота по горизонтальних смугах (у порядку розмітки). Пара "підгрупа 1" і пара "підгрупа 2" стають
    в один рядок (колонки поруч); усе інше (пара на всю ширину, повтор тієї ж підгрупи) починає новий рядок.
    """
    rows = []
    for l in slot_lessons:
        cur = rows[-1] if rows else None
        if (cur and l['sub'] in ('1', '2')
                and all(x['sub'] in ('1', '2') for x in cur) and all(x['sub'] != l['sub'] for x in cur)):
            cur.append(l)
        else:
            rows.append([l])
    return rows

def assign_week_types(lessons):
    """
    Проставляє l['week'] = 'chys' | 'znam' | None (None = щотижня) та l['current'].
    Основне джерело: id пари (l['week_id']). Запасне (лише якщо в слоті жодна пара не має маркера тижня):
    позиція рядків у слоті (day, номер пари): 2 рядки = верх чисельник / низ знаменник.
    """
    slots = {}
    for l in lessons:
        slots.setdefault((l['day'], l['slot']), []).append(l)
    for group in slots.values():
        rows = build_rows(group)
        slot_has_ids = any(l['week_id'] for l in group)
        for i, row in enumerate(rows):
            row_cur = None
            for l in row:
                wid = l['week_id']
                if wid in ('chys', 'znam'):
                    l['week'] = wid
                elif wid == 'full':
                    l['week'] = None
                elif not slot_has_ids and len(rows) == 2:
                    l['week'] = 'chys' if i == 0 else 'znam'       # позиція: верхній / нижній рядок
                else:
                    l['week'] = None
                if wid:
                    # тиждень відомий з id -> підсвітка рахується для кожної пари окремо
                    l['current'] = row_is_current([l['el']], l['all_units'], l['boundary'])
                else:
                    if row_cur is None:
                        row_cur = row_is_current([x['el'] for x in row], l['all_units'], l['boundary'])
                    l['current'] = row_cur

def week_visible(lesson, week_filter):
    """Чи показувати пару при вибраному фільтрі. Пари "щотижня" (week is None) видно завжди."""
    if week_filter == 'chys':
        return lesson['week'] in ('chys', None)
    if week_filter == 'znam':
        return lesson['week'] in ('znam', None)
    if week_filter == 'cur':
        return lesson['current'] or lesson['week'] is None
    return True                            # "Всі тижні"

def is_excluded_subgroup(text, current_subgroup):
    """Запасний варіант, коли структура не каже, яка це підгрупа: шукаємо маркери "(2)", "підгр. 2" ... у тексті."""
    if not current_subgroup: return False
    ex_sub = str(3 - int(current_subgroup))
    patterns = [rf"\({ex_sub}\)", rf"підгр\.\s*{ex_sub}", rf"{ex_sub}\s*п/г", rf"підгрупа\s*{ex_sub}"]
    text_lower = text.lower()
    for p in patterns:
        if re.search(p, text_lower, re.IGNORECASE):
            our_sub = str(current_subgroup)
            if not re.search(rf"\({our_sub}\)", text_lower): return True
    return False

def subgroup_visible(lesson, subgroup):
    """
    Підгрупа 1: sub == "1" і sub is None. Підгрупа 2: sub == "2" і sub is None.
    Порожня колонка чужої підгрупи не підставляє сусідню пару: пара з sub="1" ніколи не потрапить до підгрупи 2.
    """
    if not subgroup:
        return True
    if lesson['sub'] in ('1', '2'):
        return lesson['sub'] == str(subgroup)
    if lesson['sub_src'] == 'full':
        return True                                     # id="group_full": для обох підгруп, текст не перевіряємо
    return not is_excluded_subgroup(lesson['text'], subgroup)   # структури немає -> маркери в тексті

def iter_schedule_rows(content_div):
    """
    (день, div.stud_schedule) у порядку розмітки. Працює і коли дні обгорнуті в div.view-grouping,
    і коли (як зараз на сайті) заголовки днів та розклад лежать пласким списком в одному div.view-content.
    """
    day = None
    for el in content_div.find_all(True):
        classes = el.get('class') or []
        if 'view-grouping-header' in classes:
            day = get_standard_day_name(el.get_text(strip=True))
        elif el.name == 'div' and 'stud_schedule' in classes and day:
            yield day, el

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

    if week_filter not in WEEK_FILTERS:
        week_filter = None      # None = "Всі тижні"

    html_lessons = 0            # скільки пар знайдено в HTML-режимі (щоб не плутати "нема пар" з "нема розмітки")

    # === ВАРІАНТ 1: HTML ===
    schedule_rows = list(iter_schedule_rows(content_div))
    if schedule_rows:
        # Крок 1: збираємо всі контейнери пар (разом з порожніми, щоб позиція верх/низ і ліво/право була точною)
        units = [(day_name, row, u, sub, src) for day_name, row in schedule_rows
                 for (u, sub, src) in lesson_units(row)]
        all_units = [u for _, _, u, _, _ in units]
        lessons = []
        for day_name, row, unit, sub, src in units:
            content = unit
            if unit is row:
                content = row.find('div', class_='group_content') or row
            num_header = unit.find_previous('h3')
            lessons.append({
                'day': day_name,
                'slot': slot_number(unit),
                'num': num_header.get_text(strip=True) if num_header else "?",
                'text': content.get_text(separator=" ", strip=True).strip(),
                'el': unit, 'boundary': content_div, 'all_units': all_units,
                'sub': sub,                            # "1" | "2" | None (None = для обох підгруп)
                'sub_src': src,                        # id | column | full | none
                'week_id': explicit_week(unit, row),   # chys | znam | full | None
                'current': False,
                'week': None,
                'dbg': (_describe(unit), _describe(unit.parent)),
            })

        # Крок 2: верх/низ по слотах (до фільтра підгрупи)
        assign_week_types(lessons)
        filled = [l for l in lessons if l['text']]
        html_lessons = len(filled)
        visible = [l for l in filled if subgroup_visible(l, subgroup)]

        # Діагностика (видно в логах хостингу)
        logger.info("WEEKS group=%s filter=%s sub=%s контейнерів=%s непорожніх=%s чис=%s знам=%s щотижня=%s week_color=%s "
                    "підгр1=%s підгр2=%s для_обох=%s джерела=%s id_тижня=%s структура=%s",
                    group_name, week_filter, subgroup, len(lessons), html_lessons,
                    sum(l['week'] == 'chys' for l in filled), sum(l['week'] == 'znam' for l in filled),
                    sum(l['week'] is None for l in filled), sum(l['current'] for l in lessons),
                    sum(l['sub'] == '1' for l in filled), sum(l['sub'] == '2' for l in filled), sum(l['sub'] is None for l in filled),
                    sorted({l['sub_src'] for l in lessons}), sorted({str(l['week_id']) for l in lessons}), [l['dbg'] for l in lessons[:3]])

        # Крок 3: фільтр тижня і текст по днях
        for l in visible:
            if not week_visible(l, week_filter): continue
            day = l['day']
            if day not in schedule_data:
                schedule_data[day] = f"📅 <b>{day}</b> ({html.escape(group_name)})\n\n"
            week_mark = " <i>(чис.)</i>" if l['week'] == 'chys' else (" <i>(знам.)</i>" if l['week'] == 'znam' else "")
            sub_mark = f" <i>(підгр. {l['sub']})</i>" if l['sub'] in ('1', '2') else ""
            schedule_data[day] += f"⏰ <b>{l['num']} пара</b>{week_mark}{sub_mark}\n📖 {html.escape(l['text'])}\n──────────────\n"

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
