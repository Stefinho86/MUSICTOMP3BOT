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
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from youtubesearchpython import VideosSearch
import yt_dlp
from bs4 import BeautifulSoup

load_dotenv()

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

MENU, CHOOSE_SOURCE, CHOOSE_TYPE, ENTER_QUERY, SHOW_RESULTS = range(5)

def get_spotify_client():
    return spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(
            client_id=os.environ["SPOTIFY_CLIENT_ID"],
            client_secret=os.environ["SPOTIFY_CLIENT_SECRET"]
        )
    )

def cancel_markup():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annulla", callback_data="cancel")]])

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
    else:
        await update.effective_message.reply_text(msg, reply_markup=reply_markup, parse_mode="Markdown")
    return CHOOSE_SOURCE

async def choose_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "search_youtube":
        context.user_data.clear()
        context.user_data["source"] = "youtube"
        await query.edit_message_text(
            "🔍 *Invia il titolo della canzone da cercare su YouTube.*\n\nPremi Annulla per tornare al menù.",
            reply_markup=cancel_markup(), parse_mode="Markdown"
        )
        return ENTER_QUERY
    elif query.data == "search_spotify":
        context.user_data.clear()
        context.user_data["source"] = "spotify"
        keyboard = [
            [
                InlineKeyboardButton("Canzone", callback_data="track"),
                InlineKeyboardButton("Artista", callback_data="artist"),
            ],
            [
                InlineKeyboardButton("Album", callback_data="album"),
                InlineKeyboardButton("Playlist", callback_data="playlist"),
            ],
            [InlineKeyboardButton("❌ Annulla", callback_data="cancel")],
        ]
        await query.edit_message_text(
            "🟢 *Scegli tipo di ricerca Spotify:*",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return CHOOSE_TYPE

async def choose_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancel":
        return await main_menu(update, context)
    context.user_data["spotify_type"] = query.data
    readable = {
        "track": "canzone",
        "artist": "artista",
        "album": "album",
        "playlist": "playlist"
    }
    await query.edit_message_text(
        f"🔍 *Inserisci la query per la ricerca {readable[query.data]} su Spotify.*\n\nPremi Annulla per tornare al menù.",
        reply_markup=cancel_markup(), parse_mode="Markdown"
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
            "🔍 *Invia il titolo della canzone da cercare su YouTube.*\n\nPremi Annulla per tornare al menù.",
            reply_markup=cancel_markup(), parse_mode="Markdown"
        )
        return ENTER_QUERY
    if text.lower() == "/spotify":
        context.user_data.clear()
        context.user_data["source"] = "spotify"
        keyboard = [
            [
                InlineKeyboardButton("Canzone", callback_data="track"),
                InlineKeyboardButton("Artista", callback_data="artist"),
            ],
            [
                InlineKeyboardButton("Album", callback_data="album"),
                InlineKeyboardButton("Playlist", callback_data="playlist"),
            ],
            [InlineKeyboardButton("❌ Annulla", callback_data="cancel")],
        ]
        await update.message.reply_text(
            "🟢 *Scegli tipo di ricerca Spotify:*",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return CHOOSE_TYPE

    source = context.user_data.get("source")
    if source == "youtube":
        try:
            videos_search = VideosSearch(text, limit=15)
            results = videos_search.result()["result"]
            if not results:
                await update.message.reply_text("❌ Nessun risultato trovato. Torno al menù principale.")
                return await main_menu(update, context)
            context.user_data["yt_results"] = results
            keyboard = [
                [InlineKeyboardButton(
                    f"{v['title']} - {v['channel']['name']}", callback_data=f"yt_{i}"
                )] for i, v in enumerate(results)
            ]
            keyboard.append([InlineKeyboardButton("❌ Annulla", callback_data="cancel")])
            await update.message.reply_text(
                "📺 *Scegli il risultato da scaricare come mp3:*",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return SHOW_RESULTS
        except Exception:
            logger.exception("Errore durante la ricerca YouTube")
            await update.message.reply_text("⚠️ Errore nella ricerca su YouTube.")
            return await main_menu(update, context)
    elif source == "spotify":
        try:
            sp = get_spotify_client()
            s_type = context.user_data.get("spotify_type", "track")
            results = []
            if s_type == "track":
                res = sp.search(text, type="track", limit=10)
                results = res["tracks"]["items"]
                context.user_data["sp_results"] = [
                    {
                        "id": t["id"],
                        "name": t["name"],
                        "artists": ", ".join(a["name"] for a in t["artists"]),
                        "url": t["external_urls"]["spotify"]
                    } for t in results
                ]
                keyboard = [
                    [InlineKeyboardButton(
                        f"{t['name']} - {t['artists']}", callback_data=f"sp_{i}"
                    )] for i, t in enumerate(context.user_data["sp_results"])
                ]
            else:
                await update.message.reply_text("Solo la ricerca 'Canzone' Spotify è supportata per il download diretto mp3.")
                return await main_menu(update, context)
            if not keyboard:
                await update.message.reply_text("❌ Nessun risultato trovato. Torno al menù principale.")
                return await main_menu(update, context)
            keyboard.append([InlineKeyboardButton("❌ Annulla", callback_data="cancel")])
            await update.message.reply_text(
                "🟢 *Scegli la canzone Spotify da scaricare come mp3:*",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return SHOW_RESULTS
        except Exception:
            logger.exception("Errore durante la ricerca Spotify")
            await update.message.reply_text("⚠️ Errore nella ricerca su Spotify.")
            return await main_menu(update, context)
    else:
        await update.message.reply_text("❓ Sorgente sconosciuta. Torno al menù.")
        return await main_menu(update, context)

async def show_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancel":
        return await main_menu(update, context)
    if query.data.startswith("yt_"):
        idx = int(query.data.split("_")[1])
        result = context.user_data["yt_results"][idx]
        url = result["link"]
        title = result["title"]
        performer = result["channel"]["name"]
        try:
            await query.edit_message_text(f"⬇️ Scaricamento in corso di: *{title}* ...", parse_mode="Markdown")
            file_path = await download_youtube_audio(url)
            await query.message.reply_audio(
                audio=open(file_path, "rb"),
                title=title,
                performer=performer
            )
            os.remove(file_path)
            await query.message.reply_text("✅ *Mp3 inviato. Torno al menù principale.*", parse_mode="Markdown", reply_markup=main_keyboard())
        except Exception:
            logger.exception("Errore scaricando da YouTube")
            await query.message.reply_text("⚠️ Errore durante il download o l'invio dell'mp3.")
        return await main_menu(update, context)
    elif query.data.startswith("sp_"):
        idx = int(query.data.split("_")[-1])
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
            await query.message.reply_audio(
                audio=open(temp_path, "rb"),
                title=title,
                performer=artists
            )
            os.remove(temp_path)
            await query.message.reply_text("✅ *Mp3 inviato da SpotifyMate. Torno al menù principale.*", parse_mode="Markdown", reply_markup=main_keyboard())
        except Exception:
            logger.exception("Errore scaricando da SpotifyMate")
            await query.message.reply_text("⚠️ Errore durante il download o l'invio dell'mp3 da SpotifyMate.")
        return await main_menu(update, context)
    else:
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
    # Ottieni la pagina di Spotimate per il link Spotify
    main_url = "https://spotimate.io/it"
    try:
        resp = session.post(
            main_url,
            data={"url": spotify_url},
            headers={"User-Agent": "Mozilla/5.0"}
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        # Cerca link mp3 diretto: <a href="..." download>Download</a>
        download_btn = soup.find("a", attrs={"download": True})
        if download_btn and download_btn.get("href", "").endswith(".mp3"):
            return download_btn.get("href")
        # In alcuni casi c'è anche un bottone secondario
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
            CHOOSE_TYPE: [CallbackQueryHandler(choose_type)],
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