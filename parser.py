import requests
from bs4 import BeautifulSoup
import logging
import re
import time
import random
import os
import html # <-- ВАЖЛИВО: Бібліотека для безпечного тексту

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "https://student.lpnu.ua"

# Ключ для проксі (якщо є)
SCRAPER_API_KEY = os.environ.get('SCRAPER_API_KEY', None)

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

def fetch_schedule_dict(group_name, semester="1", duration="1", subgroup=None):
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
            'Connection': 'keep-alive',
            'Referer': BASE_URL + '/',
        }
        
        # Затримка для маскування
        time.sleep(1 + random.random() * 2)
        
        # Логіка запиту (ScraperAPI або прямий)
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
            # Використовуємо html.escape для безпечного виводу назви групи
            if "не знайдено" in soup.text.lower():
                return {"Info": f"❌ Групу <b>{html.escape(group_name)}</b> не знайдено."}
            return {"Info": "❌ Не вдалося отримати дані з сайту."}

        schedule_data = {} 

        # --- Фільтрація ---
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
                
                # Використовуємо <b> для жирного тексту
                day_text = f"📅 <b>{day_name}</b> ({html.escape(group_name)})\n\n"
                has_pairs = False
                
                rows = day_block.find_all('div', class_='stud_schedule')
                for row in rows:
                    num_header = row.find_previous('h3')
                    pair_num = num_header.get_text(strip=True) if num_header else "?"
                    
                    content = row.find('div', class_='group_content')
                    if not content: content = row
                    full_pair_text = content.get_text(separator=" ", strip=True).strip()

                    if is_pair_for_excluded_subgroup(full_pair_text, subgroup):
                        continue
                    
                    # Безпечний текст через html.escape
                    safe_text = html.escape(full_pair_text)
                    day_text += f"⏰ <b>{pair_num} пара</b>\n📖 {safe_text}\n──────────────\n"
                    has_pairs = True
                
                if has_pairs:
                    schedule_data[day_name] = day_text

        # --- СПРОБА 2: Текст ---
        if not schedule_data:
            raw_text = content_div.get_text(separator="\n", strip=True)
            lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
            
            current_day = None
            temp_schedule = {}
            day_pattern = re.compile(r'^(Понеділок|Вівторок|Середа|Четвер|П\'ятниця|Субота|Неділя|Пн|Вт|Ср|Чт|Пт|Сб|Нд)\b', re.IGNORECASE)

            for line in lines:
                match = day_pattern.match(line)
                if match:
                    day_part = match.group(0)
                    det_day = get_standard_day_name(day_part)
                    if det_day:
                        current_day = det_day
                        if current_day not in temp_schedule: temp_schedule[current_day] = []
                        
                        remainder = line[len(day_part):].strip()
                        if remainder and re.match(r'^[1-8]$', remainder.split()[0]):
                            pair_num = remainder.split()[0]
                            temp_schedule[current_day].append({'num': pair_num, 'text': remainder[len(pair_num):].strip()})
                        continue
                
                if current_day and re.match(r'^[1-8]$', line):
                    temp_schedule[current_day].append({'num': line, 'text': ""})
                    continue
                
                if current_day and current_day in temp_schedule and temp_schedule[current_day]:
                    temp_schedule[current_day][-1]['text'] += ("\n" if temp_schedule[current_day][-1]['text'] else "") + line

            for day, pairs in temp_schedule.items():
                day_text = f"📅 <b>{day}</b> ({html.escape(group_name)})\n\n"
                has_pairs_in_day = False
                for pair in pairs:
                    if is_pair_for_excluded_subgroup(pair['text'], subgroup): continue
                    
                    safe_text = html.escape(pair['text'])
                    day_text += f"⏰ <b>{pair['num']} пара</b>\n📖 {safe_text}\n──────────────\n"
                    has_pairs_in_day = True
                
                if has_pairs_in_day:
                    schedule_data[day] = day_text

        if not schedule_data:
            return {"Info": "📭 Розклад порожній."}

        return schedule_data

    except Exception as e:
        logger.error(f"Parser Error: {e}", exc_info=True)
        return {"Info": "⚠️ Технічна помилка."}
