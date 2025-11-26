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

# --- ВНУТРІШНЯ ФУНКЦІЯ ЗАПИТУ ---
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

# --- ГОЛОВНА ФУНКЦІЯ ---
def fetch_schedule_dict(group_name, semester="1", duration="1", subgroup=None, week_filter=None):
    
    # 1. Запит (Перша половина семестру)
    try:
        response = make_request(group_name, semester, "1")
        if response.status_code != 200: return {"Info": f"❌ HTTP Error {response.status_code}"}
    except Exception as e:
        return {"Info": "❌ Помилка з'єднання."}

    soup = BeautifulSoup(response.text, 'html.parser')
    content_div = soup.find('div', class_='view-content')

    # 2. Якщо пусто -> Друга половина семестру
    if not content_div or not content_div.find_all('div', class_='view-grouping'):
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
        return {"Info": "❌ Не вдалося отримати дані."}

    schedule_data = {} 

    # --- Фільтр Підгруп ---
    def is_excluded_subgroup(text, current_subgroup):
        if not current_subgroup: return False
        ex_sub = str(3 - int(current_subgroup)) # Протилежна підгрупа
        # Шукаємо маркери протилежної групи: (2), підгр. 2, 2 п/г
        patterns = [f"\({ex_sub}\)", f"підгр\.\s*{ex_sub}", f"{ex_sub}\s*п/г", f"підгрупа\s*{ex_sub}"]
        
        text_lower = text.lower()
        for p in patterns:
            if re.search(p, text_lower, re.IGNORECASE):
                # Якщо знайдено (2), перевіряємо, чи немає поруч (1). 
                # Якщо є (1), то пара спільна, не видаляємо.
                our_sub = str(current_subgroup)
                if not re.search(f"\({our_sub}\)", text_lower): 
                    return True 
        return False

    # --- Фільтр Тижнів (CSS) ---
    def is_excluded_week(classes_list, current_filter):
        if not current_filter: return False # Якщо "Всі тижні" - показуємо все
        
        # Нормалізація класів у набір
        cls = set(classes_list)
        
        # Визначаємо, до якого тижня належить пара
        is_chys = 'chys' in cls or 'week_1' in cls or 'week1' in cls
        is_znam = 'znam' in cls or 'week_2' in cls or 'week2' in cls
        
        # Якщо пара має ознаки ТІЛЬКИ протилежного тижня -> видаляємо
        if current_filter == 'chys' and is_znam and not is_chys: return True
        if current_filter == 'znam' and is_chys and not is_znam: return True
        
        return False

    # === ПАРСИНГ ===
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
                    # 1. Фільтр тижнів (CSS)
                    if is_excluded_week(row.get('class', []), week_filter):
                        continue

                    num_header = row.find_previous('h3')
                    pair_num = num_header.get_text(strip=True) if num_header else "?"
                    
                    content = row.find('div', class_='group_content')
                    if not content: content = row
                    full_pair_text = content.get_text(separator=" ", strip=True).strip()

                    # 2. Фільтр підгруп (Текст)
                    if is_excluded_subgroup(full_pair_text, subgroup):
                        continue
                    
                    # Маркери для краси
                    safe_text = html.escape(full_pair_text)
                    classes = row.get('class', [])
                    week_mark = ""
                    if 'chys' in classes or 'week_1' in classes: week_mark = " <i>(чис.)</i>"
                    if 'znam' in classes or 'week_2' in classes: week_mark = " <i>(знам.)</i>"

                    day_text += f"⏰ <b>{pair_num} пара</b>{week_mark}\n📖 {safe_text}\n──────────────\n"
                    has_pairs = True
                
                if has_pairs:
                    schedule_data[day_name] = day_text

        # Fallback (Текстовий режим) - тут фільтри тижнів не працюють ідеально
        if not schedule_data:
            raw_text = content_div.get_text(separator="\n", strip=True)
            lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
            current_day = None
            temp_schedule = {}
            
            # Regex для пошуку дня, навіть якщо він "злипся" з іншим текстом
            day_pattern = re.compile(r'^(Понеділок|Вівторок|Середа|Четвер|П\'ятниця|Субота|Неділя|Пн|Вт|Ср|Чт|Пт|Сб|Нд)\b', re.IGNORECASE)

            for line in lines:
                match = day_pattern.match(line)
                if match:
                    current_day = get_standard_day_name(match.group(0))
                    if current_day and current_day not in temp_schedule:
                        temp_schedule[current_day] = []
                    
                    # Перевіряємо, чи є після дня номер пари (напр. "Пн 1 Математика")
                    remainder = line[len(match.group(0)):].strip()
                    if remainder and re.match(r'^[1-8]', remainder):
                         pair_num = remainder[0]
                         text = remainder[1:].strip()
                         temp_schedule[current_day].append({'num': pair_num, 'text': text})
                    continue
                
                # Пошук номера пари на початку рядка (1, 2...)
                if current_day and re.match(r'^[1-8][\.\)\s]', line):
                    pair_num = line[0]
                    text = line[1:].strip(" .)")
                    temp_schedule[current_day].append({'num': pair_num, 'text': text})
                    continue
                
                # Просто текст пари
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
            return {"Info": "📭 Розклад порожній."}

        return schedule_data

    except Exception as e:
        logger.error(f"Parser Error: {e}", exc_info=True)
        return {"Info": "⚠️ Технічна помилка."}


