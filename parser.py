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

    # --- Фільтр тижнів ---
    def is_excluded_week(classes_list, current_filter):
        if not current_filter: return False
        cls = set(classes_list)
        is_chys = 'chys' in cls or 'week_1' in cls
        is_znam = 'znam' in cls or 'week_2' in cls
        if current_filter == 'chys' and is_znam and not is_chys: return True
        if current_filter == 'znam' and is_chys and not is_znam: return True
        return False

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
                if is_excluded_week(row.get('class', []), week_filter): continue

                num_header = row.find_previous('h3')
                pair_num = num_header.get_text(strip=True) if num_header else "?"
                
                content = row.find('div', class_='group_content')
                if not content: content = row
                full_pair_text = content.get_text(separator=" ", strip=True).strip()

                if is_excluded_subgroup(full_pair_text, subgroup): continue
                
                safe_text = html.escape(full_pair_text)
                classes = row.get('class', [])
                week_mark = " <i>(чис.)</i>" if ('chys' in classes or 'week_1' in classes) else (" <i>(знам.)</i>" if ('znam' in classes or 'week_2' in classes) else "")

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
                if is_excluded_subgroup(p['text'], subgroup): continue
                day_text += f"⏰ <b>{p['num']} пара</b>\n📖 {html.escape(p['text'])}\n──────────────\n"
                has = True
            if has: schedule_data[day] = day_text

    if not schedule_data:
        # --- ДІАГНОСТИКА ---
        # Ми повертаємо шматок тексту, щоб побачити, ЩО САМЕ там написано
        raw_preview = content_div.get_text(separator="\n", strip=True)[:400]
        return {"Info": f"📭 Розклад порожній. Ось що бачить бот:\n\n<pre>{html.escape(raw_preview)}</pre>"}

    return schedule_data


