import os
import asyncio
import logging
import sqlite3
import glob
from uuid import uuid4
from dotenv import load_dotenv
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler, ContextTypes
)
from yt_dlp import YoutubeDL
from googleapiclient.discovery import build

# --- Carica variabili ambiente
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

# --- Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Stati conversazione
MENU, SEARCH, CHOOSE, PAGINATE = range(4)
PAGE_SIZE = 5
MAX_HISTORY = 10
USER_LIMIT = 3  # richieste contemporanee per utente

# --- SQLite setup
DB_FILE = "database.db"
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS history (
            user_id INTEGER,
            search TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def add_history(user_id, search):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO history (user_id, search) VALUES (?, ?)", (user_id, search))
    conn.commit()
    conn.close()

def get_history(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "SELECT search FROM history WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
        (user_id, MAX_HISTORY)
    )
    results = [row[0] for row in c.fetchall()]
    conn.close()
    return results

# --- Ricerca su YouTube
def search_youtube(query, page_token=None):
    youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
    req = youtube.search().list(
        q=query, part='snippet', type='video', maxResults=PAGE_SIZE, pageToken=page_token
    )
    res = req.execute()
    results = []
    for item in res['items']:
        title = item['snippet']['title']
        video_id = item['id']['videoId']
        results.append({'title': title, 'video_id': video_id})
    next_token = res.get('nextPageToken')
    prev_token = res.get('prevPageToken')
    return results, next_token, prev_token

# --- Scarica audio (yt-dlp)
async def download_mp3_async(video_id):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, download_mp3, video_id)

def download_mp3(video_id):
    url = f"https://www.youtube.com/watch?v={video_id}"
    unique_id = str(uuid4())
    filename = f"{unique_id}.mp3"
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{unique_id}.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'noplaylist': True,
        'quiet': True,
        'merge_output_format': 'mp3',
    }
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    # Cerca il file mp3 creato
    mp3_files = glob.glob(f"{unique_id}*.mp3")
    if mp3_files:
        logger.info(f"File mp3 trovato: {mp3_files[0]}")
        return mp3_files[0]
    else:
        logger.error("Nessun file mp3 trovato dopo il download!")
        logger.error(f"Files in directory: {os.listdir('.')}")
        raise FileNotFoundError("Nessun file mp3 trovato dopo il download!")

# --- Limiti utente
user_jobs = {}

def can_download(user_id):
    return user_jobs.get(user_id, 0) < USER_LIMIT

def start_job(user_id):
    user_jobs[user_id] = user_jobs.get(user_id, 0) + 1

def end_job(user_id):
    user_jobs[user_id] = max(user_jobs.get(user_id, 1) - 1, 0)

# --- Comandi Bot

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = [
        [KeyboardButton("🔍 Cerca per titolo")],
        [KeyboardButton("🎤 Cerca per artista")],
        [KeyboardButton("💿 Cerca per album")],
        [KeyboardButton("🕑 Cronologia")],
        [KeyboardButton("❌ Esci")]
    ]
    await update.message.reply_text(
        "Benvenuto! Scegli una modalità di ricerca:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return MENU

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    if "titolo" in text:
        context.user_data['search_mode'] = "titolo"
        await update.message.reply_text("Inserisci il titolo della canzone:", reply_markup=ReplyKeyboardRemove())
        return SEARCH
    elif "artista" in text:
        context.user_data['search_mode'] = "artista"
        await update.message.reply_text("Inserisci il nome dell'artista:", reply_markup=ReplyKeyboardRemove())
        return SEARCH
    elif "album" in text:
        context.user_data['search_mode'] = "album"
        await update.message.reply_text("Inserisci il nome dell'album:", reply_markup=ReplyKeyboardRemove())
        return SEARCH
    elif "cronologia" in text:
        history = get_history(update.effective_user.id)
        if not history:
            await update.message.reply_text("Nessuna cronologia trovata.")
        else:
            await update.message.reply_text("\n".join(f"- {h}" for h in history))
        return MENU
    elif "esci" in text:
        await update.message.reply_text("Bot terminato. Usa /start per ricominciare.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    else:
        await update.message.reply_text("Scegli una delle opzioni dal menu.")
        return MENU

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    context.user_data['query'] = query
    add_history(update.effective_user.id, query)
    results, next_token, prev_token = search_youtube(query)
    if not results:
        await update.message.reply_text("Nessun risultato trovato.")
        return MENU
    # Salva per paginazione
    context.user_data['results'] = results
    context.user_data['next_token'] = next_token
    context.user_data['prev_token'] = prev_token
    context.user_data['page_token'] = None
    await show_results(update, context, results, next_token, prev_token)
    return PAGINATE

async def show_results(update, context, results, next_token, prev_token):
    keyboard = [
        [InlineKeyboardButton(r['title'][:50], callback_data=f"dl_{r['video_id']}")] for r in results
    ]
    nav_buttons = []
    if prev_token:
        nav_buttons.append(InlineKeyboardButton("⬅️ Indietro", callback_data="prev"))
    if next_token:
        nav_buttons.append(InlineKeyboardButton("Avanti ➡️", callback_data="next"))
    if nav_buttons:
        keyboard.append(nav_buttons)
    if update.message:
        await update.message.reply_text(
            "Risultati trovati:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.callback_query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def paginate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "next" or data == "prev":
        token = context.user_data['next_token'] if data == "next" else context.user_data['prev_token']
        results, next_token, prev_token = search_youtube(context.user_data['query'], page_token=token)
        context.user_data['results'] = results
        context.user_data['next_token'] = next_token
        context.user_data['prev_token'] = prev_token
        context.user_data['page_token'] = token
        await show_results(update, context, results, next_token, prev_token)
        return PAGINATE
    elif data.startswith("dl_"):
        video_id = data[3:]
        user_id = update.effective_user.id
        if not can_download(user_id):
            await query.edit_message_text("Stai già scaricando troppe canzoni in parallelo. Attendi...")
            return PAGINATE
        start_job(user_id)
        try:
            await query.edit_message_text("Scarico la canzone, attendi...")
            filename = await download_mp3_async(video_id)
            logger.info(f"Provo a inviare il file: {filename}")
            if not os.path.exists(filename):
                logger.error(f"File non trovato dopo il download: {filename}")
                await query.message.reply_text("Errore: file mp3 non trovato dopo il download.")
            else:
                with open(filename, "rb") as f:
                    await query.message.reply_audio(f)
                os.remove(filename)
                await query.message.reply_text("Scaricata e inviata!")
        except Exception as e:
            logger.error(f"Errore download: {e}")
            await query.message.reply_text("Errore nel download. Riprova più tardi.")
        finally:
            end_job(user_id)
        return MENU
    else:
        await query.edit_message_text("Comando sconosciuto.")
        return MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Conversazione terminata.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- Main
def main():
    # Inizializza database
    init_db()
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            MENU: [MessageHandler(filters.TEXT, menu)],
            SEARCH: [MessageHandler(filters.TEXT, search)],
            PAGINATE: [CallbackQueryHandler(paginate)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    app.add_handler(conv_handler)
    logger.info("Bot in esecuzione")
    app.run_polling()

if __name__ == '__main__':
    main()