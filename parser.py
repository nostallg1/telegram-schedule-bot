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
    # Видаляємо все, крім букв (щоб "Пн." стало "пн")
    clean_line = re.sub(r'[^\w]', '', line).lower()
    for standard_name, variants in DAY_MAP.items():
        for variant in variants:
            if clean_line.startswith(variant):
                return standard_name
    return None

def escape_markdown(text):
    return text

# --- REQUEST FUNCTION ---
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
            'render': 'true'
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

# --- MAIN PARSER ---
def fetch_schedule_dict(group_name, semester="1", duration="1", subgroup=None, week_filter=None):
    
    # 1. Отримуємо HTML
    try:
        response = make_request(group_name, semester, "1")
        if response.status_code != 200:
             return {"Info": f"❌ Помилка HTTP {response.status_code}."}
    except Exception as e:
        logger.error(f"Network error: {e}")
        return {"Info": "❌ Помилка з'єднання."}

    soup = BeautifulSoup(response.text, 'html.parser')
    content_div = soup.find('div', class_='view-content')

    # 2. Спроба знайти розклад в другій половині семестру, якщо перша пуста
    if not content_div or not content_div.find_all('div', class_='view-grouping'):
        try:
            response_2 = make_request(group_name, semester, "2")
            if response_2.status_code == 200:
                soup_2 = BeautifulSoup(response_2.text, 'html.parser')
                content_div_2 = soup_2.find('div', class_='view-content')
                if content_div_2 and (content_div_2.find_all('div', class_='view-grouping') or len(content_div_2.get_text(strip=True)) > 50):
                    soup = soup_2
                    content_div = content_div_2
        except: pass

    if not content_div:
        if "не знайдено" in soup.text.lower():
            return {"Info": f"❌ Групу <b>{html.escape(group_name)}</b> не знайдено."}
        return {"Info": "❌ Не вдалося отримати дані (можливо, захист сайту)."}

    schedule_data = {} 

    # --- Фільтр підгруп ---
    def is_pair_for_excluded_subgroup(text, current_subgroup):
        if not current_subgroup: return False
        excluded_subgroup = str(3 - int(current_subgroup))
        patterns = [f"\({excluded_subgroup}\)", f"підгр\.\s*{excluded_subgroup}", f"{excluded_subgroup}\s*п/г"]
        text_lower = text.lower()
        for p in patterns:
            if re.search(p, text_lower, re.IGNORECASE):
                our_sub = str(current_subgroup)
                if not re.search(f"\({our_sub}\)", text_lower): return True 
        return False

    # === ВАРІАНТ 1: Парсинг HTML-блоків ===
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
                classes = row.get('class', [])
                if week_filter == 'chys' and 'znam' in classes: continue
                if week_filter == 'znam' and 'chys' in classes: continue

                num_header = row.find_previous('h3')
                pair_num = num_header.get_text(strip=True) if num_header else "?"
                
                content = row.find('div', class_='group_content')
                if not content: content = row
                full_pair_text = content.get_text(separator=" ", strip=True).strip()

                if is_pair_for_excluded_subgroup(full_pair_text, subgroup): continue
                
                safe_text = html.escape(full_pair_text)
                week_mark = " <i>(чис.)</i>" if 'chys' in classes else (" <i>(знам.)</i>" if 'znam' in classes else "")

                day_text += f"⏰ <b>{pair_num} пара</b>{week_mark}\n📖 {safe_text}\n──────────────\n"
                has_pairs = True
            
            if has_pairs:
                schedule_data[day_name] = day_text

    # === ВАРІАНТ 2: Текстовий парсинг (Гнучкий) ===
    # Якщо HTML-блоків не знайдено або вони порожні, парсимо "сирий" текст
    if not schedule_data:
        raw_text = content_div.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
        
        current_day = None
        temp_schedule = {}

        for line in lines:
            # 1. Шукаємо День (використовуємо нашу функцію)
            detected_day = get_standard_day_name(line)
            if detected_day:
                current_day = detected_day
                if current_day not in temp_schedule: temp_schedule[current_day] = []
                continue # Це був рядок з днем, йдемо далі
            
            # 2. Шукаємо номер пари
            # Гнучкий Regex: початок рядка, цифра 1-9, опціонально крапка/дужка
            # Приклади: "1", "2.", "3)", "4 пара"
            pair_match = re.match(r'^([1-9])[\.\)\s]?', line)
            
            if current_day and pair_match:
                pair_num = pair_match.group(1) # Беремо тільки цифру
                # Якщо в цьому ж рядку є текст пари (напр. "1 Математика")
                text_part = line[len(pair_match.group(0)):].strip()
                
                temp_schedule[current_day].append({'num': pair_num, 'text': text_part})
                continue

            # 3. Текст пари (продовження)
            if current_day and current_day in temp_schedule and temp_schedule[current_day]:
                last_pair = temp_schedule[current_day][-1]
                # Додаємо текст до попередньої пари
                last_pair['text'] += ("\n" if last_pair['text'] else "") + line

        # Формуємо фінальний словник
        for day, pairs in temp_schedule.items():
            day_text = f"📅 <b>{day}</b> ({html.escape(group_name)})\n\n"
            has_pairs_in_day = False
            for pair in pairs:
                full_text = pair['text']
                if is_pair_for_excluded_subgroup(full_text, subgroup): continue
                
                # При текстовому парсингу ми не знаємо тижнів (чисельник/знаменник), тому показуємо все
                safe_text = html.escape(full_text)
                day_text += f"⏰ <b>{pair['num']} пара</b>\n📖 {safe_text}\n──────────────\n"
                has_pairs_in_day = True
            
            if has_pairs_in_day:
                schedule_data[day] = day_text

    if not schedule_data:
        return {"Info": "📭 Розклад порожній (або вихідні)."}

    return schedule_data

