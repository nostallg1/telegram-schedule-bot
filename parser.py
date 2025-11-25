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
    return text

def make_request(group_name, semester, duration):
    schedule_url = f"{BASE_URL}/students_schedule"
    # Формуємо параметри
    params = {
        "studygroup_abbrname": group_name,
        "semestr": semester,
        "semestrduration": duration
    }
    
    if SCRAPER_API_KEY:
        # Спрощуємо запит до ScraperAPI
        # Вимикаємо keep_headers, щоб ScraperAPI сам підібрав правильні заголовки
        payload = {
            'api_key': SCRAPER_API_KEY,
            'url': schedule_url + '?' + requests.compat.urlencode(params),
            'render': 'true' # JS rendering залишаємо, він корисний
        }
        logger.info(f"ScraperAPI URL: {payload['url']}") # Логуємо URL для перевірки
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

def fetch_schedule_dict(group_name, semester="1", duration="1", subgroup=None, week_filter=None):
    
    # КРОК 1: Запит
    try:
        response = make_request(group_name, semester, "1")
        if response.status_code != 200:
             return {"Info": f"❌ Помилка HTTP {response.status_code}."}
    except Exception as e:
        logger.error(f"Network error: {e}")
        return {"Info": "❌ Помилка з'єднання."}

    soup = BeautifulSoup(response.text, 'html.parser')
    content_div = soup.find('div', class_='view-content')

    # --- ДІАГНОСТИКА (Що бачить бот?) ---
    # Якщо контент порожній або немає днів, спробуємо зрозуміти чому
    days = []
    if content_div:
        days = content_div.find_all('div', class_='view-grouping')
    
    if not days:
        # Якщо це не стандартний розклад, це може бути помилка сайту
        if not content_div:
            # Перевіряємо, чи це не сторінка захисту
            page_text = soup.get_text(separator=" ", strip=True)
            if "security" in page_text.lower() or "challenge" in page_text.lower():
                return {"Info": "🛡 Бот натрапив на захист (Cloudflare). Спробуйте ще раз через хвилину."}
            if "не знайдено" in page_text.lower():
                return {"Info": f"❌ Сайт каже: Групу <b>{html.escape(group_name)}</b> не знайдено."}
            
            # Повертаємо шматок тексту для налагодження
            return {"Info": f"⚠️ Дивна відповідь сайту (немає view-content). Початок тексту:\n{html.escape(page_text[:200])}"}
        
        # Якщо content_div є, але днів немає
        raw_text = content_div.get_text(separator="\n", strip=True)
        if len(raw_text) < 20:
             return {"Info": f"📭 Сайт повернув порожню таблицю для <b>{group_name}</b>."}
        
        # Якщо текст є, але ми його не розпізнали - покажемо його!
        return {"Info": f"⚠️ Не можу розпізнати формат. Ось що бачу:\n\n{html.escape(raw_text[:500])}"}

    # --- ЯКЩО ВСЕ ОК, ПАРСИМО ---
    schedule_data = {} 

    # ... (код фільтрації is_pair_for_excluded_subgroup - такий самий, як був) ...
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

    try:
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

        if not schedule_data:
            return {"Info": "📭 Розклад порожній (можливо, фільтри приховали всі пари)."}

        return schedule_data

    except Exception as e:
        logger.error(f"Parser Logic Error: {e}", exc_info=True)
        return {"Info": f"⚠️ Помилка коду: {e}"}
        


