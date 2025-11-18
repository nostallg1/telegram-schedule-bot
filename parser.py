import requests
from bs4 import BeautifulSoup
import logging
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "https://student.lpnu.ua"

def get_standard_day_name(line):
    """
    Перетворює будь-який варіант написання дня у стандартний ключ.
    Наприклад: "пн", "Mon", "Понеділок." -> "Понеділок"
    """
    # Видаляємо все зайве і переводимо в нижній регістр
    clean_line = re.sub(r'[^\w]', '', line).lower() 
    
    # Карта відповідності
    days_map = {
        "Понеділок": ["пн", "пон", "mon"],
        "Вівторок":  ["вт", "вів", "bt", "biв", "vt", "tue"],
        "Середа":    ["ср", "сер", "cp", "cep", "wed"],
        "Четвер":    ["чт", "чет", "thu"],
        "П'ятниця":  ["пт", "пят", "fri"],
        "Субота":    ["сб", "суб", "sat"],
        "Неділя":    ["нд", "нед", "sun"]
    }
    
    for standard_name, variants in days_map.items():
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
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(schedule_url, params=params, headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        content_div = soup.find('div', class_='view-content')
        
        if not content_div:
            if "не знайдено" in soup.text.lower():
                return {"Info": f"❌ Групу **{group_name}** не знайдено."}
            return {"Info": "❌ Не вдалося отримати розклад."}

        schedule_data = {} 

        # --- ВАРІАНТ 1: HTML Блоки ---
        days = content_div.find_all('div', class_='view-grouping')
        if days:
            for day_block in days:
                header = day_block.find('span', class_='view-grouping-header')
                raw_day = header.get_text(strip=True) if header else "Інше"
                
                # НОРМАЛІЗАЦІЯ НАЗВИ ДНЯ
                day_name = get_standard_day_name(raw_day)
                if not day_name: continue # Пропускаємо, якщо не змогли визначити день
                
                day_text = f"📅 *{day_name}* ({group_name})\n\n"
                has_pairs = False
                
                rows = day_block.find_all('div', class_='stud_schedule')
                for row in rows:
                    num_header = row.find_previous('h3')
                    pair_num = num_header.get_text(strip=True) if num_header else "?"
                    
                    content = row.find('div', class_='group_content')
                    if not content: content = row
                    full_pair_text = content.get_text(separator=" ", strip=True).strip()

                    if subgroup:
                        if f"підгр. {3-int(subgroup)}" in full_pair_text.lower() or \
                           f"підгрупа {3-int(subgroup)}" in full_pair_text.lower():
                            continue

                    day_text += f"⏰ *{pair_num} пара*\n📖 {full_pair_text}\n──────────────\n"
                    has_pairs = True
                
                if has_pairs:
                    schedule_data[day_name] = day_text

        # --- ВАРІАНТ 2: Текстовий парсинг ---
        if not schedule_data:
            raw_text = content_div.get_text(separator="\n", strip=True)
            lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
            
            current_day = None
            temp_schedule = {}

            for line in lines:
                detected_day = get_standard_day_name(line)
                if detected_day:
                    current_day = detected_day
                    if current_day not in temp_schedule:
                        temp_schedule[current_day] = []
                    continue
                
                if current_day and re.match(r'^[1-8]$', line):
                    temp_schedule[current_day].append({'num': line, 'text': ""})
                    continue

                if current_day and current_day in temp_schedule and temp_schedule[current_day]:
                    last_pair = temp_schedule[current_day][-1]
                    last_pair['text'] += ("\n" if last_pair['text'] else "") + line

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
            return {"Info": "📭 Розклад порожній (або вихідні)."}

        return schedule_data

    except Exception as e:
        logger.error(f"Parser Error: {e}")
        return {"Info": "⚠️ Помилка парсера."}


