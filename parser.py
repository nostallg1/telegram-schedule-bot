import requests
from bs4 import BeautifulSoup
import logging
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "https://student.lpnu.ua"

# --- ФУНКЦІЯ ЕКРАНУВАННЯ (ОНОВЛЕНО) ---
def escape_markdown(text):
    """
    Екранує всі MarkdownV2 символи, які можуть бути в назвах предметів.
    Символи: _ * [ ] ( ) ~ ` > # + - = | { } . !
    """
    # Екрануємо ВСІ спецсимволи MarkdownV2, крім тих, що ми використовуємо (напр., * для жирного)
    # Оскільки ми використовуємо * для жирного і не використовуємо _, ми екрануємо всі інші
    chars_to_escape = r'[\[\]()~`>#+=|{}.!]'
    
    # Використовуємо ретельну заміну для дефісів та крапок, якщо вони є.
    # Заміна символів: . - ( ) | [ ]
    text = re.sub(r'([.()\[\]-])', r'\\\1', text)
    
    # Екрануємо інші спецсимволи
    text = re.sub(r'([~`>#=+|\{}!])', r'\\\1', text)

    return text.replace('_', r'\_').replace('*', r'\*')


# --- Функції визначення дня (без змін) ---
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
        
        # --- СПРОБА 1: HTML Блоки ---
        days = content_div.find_all('div', class_='view-grouping')
        if days:
            for day_block in days:
                header = day_block.find('span', class_='view-grouping-header')
                raw_day = header.get_text(strip=True) if header else "Інше"
                day_name = get_standard_day_name(raw_day)
                if not day_name: continue 
                
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
                            
                    # Екранування тексту пари
                    escaped_text = escape_markdown(full_pair_text)

                    day_text += f"⏰ *{pair_num} пара*\n📖 {escaped_text}\n──────────────\n"
                    has_pairs = True
                
                if has_pairs:
                    schedule_data[day_name] = day_text

        # --- СПРОБА 2: Текстовий парсинг ---
        if not schedule_data:
            raw_text = content_div.get_text(separator="\n", strip=True)
            lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
            
            current_day = None
            temp_schedule = {}
            day_start_pattern = re.compile(r'^(Понеділок|Вівторок|Середа|Четвер|П\'ятниця|Субота|Неділя|Пн|Вт|Ср|Чт|Пт|Сб|Нд)\b', re.IGNORECASE)

            for line in lines:
                detected_match = day_start_pattern.match(line)
                if detected_match:
                    day_part = detected_match.group(0) # Виправлено: отримуємо day_part тут
                    detected_day = get_standard_day_name(day_part)
                    
                    if detected_day:
                        current_day = detected_day
                        if current_day not in temp_schedule:
                            temp_schedule[current_day] = []
                        
                        remainder = line[len(day_part):].strip() # Тепер day_part визначена
                        if remainder and re.match(r'^[1-8]$', remainder.split()[0]):
                            pair_num = remainder.split()[0]
                            temp_schedule[current_day].append({'num': pair_num, 'text': remainder[len(pair_num):].strip()})
                        continue

                if current_day and re.match(r'^[1-8]$', line):
                    temp_schedule[current_day].append({'num': line, 'text': ""})
                    continue

                if current_day and current_day in temp_schedule and temp_schedule[current_day]:
                    last_pair = temp_schedule[current_day][-1]
                    last_pair['text'] += ("\n" if last_pair['text'] else "") + line

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
                    
                    escaped_text = escape_markdown(full_text)
                    
                    day_text += f"⏰ *{pair['num']} пара*\n📖 {escaped_text}\n──────────────\n"
                    has_pairs_in_day = True
                
                if has_pairs_in_day:
                    schedule_data[day] = day_text

        if not schedule_data:
            return {"Info": "📭 Розклад порожній (або вихідні)."}

        return schedule_data

    except Exception as e:
        logger.error(f"Parser Error: {e}")
        return {"Info": "⚠️ Помилка парсера."}
