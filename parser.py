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

# --- Config ---
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

def escape_markdown(text):
    # Екранування для HTML не потрібне, використовуємо html.escape окремо
    return text

# --- MAIN PARSER FUNCTION ---
def fetch_schedule_dict(group_name, semester="1", duration="1", subgroup=None, week_filter=None):
    """
    week_filter: 'chys', 'znam' або None
    """
    schedule_url = f"{BASE_URL}/students_schedule"
    params = {
        "studygroup_abbrname": group_name,
        "semestr": semester,
        "semestrduration": duration
    }

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Referer': BASE_URL + '/',
        }
        
        time.sleep(1 + random.random() * 2)
        
        if SCRAPER_API_KEY:
            payload = {
                'api_key': SCRAPER_API_KEY,
                'url': schedule_url + '?' + requests.compat.urlencode(params),
                'render': 'true'
            }
            response = requests.get('http://api.scraperapi.com', params=payload, timeout=60)
        else:
            with requests.Session() as session:
                session.headers.update(headers)
                response = session.get(schedule_url, params=params, timeout=15)
        
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        content_div = soup.find('div', class_='view-content')
        
        if not content_div:
            if "не знайдено" in soup.text.lower():
                return {"Info": f"❌ Групу <b>{html.escape(group_name)}</b> не знайдено."}
            return {"Info": "❌ Не вдалося отримати дані."}

        schedule_data = {} 

        # --- Subgroup Filter ---
        def is_pair_for_excluded_subgroup(text, current_subgroup):
            if not current_subgroup: return False
            excluded_subgroup = str(3 - int(current_subgroup))
            patterns = [f"\({excluded_subgroup}\)", f"підгр\.\s*{excluded_subgroup}", f"{excluded_subgroup}\s*п/г"]
            text_lower = text.lower()
            for p in patterns:
                if re.search(p, text_lower, re.IGNORECASE):
                    our_sub = str(current_subgroup)
                    if not re.search(f"\({our_sub}\)", text_lower): 
                        return True 
            return False

        # --- HTML Parsing ---
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
                    # --- WEEK FILTER LOGIC ---
                    classes = row.get('class', [])
                    # Якщо фільтр "Чисельник", а пара "Знаменник" -> пропускаємо
                    if week_filter == 'chys' and 'znam' in classes:
                        continue
                    # Якщо фільтр "Знаменник", а пара "Чисельник" -> пропускаємо
                    if week_filter == 'znam' and 'chys' in classes:
                        continue

                    num_header = row.find_previous('h3')
                    pair_num = num_header.get_text(strip=True) if num_header else "?"
                    
                    content = row.find('div', class_='group_content')
                    if not content: content = row
                    full_pair_text = content.get_text(separator=" ", strip=True).strip()

                    if is_pair_for_excluded_subgroup(full_pair_text, subgroup):
                        continue
                    
                    safe_text = html.escape(full_pair_text)
                    
                    # Додаємо позначку, якщо пара тільки в певний тиждень
                    week_mark = ""
                    if 'chys' in classes: week_mark = " <i>(чис.)</i>"
                    if 'znam' in classes: week_mark = " <i>(знам.)</i>"

                    day_text += f"⏰ <b>{pair_num} пара</b>{week_mark}\n📖 {safe_text}\n──────────────\n"
                    has_pairs = True
                
                if has_pairs:
                    schedule_data[day_name] = day_text

        if not schedule_data:
            # Спробуємо текстовий парсинг як запасний варіант, але він погано дружить з тижнями
            return {"Info": "📭 Розклад порожній для обраних параметрів."}

        return schedule_data

    except Exception as e:
        logger.error(f"Parser Error: {e}", exc_info=True)
        return {"Info": "⚠️ Технічна помилка."}
