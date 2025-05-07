import os
import requests
from bs4 import BeautifulSoup
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# --- ENV/CONFIG ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

# --- SPOTIFY AUTH ---
sp = spotipy.Spotify(
    client_credentials_manager=SpotifyClientCredentials(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
    )
)

# --- TELEGRAM BOT ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [KeyboardButton("🎵 Cerca canzone su YouTube")],
        [KeyboardButton("🟢 Cerca canzone su Spotify")],
    ]
    await update.message.reply_text(
        "Benvenuto! Scegli la modalità di ricerca:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Cerca e scarica canzoni da YouTube (mp3) o Spotify (tramite SpotiMate.io).\n"
        "Premi uno dei pulsanti per iniziare!"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "🎵 Cerca canzone su YouTube":
        await update.message.reply_text(
            "Inserisci il titolo della canzone che vuoi cercare su YouTube:",
            reply_markup=ReplyKeyboardRemove(),
        )
        context.user_data["mode"] = "youtube"
        return
    if text == "🟢 Cerca canzone su Spotify":
        await update.message.reply_text(
            "Inserisci il titolo della canzone che vuoi cercare su Spotify:",
            reply_markup=ReplyKeyboardRemove(),
        )
        context.user_data["mode"] = "spotify"
        return

    mode = context.user_data.get("mode")
    if mode == "youtube":
        await search_and_send_youtube(update, context, text)
        return
    if mode == "spotify":
        await search_and_show_spotify(update, context, text)
        return

    await update.message.reply_text("Scegli una modalità di ricerca dai pulsanti.")

# ----------- YOUTUBE (solo ricerca per titolo) -----------
def youtube_search(query):
    # Semplice scraping di YouTube
    from youtubesearchpython import VideosSearch
    videosSearch = VideosSearch(query, limit=1)
    results = videosSearch.result()
    if results['result']:
        return results['result'][0]['link']
    else:
        return None

def download_youtube_audio(url):
    import yt_dlp
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': 'song.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'noplaylist': True,
        'quiet': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info).replace('.webm', '.mp3').replace('.m4a', '.mp3')
        if not os.path.exists(filename):
            filename = 'song.mp3'
        return filename, info.get('title', 'song.mp3')

async def search_and_send_youtube(update, context, query):
    await update.message.reply_text("Cerco su YouTube...")
    url = youtube_search(query)
    if not url:
        await update.message.reply_text("Nessun risultato trovato su YouTube.")
        return
    await update.message.reply_text("Scarico l'audio...")
    try:
        filename, title = download_youtube_audio(url)
        with open(filename, "rb") as f:
            await update.message.reply_audio(f, title=title)
        os.remove(filename)
    except Exception as e:
        await update.message.reply_text(f"Errore durante il download: {e}")

# -------- SPOTIFY + SPOTIMATE.IO -----------
async def search_and_show_spotify(update, context, query):
    await update.message.reply_text("Cerco su Spotify...")
    results = sp.search(q=query, type='track', limit=5)
    if not results['tracks']['items']:
        await update.message.reply_text("Nessun risultato trovato su Spotify.")
        return

    buttons = []
    for track in results['tracks']['items']:
        track_id = track['id']
        title = track['name']
        artist = track['artists'][0]['name']
        # Salva i dati in context per callback
        context.user_data[f"spotify_{track_id}"] = track
        btn_text = f"{title} - {artist}"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"spotify_{track_id}")])

    await update.message.reply_text(
        "Scegli la traccia che vuoi scaricare:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("spotify_"):
        track_id = data.replace("spotify_", "")
        track = context.user_data.get(f"spotify_{track_id}")
        if not track:
            await query.edit_message_text("Errore interno. Riprova.")
            return
        spotify_url = track['external_urls']['spotify']
        title = track['name']
        artist = track['artists'][0]['name']
        await query.edit_message_text(f"Scarico {title} - {artist} da Spotify...")

        mp3_url, mp3_name = spotimate_scrape_mp3_url(spotify_url)
        if not mp3_url:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="Non sono riuscito a ottenere l’mp3 da SpotiMate. Riprova più tardi."
            )
            return
        # Scarica il file temporaneamente
        try:
            response = requests.get(mp3_url)
            if not mp3_name.endswith('.mp3'):
                mp3_name += '.mp3'
            with open(mp3_name, "wb") as f:
                f.write(response.content)
            with open(mp3_name, "rb") as f:
                await context.bot.send_audio(
                    chat_id=query.message.chat_id,
                    audio=f,
                    title=title,
                    performer=artist,
                )
            os.remove(mp3_name)
        except Exception as e:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"Errore durante il download: {e}"
            )
        return

def spotimate_scrape_mp3_url(spotify_link):
    '''
    Funzione che esegue scraping su spotimate.io/it per ottenere il link mp3.
    Restituisce (url_mp3, nome_canzone).
    '''
    session = requests.Session()
    headers = {"User-Agent": "Mozilla/5.0"}
    session.get("https://spotimate.io/it", headers=headers)
    post_url = "https://spotimate.io/it/download"
    data = {'url': spotify_link}
    response = session.post(post_url, data=data, headers=headers)
    soup = BeautifulSoup(response.text, "html.parser")
    for a in soup.find_all("a", href=True):
        if "/dl?token=" in a['href']:
            download_url = "https://spotimate.io" + a['href']
            nome = a.text.strip()
            if not nome:
                nome = "spotify_song.mp3"
            if not nome.endswith('.mp3'):
                nome += ".mp3"
            return download_url, nome
    return None, None

# ------ MAIN ------
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback_query))

    print("Bot avviato.")
    app.run_polling()

if __name__ == "__main__":
    main()