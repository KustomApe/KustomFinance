FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_PROJECT_ENVIRONMENT=/opt/venv
# WeasyPrint の依存ライブラリと日本語フォント、レシートOCR（Tesseract 日本語・ffmpeg）
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-noto-cjk curl postgresql-client \
      tesseract-ocr tesseract-ocr-jpn ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN ARCH=$(uname -m | sed 's/x86_64/x64/;s/aarch64/arm64/') \
    && curl -sSfL -o /usr/local/bin/tailwindcss \
       https://github.com/tailwindlabs/tailwindcss/releases/download/v4.1.18/tailwindcss-linux-$ARCH \
    && chmod +x /usr/local/bin/tailwindcss \
    && tailwindcss -i static/src/app.css -o static/css/app.css --minify \
    && SECRET_KEY=build DATABASE_URL=sqlite:// /opt/venv/bin/python manage.py collectstatic --noinput

EXPOSE 8000
CMD ["sh", "-c", "/opt/venv/bin/python manage.py migrate --noinput && /opt/venv/bin/gunicorn config.wsgi -b 0.0.0.0:8000 -w 3"]
