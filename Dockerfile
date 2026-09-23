# ── Стадия 1: сборка веб-консоли менеджеров (React + Vite) ──
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


# ── Стадия 2: приложение ─────────────────────────────────────
# Use Python 3.10 slim image as base
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies
# ffmpeg — перекодирование голосовых из консоли: браузер пишет WebM (Chrome,
# Firefox) или MP4 (Safari), а WhatsApp как голосовое принимает только OGG/Opus.
RUN apt-get update && apt-get install -y \
    curl \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 - \
    && ln -s /root/.local/bin/poetry /usr/local/bin/poetry

# Copy dependency files
COPY pyproject.toml poetry.lock ./

# Configure poetry to not create a virtual environment
RUN poetry config virtualenvs.create false

# Install dependencies from locked versions
RUN poetry install --only main --no-root --no-interaction --no-ansi

# Install additional packages not managed by poetry lock
RUN pip install --no-cache-dir aiogram httpx openpyxl

# Copy the rest of the application
COPY . .

# Собранная консоль кладётся в /srv — ВНЕ /app, который перекрывается
# bind-mount'ом из docker-compose (volumes: - .:/app).
COPY --from=frontend /build/dist /srv/console
ENV CONSOLE_DIST_DIR=/srv/console

# Add src directory to PYTHONPATH
ENV PYTHONPATH=/app

# Expose the port the app runs on
EXPOSE 8000

# Command to run the application
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
