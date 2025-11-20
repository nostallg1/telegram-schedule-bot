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

# --- ДОПОМІЖНІ ФУНКЦІЇ ---
def escape_markdown(text):
    text = re.sub(r'([.()\[\]-])', r'\\\1', text)
    text = re.sub(r'([~`>#+=|{}]!)', r'\\\1', text)
    return text.replace('_', r'\_').replace('*', r'\*')

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

# --- ГОЛОВНА ФУНКЦІЯ ---
def fetch_schedule_dict(group_name, semester="1", duration="1", subgroup=None, week_filter=None):
    """
    week_filter: 'chys' (чисельник), 'znam' (знаменник) або None (всі)
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
            return {"Info": "❌ Не вдалося отримати дані з сайту."}

        schedule_data = {} 

        # --- Фільтрація підгруп ---
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

        # --- СПРОБА 1: HTML ---
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
                    # ФІЛЬТРАЦІЯ ПО ТИЖНЯХ (CSS КЛАСИ)
                    classes = row.get('class', [])
                    if week_filter == 'chys' and 'znam' in classes:
                        continue # Пропускаємо знаменник, якщо хочемо чисельник
                    if week_filter == 'znam' and 'chys' in classes:
                        continue # Пропускаємо чисельник, якщо хочемо знаменник

                    num_header = row.find_previous('h3')
                    pair_num = num_header.get_text(strip=True) if num_header else "?"
                    
                    content = row.find('div', class_='group_content')
                    if not content: content = row
                    full_pair_text = content.get_text(separator=" ", strip=True).strip()

                    if is_pair_for_excluded_subgroup(full_pair_text, subgroup):
                        continue
                    
                    safe_text = html.escape(full_pair_text)
                    day_text += f"⏰ <b>{pair_num} пара</b>\n📖 {safe_text}\n──────────────\n"
                    has_pairs = True
                
                if has_pairs:
                    schedule_data[day_name] = day_text

        # --- СПРОБА 2: Текст (Fallback) ---
        # Примітка: Текстовий парсинг погано розуміє чисельник/знаменник, бо це часто лише колір на сайті.
        # Тому тут ми просто повертаємо все, якщо HTML не спрацював.
        if not schedule_data:
             return {"Info": "📭 Розклад порожній або не вдалося визначити тижні."}

        return schedule_data

    except Exception as e:
        logger.error(f"Parser Error: {e}", exc_info=True)
        return {"Info": "⚠️ Технічна помилка."}
