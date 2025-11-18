import requests
from bs4 import BeautifulSoup
import logging
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "https://student.lpnu.ua"

# --- Функція екранування та визначення дня (без змін) ---
def escape_markdown(text):
    """
    Екранує всі MarkdownV2 символи, які можуть бути в назвах предметів.
    """
    text = re.sub(r'([.()\[\]-])', r'\\\1', text)
    text = re.sub(r'([~`>#=+|\{}!])', r'\\\1', text)
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
        # --- КРИТИЧНО ВАЖЛИВА ЗМІНА: Реалістичні заголовки ---
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7',
            'Connection': 'keep-alive',
        }
        
        # requests.get автоматично підтримує до 30 перенаправлень. Ми покладаємося на те,
        # що нові заголовки зламають цикл перенаправлень.
        response = requests.get(schedule_url, params=params, headers=headers, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        content_div = soup.find('div', class_='view-content')
        
        if not content_div:
            if "не знайдено" in soup.text.lower():
                return {"Info": f"❌ Групу **{group_name}** не знайдено."}
            return {"Info": "❌ Не вдалося отримати розклад. Сайт повернув незрозумілу відповідь."}

        schedule_data = {} 
        
        # --- СПРОБА 1: HTML Блоки ---
        days = content_div.find_all('div', class_='view-grouping')
        # ... (логіка обробки HTML блоків, залишена без змін)
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
                        excluded_subgroup = str(3 - int(subgroup))
                        if re.search(f"(підгр\. {excluded_subgroup})", full_pair_text, re.IGNORECASE) or \
                           re.search(f"(\({excluded_subgroup}\))", full_pair_text):
                            continue
                            
                    day_text += f"⏰ *{pair_num} пара*\n📖 {escape_markdown(full_pair_text)}\n──────────────\n"
                    has_pairs = True
                
                if has_pairs:
                    schedule_data[day_name] = day_text

        # --- СПРОБА 2: Текстовий парсинг ---
        if not schedule_data:
            # ... (логіка текстового парсингу, залишена без змін)
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
                    
                    if subgroup:
                        excluded_subgroup = str(3 - int(subgroup))
                        if re.search(f"(підгр\. {excluded_subgroup})", full_text, re.IGNORECASE) or \
                           re.search(f"(\({excluded_subgroup}\))", full_text):
                            continue
                    
                    escaped_text = escape_markdown(full_text)
                    
                    day_text += f"⏰ *{pair['num']} пара*\n📖 {escaped_text}\n──────────────\n"
                    has_pairs_in_day = True
                
                if has_pairs_in_day:
                    schedule_data[day] = day_text

        if not schedule_data:
            return {"Info": "📭 Розклад порожній (або вихідні)."}

        return schedule_data

    except requests.exceptions.TooManyRedirects:
        logger.error("Exceeded 30 redirects (Site blocking bot).")
        return {"Info": "🛑 Помилка. Сайт університету заблокував запит (захист від ботів). Спробуйте пізніше."}
    except Exception as e:
        logger.error(f"Parser Error: {e}", exc_info=True)
        return {"Info": "⚠️ Невідома помилка парсера."}

