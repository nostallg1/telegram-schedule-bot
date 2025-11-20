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

def escape_markdown(text):
    return text

# --- ВНУТРІШНЯ ФУНКЦІЯ ЗАПИТУ ---
def make_request(group_name, semester, duration):
    """Робить один конкретний запит до сайту"""
    schedule_url = f"{BASE_URL}/students_schedule"
    params = {
        "studygroup_abbrname": group_name,
        "semestr": semester,
        "semestrduration": duration
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Referer': BASE_URL + '/',
    }
    
    # Затримка (тільки для прямих запитів, для ScraperAPI не критично)
    if not SCRAPER_API_KEY:
        time.sleep(0.5 + random.random())

    if SCRAPER_API_KEY:
        payload = {
            'api_key': SCRAPER_API_KEY,
            'url': schedule_url + '?' + requests.compat.urlencode(params),
            'render': 'true' # JS rendering допомагає
        }
        response = requests.get('http://api.scraperapi.com', params=payload, timeout=60)
    else:
        with requests.Session() as session:
            session.headers.update(headers)
            response = session.get(schedule_url, params=params, timeout=15)
            
    return response

# --- ГОЛОВНА ФУНКЦІЯ ---
def fetch_schedule_dict(group_name, semester="1", duration="1", subgroup=None, week_filter=None):
    
    # КРОК 1: Пробуємо запит з параметрами за замовчуванням (Duration=1)
    logger.info(f"Trying {group_name} with duration=1...")
    try:
        response = make_request(group_name, semester, "1") # Спочатку шукаємо в "Першій половині"
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Network error: {e}")
        return {"Info": "❌ Помилка з'єднання."}

    soup = BeautifulSoup(response.text, 'html.parser')
    content_div = soup.find('div', class_='view-content')

    # КРОК 2: Якщо пусто, пробуємо Duration=2 (Друга половина семестру)
    # Це "план Б", якщо в першій половині нічого немає
    if not content_div or not content_div.find_all('div', class_='view-grouping'):
        logger.info(f"Empty/Not found for duration=1. Trying duration=2...")
        try:
            response_2 = make_request(group_name, semester, "2")
            if response_2.status_code == 200:
                soup_2 = BeautifulSoup(response_2.text, 'html.parser')
                content_div_2 = soup_2.find('div', class_='view-content')
                if content_div_2 and content_div_2.find_all('div', class_='view-grouping'):
                    # Ура! Знайшли розклад у другій половині
                    soup = soup_2
                    content_div = content_div_2
        except:
            pass # Якщо і тут помилка, повертаємо результат першого запиту

    # --- Перевірка результату ---
    if not content_div:
        if "не знайдено" in soup.text.lower():
            return {"Info": f"❌ Групу <b>{html.escape(group_name)}</b> не знайдено."}
        return {"Info": "❌ Не вдалося отримати дані."}

    schedule_data = {} 

    # --- Subgroup Filter ---
    def is_pair_for_excluded_subgroup(text, current_subgroup):
        if not current_subgroup: return False
        excluded_subgroup = str(3 - int(current_subgroup))
        # Патерни для виключення
        patterns = [f"\({excluded_subgroup}\)", f"підгр\.\s*{excluded_subgroup}", f"{excluded_subgroup}\s*п/г"]
        text_lower = text.lower()
        
        for p in patterns:
            if re.search(p, text_lower, re.IGNORECASE):
                # Якщо є маркер виключеної групи, перевіряємо чи немає маркера нашої
                our_sub = str(current_subgroup)
                if not re.search(f"\({our_sub}\)", text_lower): 
                    return True 
        return False

    # --- PARSING ---
    try:
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
                    # Week Filter
                    classes = row.get('class', [])
                    if week_filter == 'chys' and 'znam' in classes: continue
                    if week_filter == 'znam' and 'chys' in classes: continue

                    num_header = row.find_previous('h3')
                    pair_num = num_header.get_text(strip=True) if num_header else "?"
                    
                    content = row.find('div', class_='group_content')
                    if not content: content = row
                    full_pair_text = content.get_text(separator=" ", strip=True).strip()

                    if is_pair_for_excluded_subgroup(full_pair_text, subgroup):
                        continue
                    
                    safe_text = html.escape(full_pair_text)
                    week_mark = ""
                    if 'chys' in classes: week_mark = " <i>(чис.)</i>"
                    if 'znam' in classes: week_mark = " <i>(знам.)</i>"

                    day_text += f"⏰ <b>{pair_num} пара</b>{week_mark}\n📖 {safe_text}\n──────────────\n"
                    has_pairs = True
                
                if has_pairs:
                    schedule_data[day_name] = day_text

        if not schedule_data:
            return {"Info": "📭 Розклад порожній для обраних параметрів."}

        return schedule_data

    except Exception as e:
        logger.error(f"Parser Logic Error: {e}", exc_info=True)
        return {"Info": "⚠️ Помилка обробки."}

