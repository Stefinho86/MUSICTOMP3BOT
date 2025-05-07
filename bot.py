import os
import logging
import tempfile
import requests
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, ContextTypes, filters
)
from dotenv import load_dotenv
from googleapiclient.discovery import build
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import yt_dlp
from bs4 import BeautifulSoup

load_dotenv()

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

MENU, CHOOSE_SOURCE, ENTER_QUERY, SHOW_RESULTS = range(4)

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET")

def get_youtube_service():
    return build('youtube', 'v3', developerKey=YOUTUBE_API_KEY, cache_discovery=False)

def get_spotify_client():
    return spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET
        )
    )

def main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("/youtube"), KeyboardButton("/spotify")],
        [KeyboardButton("/annulla")]
    ], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎧 *Benvenuto! Scegli una sorgente musicale oppure usa i comandi qui sotto.*",
        parse_mode="Markdown", reply_markup=main_keyboard()
    )
    return await main_menu(update, context)

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("🎵 Cerca su YouTube", callback_data="search_youtube"),
            InlineKeyboardButton("🟢 Cerca su Spotify", callback_data="search_spotify"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = "🎧 *Scegli la sorgente musicale:*"
    if hasattr(update, "callback_query") and update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(msg, reply_markup=reply_markup, parse_mode="Markdown")
    elif hasattr(update, "message") and update.message:
        await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode="Markdown")
    return CHOOSE_SOURCE

async def choose_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "search_youtube":
        context.user_data.clear()
        context.user_data["source"] = "youtube"
        await query.edit_message_text(
            "🔍 *Invia il titolo della canzone da cercare su YouTube.*\n\nPremi /annulla per tornare al menù.",
            parse_mode="Markdown"
        )
        return ENTER_QUERY
    elif query.data == "search_spotify":
        context.user_data.clear()
        context.user_data["source"] = "spotify"
        await query.edit_message_text(
            "🔍 *Invia il titolo della canzone da cercare su Spotify.*\n\nPremi /annulla per tornare al menù.",
            parse_mode="Markdown"
        )
        return ENTER_QUERY

async def enter_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() in ["/annulla", "annulla"]:
        return await main_menu(update, context)
    if text.lower() == "/youtube":
        context.user_data.clear()
        context.user_data["source"] = "youtube"
        await update.message.reply_text(
            "🔍 *Invia il titolo della canzone da cercare su YouTube.*\n\nPremi /annulla per tornare al menù.",
            parse_mode="Markdown"
        )
        return ENTER_QUERY
    if text.lower() == "/spotify":
        context.user_data.clear()
        context.user_data["source"] = "spotify"
        await update.message.reply_text(
            "🔍 *Invia il titolo della canzone da cercare su Spotify.*\n\nPremi /annulla per tornare al menù.",
            parse_mode="Markdown"
        )
        return ENTER_QUERY

    source = context.user_data.get("source")

    if source == "youtube":
        try:
            youtube = get_youtube_service()
            req = youtube.search().list(
                q=text,
                part="snippet",
                type="video",
                maxResults=25
            )
            res = req.execute()
            results = []
            for item in res.get("items", []):
                # Solo risultati che hanno videoId
                if "videoId" in item["id"]:
                    results.append({
                        "videoId": item["id"]["videoId"],
                        "title": item["snippet"]["title"],
                        "channel": item["snippet"]["channelTitle"]
                    })
            if not results:
                await update.message.reply_text("❌ Nessun risultato trovato su YouTube. Torno al menù principale.")
                return await main_menu(update, context)
            context.user_data["yt_results"] = results
            context.user_data["yt_page"] = 0
            return await show_youtube_page(update, context)
        except Exception as e:
            logger.exception(f"Errore durante la ricerca YouTube: {e}")
            await update.message.reply_text("⚠️ Errore nella ricerca su YouTube (API).")
            return await main_menu(update, context)

    elif source == "spotify":
        try:
            sp = get_spotify_client()
            res = sp.search(text, type="track", limit=25)
            results = res["tracks"]["items"]
            if not results:
                await update.message.reply_text("❌ Nessun risultato trovato su Spotify. Torno al menù principale.")
                return await main_menu(update, context)
            context.user_data["sp_results"] = [
                {
                    "id": t["id"],
                    "name": t["name"],
                    "artists": ", ".join(a["name"] for a in t["artists"]),
                    "url": t["external_urls"]["spotify"]
                } for t in results
            ]
            context.user_data["sp_page"] = 0
            return await show_spotify_page(update, context)
        except Exception as e:
            logger.exception(f"Errore durante la ricerca Spotify: {e}")
            await update.message.reply_text("⚠️ Errore nella ricerca su Spotify.")
            return await main_menu(update, context)
    else:
        await update.message.reply_text("❓ Sorgente sconosciuta. Torno al menù.")
        return await main_menu(update, context)

async def show_youtube_page(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    results = context.user_data["yt_results"]
    page = context.user_data.get("yt_page", 0)
    per_page = 5
    total = len(results)
    start = page * per_page
    end = start + per_page
    paginated = results[start:end]
    keyboard = [
        [InlineKeyboardButton(
            f"{v['title']} - {v['channel']}", callback_data=f"yt_{start+i}"
        )] for i, v in enumerate(paginated)
    ]
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Indietro", callback_data="yt_prev"))
    if end < total:
        nav_row.append(InlineKeyboardButton("Avanti ➡️", callback_data="yt_next"))
    if nav_row:
        keyboard.append(nav_row)
    keyboard.append([InlineKeyboardButton("❌ Annulla", callback_data="cancel")])
    msg = f"📺 *Risultati YouTube ({start+1}-{min(end,total)}) su {total}:*"
    if hasattr(update_or_query, "callback_query") and update_or_query.callback_query:
        await update_or_query.callback_query.edit_message_text(
            msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    else:
        await update_or_query.message.reply_text(
            msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    return SHOW_RESULTS

async def show_spotify_page(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    results = context.user_data["sp_results"]
    page = context.user_data.get("sp_page", 0)
    per_page = 5
    total = len(results)
    start = page * per_page
    end = start + per_page
    paginated = results[start:end]
    keyboard = [
        [InlineKeyboardButton(
            f"{t['name']} - {t['artists']}", callback_data=f"sp_{start+i}"
        )] for i, t in enumerate(paginated)
    ]
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Indietro", callback_data="sp_prev"))
    if end < total:
        nav_row.append(InlineKeyboardButton("Avanti ➡️", callback_data="sp_next"))
    if nav_row:
        keyboard.append(nav_row)
    keyboard.append([InlineKeyboardButton("❌ Annulla", callback_data="cancel")])
    msg = f"🟢 *Risultati Spotify ({start+1}-{min(end,total)}) su {total}:*"
    if hasattr(update_or_query, "callback_query") and update_or_query.callback_query:
        await update_or_query.callback_query.edit_message_text(
            msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    else:
        await update_or_query.message.reply_text(
            msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    return SHOW_RESULTS

async def show_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "yt_prev":
        context.user_data["yt_page"] = max(0, context.user_data["yt_page"] - 1)
        return await show_youtube_page(update, context)
    if data == "yt_next":
        context.user_data["yt_page"] = context.user_data["yt_page"] + 1
        return await show_youtube_page(update, context)
    if data.startswith("yt_"):
        idx = int(data.split("_")[1])
        result = context.user_data["yt_results"][idx]
        video_id = result["videoId"]
        url = f"https://www.youtube.com/watch?v={video_id}"
        title = result["title"]
        performer = result["channel"]
        try:
            await query.edit_message_text(f"⬇️ Scaricamento in corso di: *{title}* ...", parse_mode="Markdown")
            file_path = await download_youtube_audio(url)
            with open(file_path, "rb") as f:
                await query.message.reply_audio(
                    audio=f,
                    title=title,
                    performer=performer
                )
            os.remove(file_path)
            await query.message.reply_text("✅ *Mp3 inviato. Torno al menù principale.*", parse_mode="Markdown", reply_markup=main_keyboard())
        except Exception:
            logger.exception("Errore scaricando da YouTube")
            await query.message.reply_text("⚠️ Errore durante il download o l'invio dell'mp3. Probabilmente ffmpeg manca nel container Railway.")
        return await main_menu(update, context)
    if data == "sp_prev":
        context.user_data["sp_page"] = max(0, context.user_data["sp_page"] - 1)
        return await show_spotify_page(update, context)
    if data == "sp_next":
        context.user_data["sp_page"] = context.user_data["sp_page"] + 1
        return await show_spotify_page(update, context)
    if data.startswith("sp_"):
        idx = int(data.split("_")[1])
        track = context.user_data["sp_results"][idx]
        spotify_url = track["url"]
        title = track["name"]
        artists = track["artists"]
        try:
            await query.edit_message_text(f"🔄 Scarico mp3 da SpotifyMate per *{title}*...", parse_mode="Markdown")
            mp3_url = get_mp3_from_spotimate(spotify_url)
            if not mp3_url:
                await query.message.reply_text("❌ Non sono riuscito a recuperare l'mp3 da SpotifyMate.")
                return await main_menu(update, context)
            temp_fd, temp_path = tempfile.mkstemp(suffix=".mp3")
            os.close(temp_fd)
            r = requests.get(mp3_url, stream=True)
            with open(temp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            with open(temp_path, "rb") as f:
                await query.message.reply_audio(
                    audio=f,
                    title=title,
                    performer=artists
                )
            os.remove(temp_path)
            await query.message.reply_text("✅ *Mp3 inviato da SpotifyMate. Torno al menù principale.*", parse_mode="Markdown", reply_markup=main_keyboard())
        except Exception:
            logger.exception("Errore scaricando da SpotifyMate")
            await query.message.reply_text("⚠️ Errore durante il download o l'invio dell'mp3 da SpotifyMate.")
        return await main_menu(update, context)
    if data == "cancel":
        return await main_menu(update, context)
    await query.edit_message_text("Errore interno, torno al menù.")
    return await main_menu(update, context)

async def download_youtube_audio(url: str) -> str:
    temp_fd, temp_path = tempfile.mkstemp(suffix=".mp3")
    os.close(temp_fd)
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': temp_path,
        'quiet': True,
        'noplaylist': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192'
        }],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    return temp_path

def get_mp3_from_spotimate(spotify_url):
    session = requests.Session()
    main_url = "https://spotimate.io/it"
    try:
        resp = session.post(
            main_url,
            data={"url": spotify_url},
            headers={"User-Agent": "Mozilla/5.0"}
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        download_btn = soup.find("a", attrs={"download": True})
        if download_btn and download_btn.get("href", "").endswith(".mp3"):
            return download_btn.get("href")
        for a in soup.find_all("a"):
            if a.get("href", "").endswith(".mp3"):
                return a.get("href")
    except Exception as e:
        logger.exception("Errore nell'accesso a SpotifyMate")
    return None

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await main_menu(update, context)

def main():
    token = os.environ["TELEGRAM_TOKEN"]
    app = ApplicationBuilder().token(token).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSE_SOURCE: [CallbackQueryHandler(choose_source)],
            ENTER_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_query)],
            SHOW_RESULTS: [CallbackQueryHandler(show_results)],
        },
        fallbacks=[CommandHandler("annulla", cancel)],
        allow_reentry=True,
        persistent=False,
    )
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("youtube", lambda u, c: enter_query(u, c)))
    app.add_handler(CommandHandler("spotify", lambda u, c: enter_query(u, c)))
    app.add_handler(CommandHandler("annulla", cancel))
    app.run_polling()

if __name__ == "__main__":
    main()