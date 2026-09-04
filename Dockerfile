FROM python:3.12-slim-bookworm

# Ustawienia środowiska Pythona
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TEMP_DIR=/tmp/bot_media

# Instalacja ExifTool, FFmpeg oraz certyfikatów CA
RUN apt-get update && apt-get install -y --no-install-recommends \
    libimage-exiftool-perl \
    ffmpeg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Utworzenie nieuprzywilejowanego użytkownika dla bezpieczeństwa
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app /tmp/bot_media && \
    chown -R appuser:appuser /app /tmp/bot_media

WORKDIR /app

# Instalacja zależności Pythona
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopiowanie kodu źródłowego
COPY src/ ./src/

# Przełączenie na użytkownika bez uprawnień roota
USER appuser

CMD ["python", "-m", "src.main"]
