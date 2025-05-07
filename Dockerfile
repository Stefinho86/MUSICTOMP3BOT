FROM python:3.12-slim

# Installa ffmpeg e pulisci la cache per mantenere l'immagine leggera
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

# Installa le dipendenze Python
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Avvia il bot
CMD ["python", "bot.py"]