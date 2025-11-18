import requests
from bs4 import BeautifulSoup
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "https://student.lpnu.ua"

def fetch_schedule_dict(group_name, semester="1", duration="1", subgroup=None):
    """
    Повертає словник: {'Понеділок': 'текст розкладу', 'Вівторок': ...}
    """
    schedule_url = f"{BASE_URL}/students_schedule"
    params = {
        "studygroup_abbrname": group_name,
        "semestr": semester,
        "semestrduration": duration
    }

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'
        }
        response = requests.get(schedule_url, params=params, headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        content_div = soup.find('div', class_='view-content')
        
        if not content_div:
            return None # Сигнал про помилку

        days = content_div.find_all('div', class_='view-grouping')
        schedule_data = {} # Тут будемо зберігати результат

        if not days:
            return {"Info": "Сайт повернув нестандартну структуру. Спробуйте пізніше."}

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
                    if f"підгр. {3-int(subgroup)}" in full_pair_text.lower() or \
                       f"підгрупа {3-int(subgroup)}" in full_pair_text.lower():
                        continue
                
                # Дизайн пари
                day_text += f"⏰ *{pair_num} пара*\n📖 {full_pair_text}\n──────────────\n"
                has_pairs = True
            
            if has_pairs:
                schedule_data[day_name] = day_text

        if not schedule_data:
            return {"Info": "🎉 Схоже, пар немає!"}

        return schedule_data

    except Exception as e:
        logger.error(f"Parser Error: {e}")
        return None


