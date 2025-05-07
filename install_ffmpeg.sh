#!/bin/sh
set -e
if command -v apt-get >/dev/null 2>&1; then
  apt-get update && apt-get install -y ffmpeg
fi
python bot.py