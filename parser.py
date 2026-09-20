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

# --- ВИЗНАЧЕННЯ ТИЖНЯ (чисельник / знаменник) ---
# Сайт НЕ приймає тип тижня як параметр запиту (форма має лише група / семестр / половина семестру),
# тому завжди приходять обидва тижні разом, а фільтруємо ми їх самі за позначками в HTML.
_CHYS_PREFIXES = ("chys", "chis", "numer", "чис")
_ZNAM_PREFIXES = ("znam", "denom", "знам")
_CHYS_EXACT = {"week_1", "week-1", "week1", "odd"}
_ZNAM_EXACT = {"week_2", "week-2", "week2", "even"}
# Текстові позначки. Свідомо суворі, щоб не зачепити назви предметів на кшталт "Чисельні методи".
_TEXT_CHYS = re.compile(r'(?<![а-яіїєґ])(чис\.|чисельник)(?![а-яіїєґ])', re.IGNORECASE)
_TEXT_ZNAM = re.compile(r'(?<![а-яіїєґ])(знам\.|знаменник)(?![а-яіїєґ])', re.IGNORECASE)

def _tokens_week(tokens):
    """Повертає набір {'chys','znam'} за списком CSS-класів / значень атрибутів."""
    found = set()
    for t in tokens:
        t = str(t).strip().lower()
        if not t:
            continue
        if t.startswith(_CHYS_PREFIXES) or t in _CHYS_EXACT:
            found.add('chys')
        if t.startswith(_ZNAM_PREFIXES) or t in _ZNAM_EXACT:
            found.add('znam')
    return found

def _element_tokens(el):
    tokens = list(el.get('class', []) or [])
    for attr in ('data-week', 'week'):
        val = el.get(attr)
        if val:
            tokens.extend(re.split(r'[\s,;]+', str(val)))
    return tokens

def _text_week(text):
    found = set()
    if _TEXT_CHYS.search(text): found.add('chys')
    if _TEXT_ZNAM.search(text): found.add('znam')
    return found

def detect_week(row, boundary, text=""):
    """
    'chys' / 'znam' / None (None = пара стоїть в обох тижнях або позначки немає).
    Дивимось: клас самого рядка, його батьків (до блоку дня), усіх вкладених елементів, а потім текст.
    """
    found = set(_tokens_week(_element_tokens(row)))
    for parent in row.parents:
        if parent is boundary or parent is None or parent.name in (None, '[document]'):
            break
        found |= _tokens_week(_element_tokens(parent))
    for child in row.find_all(True):
        found |= _tokens_week(_element_tokens(child))
    if not found:
        found = _text_week(text)
    return next(iter(found)) if len(found) == 1 else None

def week_excluded(row_week, week_filter):
    """Чи треба сховати пару при вибраному фільтрі тижня."""
    if not week_filter or not row_week:
        return False
    return row_week != week_filter

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
        patterns = [f"\({ex_sub}\)", f"підгр\.\s*{ex_sub}", f"{ex_sub}\s*п/г", f"підгрупа\s*{ex_sub}"]
        text_lower = text.lower()
        for p in patterns:
            if re.search(p, text_lower, re.IGNORECASE):
                our_sub = str(current_subgroup)
                if not re.search(f"\({our_sub}\)", text_lower): return True 
        return False

    # Статистика для діагностики: скільки пар мають позначку тижня
    stats = {'rows': 0, 'chys': 0, 'znam': 0, 'none': 0, 'samples': []}

    def count_row(row_week, sample):
        stats['rows'] += 1
        stats[row_week or 'none'] += 1
        if len(stats['samples']) < 4:
            stats['samples'].append(sample)

    # === ВАРІАНТ 1: HTML ===
    days = content_div.find_all('div', class_='view-grouping')
    if days:
        for day_block in days:
            header = day_block.find('span', class_='view-grouping-header')
            raw_day = header.get_text(strip=True) if header else ""
            day_name = get_standard_day_name(raw_day)
            if not day_name: continue 
            
            day_text = f"📅 <b>{day_name}</b> ({html.escape(group_name)})\n\n"
            has_pairs = False
            
            rows = day_block.find_all('div', class_='stud_schedule')
            for row in rows:
                content = row.find('div', class_='group_content')
                if not content: content = row
                full_pair_text = content.get_text(separator=" ", strip=True).strip()

                row_week = detect_week(row, day_block, full_pair_text)
                count_row(row_week, {'classes': row.get('class', []), 'week': row_week, 'text': full_pair_text[:40]})
                if week_excluded(row_week, week_filter): continue

                num_header = row.find_previous('h3')
                pair_num = num_header.get_text(strip=True) if num_header else "?"

                if is_excluded_subgroup(full_pair_text, subgroup): continue

                safe_text = html.escape(full_pair_text)
                week_mark = " <i>(чис.)</i>" if row_week == 'chys' else (" <i>(знам.)</i>" if row_week == 'znam' else "")

                day_text += f"⏰ <b>{pair_num} пара</b>{week_mark}\n📖 {safe_text}\n──────────────\n"
                has_pairs = True
            
            if has_pairs:
                schedule_data[day_name] = day_text

    # === ВАРІАНТ 2: Текст (Fallback) ===
    if not schedule_data:
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
                # Раніше в цьому режимі тиждень взагалі не фільтрувався
                row_week = next(iter(_text_week(p['text'])), None) if len(_text_week(p['text'])) == 1 else None
                count_row(row_week, {'classes': [], 'week': row_week, 'text': p['text'][:40]})
                if week_excluded(row_week, week_filter): continue
                if is_excluded_subgroup(p['text'], subgroup): continue
                week_mark = " <i>(чис.)</i>" if row_week == 'chys' else (" <i>(знам.)</i>" if row_week == 'znam' else "")
                day_text += f"⏰ <b>{p['num']} пара</b>{week_mark}\n📖 {html.escape(p['text'])}\n──────────────\n"
                has = True
            if has: schedule_data[day] = day_text

    if not schedule_data:
        # --- ДІАГНОСТИКА ---
        # Ми повертаємо шматок тексту, щоб побачити, ЩО САМЕ там написано
        raw_preview = content_div.get_text(separator="\n", strip=True)[:400]
        return {"Info": f"📭 Розклад порожній. Ось що бачить бот:\n\n<pre>{html.escape(raw_preview)}</pre>"}

    # Діагностика тижнів (видно в логах хостингу)
    logger.info(
        "WEEKS group=%s filter=%s rows=%s чис=%s знам=%s без_позначки=%s зразки=%s",
        group_name, week_filter, stats['rows'], stats['chys'], stats['znam'], stats['none'], stats['samples']
    )
    # Якщо на сторінці немає жодної позначки тижня, фільтр нічого не може змінити.
    # Повідомляємо про це боту, щоб показати користувачу чесну примітку.
    if week_filter and stats['rows'] and not (stats['chys'] or stats['znam']):
        schedule_data["_week_unmarked"] = True

    return schedule_data


