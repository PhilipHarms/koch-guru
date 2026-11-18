# KochGuru: web app and Telegram bot in one service.
# Railway builds this file automatically when it is in the repository root.

# 1) Build the front end (Vite) to static files.
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# 2) Python service that serves the built front end and runs the bot.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY main.py ./
COPY koch_guru ./koch_guru
COPY --from=web /web/dist ./web/dist
RUN useradd --create-home --uid 1000 kochguru
USER kochguru
CMD ["python", "main.py"]
