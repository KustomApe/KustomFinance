# macOS (Homebrew) で WeasyPrint が pango 等を見つけられるようにする
export DYLD_FALLBACK_LIBRARY_PATH := /opt/homebrew/lib:$(DYLD_FALLBACK_LIBRARY_PATH)
TAILWIND := bin/tailwindcss
TAILWIND_VERSION := v4.1.18

.PHONY: setup dev serve css css-watch migrate test lint tailwind ocr-data

setup: tailwind ocr-data
	uv sync
	uv run manage.py migrate
	$(MAKE) css

tailwind:
	@test -x $(TAILWIND) || ( mkdir -p bin && \
	  curl -sSfL -o $(TAILWIND) https://github.com/tailwindlabs/tailwindcss/releases/download/$(TAILWIND_VERSION)/tailwindcss-macos-arm64 && \
	  chmod +x $(TAILWIND) && xattr -c $(TAILWIND) && codesign --force -s - $(TAILWIND) )

css:
	$(TAILWIND) -i static/src/app.css -o static/css/app.css --minify

css-watch:
	$(TAILWIND) -i static/src/app.css -o static/css/app.css --watch

dev:
	uv run manage.py runserver 0.0.0.0:8000

# 社内LAN向け本番起動
serve: css
	uv run manage.py collectstatic --noinput
	uv run gunicorn config.wsgi -b 0.0.0.0:8000 -w 3

migrate:
	uv run manage.py migrate

test:
	uv run pytest

lint:
	uv run ruff check . && uv run ruff format --check .

# レシートOCR用の日本語データ（Tesseract）。Homebrew の tesseract に日本語が入っていない場合に使う
TESSDATA := bin/tessdata
ocr-data:
	@test -f $(TESSDATA)/jpn.traineddata || ( mkdir -p $(TESSDATA) && \
	  curl -sSfL -o $(TESSDATA)/jpn.traineddata https://github.com/tesseract-ocr/tessdata_best/raw/main/jpn.traineddata && \
	  curl -sSfL -o $(TESSDATA)/eng.traineddata https://github.com/tesseract-ocr/tessdata_best/raw/main/eng.traineddata )
