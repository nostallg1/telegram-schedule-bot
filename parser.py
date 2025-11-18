import requests
from bs4 import BeautifulSoup
import logging
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "https://student.lpnu.ua"

def fetch_schedule_dict(group_name, semester="1", duration="1", subgroup=None):
    """
    Повертає словник розкладу.
    Вміє парсити як стандартну верстку, так і "сирий" текст.
    """
    schedule_url = f"{BASE_URL}/students_schedule"
    params = {
        "studygroup_abbrname": group_name,
        "semestr": semester,
        "semestrduration": duration
    }

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(schedule_url, params=params, headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        content_div = soup.find('div', class_='view-content')
        
        if not content_div:
            if "не знайдено" in soup.text.lower():
                return {"Info": f"❌ Групу **{group_name}** не знайдено."}
            return {"Info": "❌ Не вдалося отримати дані."}

        schedule_data = {} 

        # --- СПРОБА 1: Стандартна структура (view-grouping) ---
        days = content_div.find_all('div', class_='view-grouping')
        if days:
            for day_block in days:
                header = day_block.find('span', class_='view-grouping-header')
                day_name = header.get_text(strip=True) if header else "Інше"
                
                day_text = f"📅 *{day_name}* ({group_name})\n\n"
                has_pairs = False
                
                rows = day_block.find_all('div', class_='stud_schedule')
                for row in rows:
                    num_header = row.find_previous('h3')
                    pair_num = num_header.get_text(strip=True) if num_header else "?"
                    
                    content = row.find('div', class_='group_content')
                    if not content: content = row
                    full_pair_text = content.get_text(separator=" ", strip=True)

                    if subgroup:
                        if f"підгр. {3-int(subgroup)}" in full_pair_text.lower() or \
                           f"підгрупа {3-int(subgroup)}" in full_pair_text.lower():
                            continue

                    day_text += f"⏰ *{pair_num} пара*\n📖 {full_pair_text}\n──────────────\n"
                    has_pairs = True
                
                if has_pairs:
                    schedule_data[day_name] = day_text

        # --- СПРОБА 2: Парсинг "сирого" тексту (Regex) ---
        # Якщо Спроба 1 нічого не дала, але текст є
        if not schedule_data:
            raw_text = content_div.get_text(separator="\n", strip=True)
            
            # Список днів для пошуку
            days_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
            
            # Розбиваємо текст на рядки
            lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
            
            current_day = None
            current_pair = None
            buffer_pair_text = []
            
            # Словник для проміжного зберігання: {'Пн': [{'num': '1', 'text': 'Матема...'}]}
            temp_schedule = {}

            for line in lines:
                # 1. Чи це День тижня? (Пн, Вт...)
                if line in days_names:
                    current_day = line
                    temp_schedule[current_day] = []
                    current_pair = None
                    continue
                
                # 2. Чи це Номер пари? (1, 2, 3...)
                # Перевіряємо, чи рядок складається тільки з однієї цифри 1-9
                if current_day and re.match(r'^[1-8]$', line):
                    current_pair = line
                    # Додаємо нову пару в список цього дня
                    temp_schedule[current_day].append({'num': current_pair, 'text': ""})
                    continue

                # 3. Це текст пари
                if current_day and current_pair:
                    # Дописуємо текст до останньої пари поточного дня
                    if temp_schedule[current_day]:
                        last_pair_idx = len(temp_schedule[current_day]) - 1
                        # Додаємо пробіл, якщо там вже щось є
                        if temp_schedule[current_day][last_pair_idx]['text']:
                            temp_schedule[current_day][last_pair_idx]['text'] += "\n" + line
                        else:
                            temp_schedule[current_day][last_pair_idx]['text'] = line

            # Формуємо фінальний гарний словник
            for day, pairs in temp_schedule.items():
                day_text = f"📅 *{day}* ({group_name})\n\n"
                has_pairs_in_day = False
                
                for pair in pairs:
                    full_text = pair['text']
                    
                    # Фільтрація підгрупи (те ж саме, що і вище)
                    if subgroup:
                        if f"підгр. {3-int(subgroup)}" in full_text.lower() or \
                           f"підгрупа {3-int(subgroup)}" in full_text.lower():
                            continue
                    
                    day_text += f"⏰ *{pair['num']} пара*\n📖 {full_text}\n──────────────\n"
                    has_pairs_in_day = True
                
                if has_pairs_in_day:
                    schedule_data[day] = day_text

        # --- ФІНАЛ ---
        if not schedule_data:
             return {"Info": "📭 Розклад порожній (або вихідні)."}

        return schedule_data

    except Exception as e:
        logger.error(f"Parser Error: {e}")
        return {"Info": "⚠️ Технічна помилка парсера."}
