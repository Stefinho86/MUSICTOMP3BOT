import os
import asyncio
import logging
import sqlite3
import glob
import re
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
MENU, SEARCH, PAGINATE = range(3)
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

# --- Utilità per pulire il nome del file
def safe_filename(s):
    return re.sub(r'[\\/*?:"<>|]', '', s).strip()

# --- Ricerca su YouTube (con paginazione)
def search_youtube(query, page_token=None):
    youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
    req = youtube.search().list(
        q=query, part='snippet', type='video', maxResults=PAGE_SIZE, pageToken=page_token
    )
    res = req.execute()
    results = []
    for item in res['items']:
        title = item['snippet']['title']
        channel = item['snippet'].get('channelTitle', 'Sconosciuto')
        video_id = item['id']['videoId']
        results.append({'title': title, 'video_id': video_id, 'channel': channel})
    next_token = res.get('nextPageToken')
    prev_token = res.get('prevPageToken')
    return results, next_token, prev_token

# --- Scarica audio (yt-dlp)
async def download_mp3_async(video_id, artist, title):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, download_mp3, video_id, artist, title)

def download_mp3(video_id, artist, title):
    url = f"https://www.youtube.com/watch?v={video_id}"
    unique_id = str(uuid4())
    temp_filename = f"{unique_id}.mp3"
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
        'cookies': 'youtube_cookies.txt',  # << aggiungi questa riga!
    }
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    mp3_files = glob.glob(f"{unique_id}*.mp3")
    if not mp3_files:
        logger.error("Nessun file mp3 trovato dopo il download!")
        raise FileNotFoundError("Nessun file mp3 trovato dopo il download!")
    artist_clean = safe_filename(artist)
    title_clean = safe_filename(title)
    final_name = f"{artist_clean} - {title_clean}.mp3"
    os.rename(mp3_files[0], final_name)
    return final_name

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
    await manda_menu(update)
    return MENU

async def manda_menu(update):
    keyboard = [
        [KeyboardButton("🔍 Cerca brano")],
        [KeyboardButton("🕑 Cronologia")],
        [KeyboardButton("❌ Esci")]
    ]
    if hasattr(update, "message") and update.message:
        await update.message.reply_text(
            "Benvenuto! Scegli una modalità:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
    elif hasattr(update, "callback_query") and update.callback_query:
        await update.callback_query.message.reply_text(
            "Menù principale:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    if "cerca" in text:
        context.user_data['search_mode'] = "titolo"
        await update.message.reply_text(
            "Inserisci il titolo del brano da cercare:",
            reply_markup=ReplyKeyboardMarkup([["Annulla"]], resize_keyboard=True)
        )
        return SEARCH
    elif "cronologia" in text:
        history = get_history(update.effective_user.id)
        if not history:
            await update.message.reply_text("Nessuna cronologia trovata.")
        else:
            await update.message.reply_text("\n".join(f"- {h}" for h in history))
        await manda_menu(update)
        return MENU
    elif "esci" in text or "annulla" in text or "/annulla" in text:
        await update.message.reply_text(
            "Conversazione annullata.",
            reply_markup=ReplyKeyboardRemove()
        )
        await manda_menu(update)
        return MENU
    else:
        await update.message.reply_text("Scegli una delle opzioni dal menu.")
        return MENU

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() in ["annulla", "/annulla"]:
        await update.message.reply_text(
            "Operazione annullata.",
            reply_markup=ReplyKeyboardRemove()
        )
        await manda_menu(update)
        return MENU
    context.user_data['query'] = text
    add_history(update.effective_user.id, text)
    results, next_token, prev_token = search_youtube(text)
    if not results:
        await update.message.reply_text("Nessun risultato trovato.")
        await manda_menu(update)
        return MENU
    context.user_data['results'] = results
    context.user_data['next_token'] = next_token
    context.user_data['prev_token'] = prev_token
    context.user_data['page_token'] = None
    context.user_data['current_page'] = 0  # Resetta a pagina 0
    await show_results(update, context, results, next_token, prev_token)
    return PAGINATE

async def show_results(update, context, results, next_token, prev_token):
    # Calcola il numero iniziale del conteggio in base alla pagina attuale
    current_page = context.user_data.get('current_page', 0)
    start_number = current_page * PAGE_SIZE + 1

    msg = ""
    for idx, r in enumerate(results, start=start_number):
        msg += f"*{idx}.* {r['title']}\n   _Canale:_ `{r['channel']}`\n\n"
    msg += "Scegli quale scaricare dai pulsanti qui sotto."

    # Pulsanti: uno per ogni risultato
    keyboard = [
        [
            InlineKeyboardButton(f"Scarica {i+start_number}", callback_data=f"dl_{i}")
        ] for i in range(len(results))
    ]
    # Navigazione
    nav_buttons = []
    if prev_token:
        nav_buttons.append(InlineKeyboardButton("⬅️ Indietro", callback_data="prev"))
    if next_token:
        nav_buttons.append(InlineKeyboardButton("Avanti ➡️", callback_data="next"))
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton("❌ Annulla", callback_data="annulla")])

    if hasattr(update, "message") and update.message:
        await update.message.reply_text(
            msg,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    else:
        await update.callback_query.edit_message_text(
            msg,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

async def paginate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "next" or data == "prev":
        # Calcola pagina attuale
        current_page = context.user_data.get('current_page', 0)
        if data == "next":
            current_page += 1
        else:
            current_page = max(0, current_page - 1)
        token = context.user_data['next_token'] if data == "next" else context.user_data['prev_token']
        results, next_token, prev_token = search_youtube(context.user_data['query'], page_token=token)
        context.user_data['results'] = results
        context.user_data['next_token'] = next_token
        context.user_data['prev_token'] = prev_token
        context.user_data['page_token'] = token
        context.user_data['current_page'] = current_page  # Aggiorna pagina
        await show_results(update, context, results, next_token, prev_token)
        return PAGINATE
    elif data.startswith("dl_"):
        idx = int(data[3:])
        result = context.user_data['results'][idx]
        video_id = result['video_id']
        artist = result['channel']
        title = result['title']
        user_id = update.effective_user.id
        if not can_download(user_id):
            await query.edit_message_text("Stai già scaricando troppe canzoni in parallelo. Attendi...")
            return PAGINATE
        start_job(user_id)
        try:
            await query.edit_message_text("Scarico la canzone, attendi...")
            filename = await download_mp3_async(video_id, artist, title)
            if not os.path.exists(filename):
                logger.error(f"File non trovato dopo il download: {filename}")
                await query.message.reply_text("Errore: file mp3 non trovato dopo il download.")
            else:
                with open(filename, "rb") as f:
                    await query.message.reply_audio(f, title=title, performer=artist)
                os.remove(filename)
                await query.message.reply_text("Scaricata e inviata!")
        except Exception as e:
            logger.error(f"Errore download: {e}")
            await query.message.reply_text("Errore nel download. Riprova più tardi.")
        finally:
            end_job(user_id)
        await manda_menu(query)
        return MENU
    elif data == "annulla":
        await query.edit_message_text(
            "Operazione annullata.",
        )
        await manda_menu(query)
        return MENU
    else:
        await query.edit_message_text("Comando sconosciuto.")
        await manda_menu(query)
        return MENU

async def annulla(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Conversazione annullata.", reply_markup=ReplyKeyboardRemove())
    await manda_menu(update)
    return MENU

# --- Main
def main():
    init_db()
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            MENU: [MessageHandler(filters.TEXT, menu)],
            SEARCH: [MessageHandler(filters.TEXT, search)],
            PAGINATE: [CallbackQueryHandler(paginate)],
        },
        fallbacks=[
            CommandHandler('annulla', annulla),
            MessageHandler(filters.Regex("(?i)annulla"), annulla)
        ]
    )
    app.add_handler(conv_handler)
    logger.info("Bot in esecuzione")
    app.run_polling()

if __name__ == '__main__':
    main()