import requests
from bs4 import BeautifulSoup
import logging
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "https://student.lpnu.ua"

def normalize_text(text):
    """
    Замінює англійські літери, схожі на українські, на українські.
    Видаляє зайві пробіли.
    """
    if not text: return ""
    
    # Таблиця замін (Латиниця -> Кирилиця)
    replacements = {
        'A': 'А', 'B': 'В', 'C': 'С', 'E': 'Е', 'H': 'Н', 'I': 'І', 'K': 'К',
        'M': 'М', 'O': 'О', 'P': 'Р', 'T': 'Т', 'X': 'Х', 'Y': 'У',
        'a': 'а', 'c': 'с', 'e': 'е', 'i': 'і', 'k': 'к', 'o': 'о', 'p': 'р', 'x': 'х'
    }
    
    clean = text.strip()
    for lat, cyr in replacements.items():
        clean = clean.replace(lat, cyr)
    
    return clean

def fetch_schedule_dict(group_name, semester="1", duration="1", subgroup=None):
    schedule_url = f"{BASE_URL}/students_schedule"
    params = {
        "studygroup_abbrname": group_name,
        "semestr": semester,
        "semestrduration": duration
    }

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0'
        }
        response = requests.get(schedule_url, params=params, headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        content_div = soup.find('div', class_='view-content')
        
        if not content_div:
            if "не знайдено" in soup.text.lower():
                return {"Info": f"❌ Групу **{group_name}** не знайдено."}
            return {"Info": "❌ Помилка: Не вдалося отримати розклад."}

        schedule_data = {} 
        
        # Список днів для Regex (враховуємо крапки, пробіли і повні назви)
        # (Пн|Понеділок|Вівторок|Вт|...)
        days_pattern = r'^(Пн|Понеділок|Вт|Вівторок|Ср|Середа|Чт|Четвер|Пт|П\'ятниця|Пятниця|Сб|Субота|Нд|Неділя)\.?$'

        # --- СПРОБА 1: HTML структура ---
        days = content_div.find_all('div', class_='view-grouping')
        if days:
            for day_block in days:
                header = day_block.find('span', class_='view-grouping-header')
                day_name_raw = header.get_text(strip=True) if header else "Інше"
                day_name = normalize_text(day_name_raw) # Чистимо назву
                
                day_text = f"📅 *{day_name}* ({group_name})\n\n"
                has_pairs = False
                
                rows = day_block.find_all('div', class_='stud_schedule')
                for row in rows:
                    num_header = row.find_previous('h3')
                    pair_num = num_header.get_text(strip=True) if num_header else "?"
                    
                    content = row.find('div', class_='group_content')
                    if not content: content = row
                    full_pair_text = normalize_text(content.get_text(separator=" ", strip=True))

                    if subgroup:
                        if f"підгр. {3-int(subgroup)}" in full_pair_text.lower() or \
                           f"підгрупа {3-int(subgroup)}" in full_pair_text.lower():
                            continue

                    day_text += f"⏰ *{pair_num} пара*\n📖 {full_pair_text}\n──────────────\n"
                    has_pairs = True
                
                if has_pairs:
                    schedule_data[day_name] = day_text

        # --- СПРОБА 2: Текстовий парсинг (Backup) ---
        if not schedule_data:
            raw_text = content_div.get_text(separator="\n", strip=True)
            raw_text = normalize_text(raw_text) # Чистимо весь текст від латиниці
            
            lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
            
            current_day = None
            current_pair = None
            
            temp_schedule = {}

            for line in lines:
                # 1. Шукаємо день тижня за допомогою Regex
                if re.match(days_pattern, line, re.IGNORECASE):
                    current_day = line.replace(".", "") # Прибираємо можливу крапку
                    temp_schedule[current_day] = []
                    current_pair = None
                    continue
                
                # 2. Шукаємо номер пари (просто цифра 1-8)
                if current_day and re.match(r'^[1-8]$', line):
                    current_pair = line
                    temp_schedule[current_day].append({'num': current_pair, 'text': ""})
                    continue

                # 3. Текст пари
                if current_day and current_pair:
                    if temp_schedule[current_day]:
                        last = temp_schedule[current_day][-1]
                        last['text'] += ("\n" if last['text'] else "") + line

            # Формуємо результат
            for day, pairs in temp_schedule.items():
                day_text = f"📅 *{day}* ({group_name})\n\n"
                has_pairs_in_day = False
                
                for pair in pairs:
                    full_text = pair['text']
                    if subgroup:
                        if f"підгр. {3-int(subgroup)}" in full_text.lower() or \
                           f"підгрупа {3-int(subgroup)}" in full_text.lower():
                            continue
                    
                    day_text += f"⏰ *{pair['num']} пара*\n📖 {full_text}\n──────────────\n"
                    has_pairs_in_day = True
                
                if has_pairs_in_day:
                    schedule_data[day] = day_text

        if not schedule_data:
            return {"Info": "📭 Розклад порожній."}

        return schedule_data

    except Exception as e:
        logger.error(f"Parser Error: {e}")
        return {"Info": "⚠️ Помилка парсера."}

