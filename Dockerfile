FROM python:3.12-slim

# Installa ffmpeg
RUN apt-get update && apt-get install -y ffmpeg

# Crea una cartella app e copia tutto dentro
WORKDIR /app
COPY . /app

# Installa le dipendenze Python
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Avvia il bot
CMD ["python", "bot.py"]