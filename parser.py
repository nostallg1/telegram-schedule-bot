import requests
from bs4 import BeautifulSoup
import logging
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "https://student.lpnu.ua"

# --- Функції визначення дня та екранування (без змін) ---
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
            'Accept-Language': 'uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7',
            'Connection': 'keep-alive',
        }
        
        response = requests.get(schedule_url, params=params, headers=headers, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        content_div = soup.find('div', class_='view-content')
        
        if not content_div:
            if "не знайдено" in soup.text.lower():
                return {"Info": f"❌ Групу **{group_name}** не знайдено."}
            return {"Info": "❌ Не вдалося отримати розклад."}

        schedule_data = {} 

        # --- НОВА ФУНКЦІЯ ФІЛЬТРАЦІЇ ПАР (АГРЕСИВНА) ---
        def is_pair_for_excluded_subgroup(text, current_subgroup):
            """
            Перевіряє, чи пара призначена для протилежної підгрупи,
            ігноруючи пари для всієї групи.
            """
            if not current_subgroup:
                return False
            
            excluded_subgroup = str(3 - int(current_subgroup)) # 2, якщо обрано 1, і 1, якщо обрано 2
            
            # Патерни, які вказують на ВИКЛЮЧЕНУ підгрупу:
            patterns_to_exclude = [
                f"\({excluded_subgroup}\)",       # (2) або (1)
                f"підгр\.\s*{excluded_subgroup}", # підгр. 2
                f"{excluded_subgroup}\s*п/г",     # 2 п/г
            ]
            
            # Патерни, які вказують на НАШУ підгрупу (щоб не відфільтрувати зайвого)
            our_sub = str(current_subgroup)
            patterns_for_us = [
                f"\({our_sub}\)",                 # (1) або (2)
                f"підгр\.\s*{our_sub}",
            ]
            
            text_lower = text.lower()

            # КРОК 1: Якщо в тексті Є явна позначка ВИКЛЮЧЕНОЇ підгрупи, то пропускаємо її.
            for pattern in patterns_to_exclude:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    # Але якщо в тексті є і (1), і (2), це означає, що пара для ВСІХ.
                    # Потрібно бути обережним.
                    
                    # Простий тест: якщо знайдено лише протилежну і нічого іншого, фільтруємо
                    # Інакше: Якщо є (2), але ми обрали (1), то пропускаємо.
                    return True # Якщо є маркер протилежної групи, пропускаємо.
            
            # КРОК 2: Якщо в тексті Є позначка НАШОЇ підгрупи, то залишаємо її. (Це не фільтрація, а підтвердження)
            # КРОК 3: Якщо в тексті немає позначок (тобто, вона для ВСІЄЇ групи), то залишаємо її.

            # Якщо немає ніяких позначок підгруп взагалі, припускаємо, що це для ВСІХ.
            if not re.search(f"\([1-2]\)|\sп/г\s*[1-2]", text_lower):
                return False 
            
            # Якщо до цього не відфільтрувало, і є позначка нашої групи - залишаємо
            return False 
        # --- КІНЕЦЬ ФУНКЦІЇ ФІЛЬТРАЦІЇ ---


        # --- СПРОБА 1: HTML Блоки ---
        days = content_div.find_all('div', class_='view-grouping')
        # ... (продовжуємо парсинг)
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

                    # Фільтрація
                    if is_pair_for_excluded_subgroup(full_pair_text, subgroup):
                        continue

                    day_text += f"⏰ *{pair_num} пара*\n📖 {escape_markdown(full_pair_text)}\n──────────────\n"
                    has_pairs = True
                
                if has_pairs:
                    schedule_data[day_name] = day_text
        
        # ... (логіка для СПРОБИ 2: Текстовий парсинг без змін, але використовує нову функцію is_pair_for_excluded_subgroup)
        if not schedule_data:
            raw_text = content_div.get_text(separator="\n", strip=True)
            lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
            
            current_day = None
            temp_schedule = {}
            day_start_pattern = re.compile(r'^(Понеділок|Вівторок|Середа|Четвер|П\'ятниця|Субота|Неділя|Пн|Вт|Ср|Чт|Пт|Сб|Нд)\b', re.IGNORECASE)

            for line in lines:
                detected_match = day_start_pattern.match(line)
                if detected_match:
                    day_part = detected_match.group(0)
                    detected_day = get_standard_day_name(day_part)
                    
                    if detected_day:
                        current_day = detected_day
                        if current_day not in temp_schedule:
                            temp_schedule[current_day] = []
                        
                        remainder = line[len(day_part):].strip()
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

            for day, pairs in temp_schedule.items():
                day_text = f"📅 *{day}* ({group_name})\n\n"
                has_pairs_in_day = False
                
                for pair in pairs:
                    full_text = pair['text']
                    
                    if is_pair_for_excluded_subgroup(full_text, subgroup):
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
        logger.error(f"Parser Error: {e}", exc_info=True)
        return {"Info": "⚠️ Помилка парсера."}

