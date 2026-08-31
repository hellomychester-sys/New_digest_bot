FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Данные (state.json со списком тем, контекстом и chat_id) сохраняются в /app/data —
# смонтируйте эту папку как volume, чтобы не терять темы при пересборке контейнера.

CMD ["python", "main.py"]
