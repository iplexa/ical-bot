# Базовый образ для сборки
FROM python:3.12-slim as builder

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Финальный образ
FROM python:3.12-slim

WORKDIR /app

# Копирование зависимостей и исходного кода
COPY --from=builder /root/.local /root/.local
COPY . .

# Настройка окружения
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1

# Запуск бота
CMD ["python", "main.py"]