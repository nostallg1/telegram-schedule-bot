import requests
from bs4 import BeautifulSoup
import logging
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "https://student.lpnu.ua"

# ... (весь код get_standard_day_name, DAY_MAP, escape_markdown без змін)

# ... (весь код get_standard_day_name, DAY_MAP, escape_markdown без змін)
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
    # ... (код без змін)
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
        
        
        # --- ФУНКЦІЯ ФІЛЬТРАЦІЇ ПАР (Додано) ---
        def is_pair_for_excluded_subgroup(text, current_subgroup):
            """
            Перевіряє, чи пара призначена для протилежної підгрупи.
            Наприклад, якщо обрано '1', шукаємо '2'.
            """
            if not current_subgroup:
                return False # Не фільтруємо, якщо обрано "Вся група"

            # Визначаємо підгрупу, яку потрібно виключити
            excluded_subgroup = str(3 - int(current_subgroup)) 
            
            # Варіанти, які вказують на ВИКЛЮЧЕНУ підгрупу:
            patterns = [
                f"(підгр\. {excluded_subgroup})",   # (підгр. 2)
                f"(підгрупа {excluded_subgroup})",  # (підгрупа 2)
                f"(\({excluded_subgroup}\))",       # (2) - Тільки цифра в дужках
                f"({excluded_subgroup}\s*п/г)",     # 2 п/г
                f"({excluded_subgroup}\s*п/гр)",    # 2 п/гр
            ]
            
            # Якщо знайдено будь-який з цих патернів, повертаємо True (цю пару треба пропустити)
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    # Важливо: якщо в тексті є (1) І (2), то це для ВСІЄЇ групи.
                    # Перевіряємо, чи немає одночасно обох підгруп
                    if re.search(f"\([1-2]\)", text) and re.search(f"\([1-2]\)", text.replace(f"({excluded_subgroup})", "")):
                        return False # Якщо є обидві, не фільтруємо

                    return True
            
            # Якщо пара не містить номерів підгруп взагалі, припускаємо, що вона для ВСІЄЇ групи
            # Якщо пара має лише (1) і ми обрали (2) — це нормально.
            
            # Спеціальна перевірка: якщо пара має лише *нашу* підгрупу (1), 
            # але ми обрали протилежну (2), то ми її пропускаємо.
            our_sub = str(current_subgroup)
            
            # Якщо в тексті Є позначка (1) і НЕМАЄ позначки (2), і ми обрали 2-гу
            if re.search(f"\({our_sub}\)", text) and not re.search(f"\({excluded_subgroup}\)", text):
                 if our_sub != current_subgroup:
                    return True

            return False
        # --- КІНЕЦЬ ФУНКЦІЇ ФІЛЬТРАЦІЇ ---


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

                    # ВІДТІКАННЯ: Нова, надійна перевірка
                    if is_pair_for_excluded_subgroup(full_pair_text, subgroup):
                        continue

                    day_text += f"⏰ *{pair_num} пара*\n📖 {escape_markdown(full_pair_text)}\n──────────────\n"
                    has_pairs = True
                
                if has_pairs:
                    schedule_data[day_name] = day_text

        # --- СПРОБА 2: Текстовий парсинг ---
        if not schedule_data:
            # ... (логіка текстового парсингу)
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

            # Формуємо фінальний результат
            for day, pairs in temp_schedule.items():
                day_text = f"📅 *{day}* ({group_name})\n\n"
                has_pairs_in_day = False
                
                for pair in pairs:
                    full_text = pair['text']
                    
                    # ВІДТІКАННЯ: Нова, надійна перевірка
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
        logger.error(f"Parser Error: {e}")
        return {"Info": "⚠️ Помилка парсера."}

