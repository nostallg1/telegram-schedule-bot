FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# TELEGRAM_TOKEN (and optionally SCRAPER_API_KEY) are passed as environment variables at run time
CMD ["python", "bot.py"]
