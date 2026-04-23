FROM python:3.14-slim-bookworm

WORKDIR /app

# Prevent Python from buffering logs
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]