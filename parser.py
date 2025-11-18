import requests
from bs4 import BeautifulSoup
import logging
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "https://student.lpnu.ua"

def fetch_schedule_dict(group_name, semester="1", duration="1", subgroup=None):
    """
    Повертає словник розкладу або повідомлення про помилку.
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
            # Якщо немає контенту, перевіряємо, чи не повернув сайт помилку "не знайдено"
            if "не знайдено" in soup.text.lower():
                return {"Info": f"❌ Групу **{group_name}** не знайдено.\nСпробуйте ввести точну назву (напр. КН-101)."}
            return {"Info": "⚠️ Не вдалося отримати дані. Можливо, сайт університету не відповідає."}

        # Спробуємо знайти дні (стандартна структура)
        days = content_div.find_all('div', class_='view-grouping')
        schedule_data = {} 

        # ВАРІАНТ 1: Стандартна структура (блоки view-grouping)
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

                    # Фільтрація підгрупи
                    if subgroup:
                        # Якщо пара явно для іншої підгрупи -> пропускаємо
                        # (підгр. 1) або (1) або [1]
                        if f"підгр. {3-int(subgroup)}" in full_pair_text.lower() or \
                           f"підгрупа {3-int(subgroup)}" in full_pair_text.lower():
                            continue

                    day_text += f"⏰ *{pair_num} пара*\n📖 {full_pair_text}\n──────────────\n"
                    has_pairs = True
                
                if has_pairs:
                    schedule_data[day_name] = day_text

        # ВАРІАНТ 2: Якщо днів немає, але є текст (нестандартна структура)
        if not schedule_data:
            raw_text = content_div.get_text(separator="\n", strip=True)
            # Якщо тексту мало, то розклад просто порожній
            if len(raw_text) < 50:
                 return {"Info": f"📭 Розклад для **{group_name}** (підгр. {subgroup if subgroup else 'всі'}) порожній."}
            
            # Якщо тексту багато, повертаємо його як "Загальний розклад"
            # Це милиця для випадків, коли сайт ламає верстку
            clean_text = "\n".join([line for line in raw_text.split('\n') if line.strip()])
            return {"Info": f"⚠️ Сайт повернув нестандартний вигляд, ось що вдалося дістати:\n\n{clean_text[:3500]}"} # Обрізаємо, щоб не перевищити ліміт Telegram

        return schedule_data

    except Exception as e:
        logger.error(f"Parser Error: {e}")
        return {"Info": "⚠️ Сталася технічна помилка при обробці сторінки."}

