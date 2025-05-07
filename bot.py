import os
import logging
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

load_dotenv()

# Logging
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# States
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
    # Bottoni reply che compaiono nella barra della chat
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
    # Solo un reply_markup per ogni messaggio!
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
    # Comandi barra chat
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
        # Cerca su YouTube (15 risultati)
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
                "📺 *Scegli il risultato che vuoi scaricare:*",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return SHOW_RESULTS
        except Exception as e:
            logger.exception("Errore durante la ricerca YouTube")
            await update.message.reply_text("⚠️ Errore nella ricerca su YouTube.")
            return await main_menu(update, context)
    elif source == "spotify":
        # Cerca su Spotify in base a tipo
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
                        "artists": ", ".join(a["name"] for a in t["artists"])
                    } for t in results
                ]
                keyboard = [
                    [InlineKeyboardButton(
                        f"{t['name']} - {t['artists']}", callback_data=f"sp_{i}"
                    )] for i, t in enumerate(context.user_data["sp_results"])
                ]
            elif s_type == "artist":
                res = sp.search(text, type="artist", limit=10)
                results = res["artists"]["items"]
                context.user_data["sp_results"] = [
                    {"id": a["id"], "name": a["name"]} for a in results
                ]
                keyboard = [
                    [InlineKeyboardButton(
                        f"{a['name']}", callback_data=f"sp_artist_{i}"
                    )] for i, a in enumerate(context.user_data["sp_results"])
                ]
            elif s_type == "album":
                res = sp.search(text, type="album", limit=10)
                results = res["albums"]["items"]
                context.user_data["sp_results"] = [
                    {"id": al["id"], "name": al["name"], "artists": ", ".join(a["name"] for a in al["artists"])} for al in results
                ]
                keyboard = [
                    [InlineKeyboardButton(
                        f"{al['name']} - {al['artists']}", callback_data=f"sp_album_{i}"
                    )] for i, al in enumerate(context.user_data["sp_results"])
                ]
            elif s_type == "playlist":
                res = sp.search(text, type="playlist", limit=10)
                results = res["playlists"]["items"]
                context.user_data["sp_results"] = [
                    {"id": pl["id"], "name": pl["name"], "owner": pl["owner"]["display_name"]} for pl in results
                ]
                keyboard = [
                    [InlineKeyboardButton(
                        f"{pl['name']} (di {pl['owner']})", callback_data=f"sp_playlist_{i}"
                    )] for i, pl in enumerate(context.user_data["sp_results"])
                ]
            else:
                await update.message.reply_text("Tipo di ricerca non supportato.")
                return await main_menu(update, context)
            if not keyboard:
                await update.message.reply_text("❌ Nessun risultato trovato. Torno al menù principale.")
                return await main_menu(update, context)
            keyboard.append([InlineKeyboardButton("❌ Annulla", callback_data="cancel")])
            await update.message.reply_text(
                "🟢 *Scegli il risultato Spotify:*",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return SHOW_RESULTS
        except Exception as e:
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
    # YouTube
    if query.data.startswith("yt_"):
        idx = int(query.data.split("_")[1])
        result = context.user_data["yt_results"][idx]
        url = result["link"]
        title = result["title"]
        # Invece di scaricare mp3 (problemi ffmpeg/yt-dlp su Railway), invia il link diretto YouTube!
        await query.edit_message_text(
            f"🎶 *Ecco il link YouTube:*\n[{title}]({url})\n\nPer scaricare l'mp3 puoi usare siti come [ytmp3.cc](https://ytmp3.cc/it/) o simili.",
            parse_mode="Markdown"
        )
        await query.message.reply_text("✅ *Operazione completata.*", parse_mode="Markdown", reply_markup=main_keyboard())
        return await main_menu(update, context)
    # Spotify
    elif query.data.startswith("sp_"):
        # Track, Artist, Album, Playlist
        if "artist_" in query.data:
            idx = int(query.data.split("_")[-1])
            artist = context.user_data["sp_results"][idx]
            # Cerca le 5 canzoni più famose dell'artista
            try:
                sp = get_spotify_client()
                tracks = sp.artist_top_tracks(artist["id"], country="IT")["tracks"][:5]
                if not tracks:
                    await query.edit_message_text("❌ Nessuna canzone trovata per questo artista.")
                    return await main_menu(update, context)
                context.user_data["sp_results_artist_tracks"] = [
                    {
                        "id": t["id"],
                        "name": t["name"],
                        "artists": ", ".join(a["name"] for a in t["artists"])
                    } for t in tracks
                ]
                keyboard = [
                    [InlineKeyboardButton(
                        f"{t['name']} - {t['artists']}", callback_data=f"sp_artist_track_{i}"
                    )] for i, t in enumerate(context.user_data["sp_results_artist_tracks"])
                ]
                keyboard.append([InlineKeyboardButton("❌ Annulla", callback_data="cancel")])
                await query.edit_message_text(
                    f"Scegli una canzone di {artist['name']}:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return SHOW_RESULTS
            except Exception:
                logger.exception("Errore ricerca canzoni artista")
                await query.edit_message_text("⚠️ Errore nella ricerca delle canzoni dell'artista.")
                return await main_menu(update, context)
        elif "album_" in query.data:
            idx = int(query.data.split("_")[-1])
            album = context.user_data["sp_results"][idx]
            try:
                sp = get_spotify_client()
                tracks = sp.album_tracks(album["id"])["items"][:10]
                if not tracks:
                    await query.edit_message_text("❌ Nessuna canzone trovata in questo album.")
                    return await main_menu(update, context)
                context.user_data["sp_results_album_tracks"] = [
                    {
                        "id": t["id"],
                        "name": t["name"],
                        "artists": album["artists"]
                    } for t in tracks
                ]
                keyboard = [
                    [InlineKeyboardButton(
                        f"{t['name']}", callback_data=f"sp_album_track_{i}"
                    )] for i, t in enumerate(context.user_data["sp_results_album_tracks"])
                ]
                keyboard.append([InlineKeyboardButton("❌ Annulla", callback_data="cancel")])
                await query.edit_message_text(
                    f"Scegli una canzone dell'album {album['name']}:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return SHOW_RESULTS
            except Exception:
                logger.exception("Errore ricerca canzoni album")
                await query.edit_message_text("⚠️ Errore nella ricerca tracce dell'album.")
                return await main_menu(update, context)
        elif "playlist_" in query.data:
            idx = int(query.data.split("_")[-1])
            playlist = context.user_data["sp_results"][idx]
            try:
                sp = get_spotify_client()
                tracks = sp.playlist_tracks(playlist["id"], limit=10)["items"]
                if not tracks:
                    await query.edit_message_text("❌ Nessuna canzone trovata in questa playlist.")
                    return await main_menu(update, context)
                context.user_data["sp_results_playlist_tracks"] = [
                    {
                        "id": t["track"]["id"],
                        "name": t["track"]["name"],
                        "artists": ", ".join(a["name"] for a in t["track"]["artists"])
                    } for t in tracks
                ]
                keyboard = [
                    [InlineKeyboardButton(
                        f"{t['name']} - {t['artists']}", callback_data=f"sp_playlist_track_{i}"
                    )] for i, t in enumerate(context.user_data["sp_results_playlist_tracks"])
                ]
                keyboard.append([InlineKeyboardButton("❌ Annulla", callback_data="cancel")])
                await query.edit_message_text(
                    f"Scegli una canzone dalla playlist {playlist['name']}:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return SHOW_RESULTS
            except Exception:
                logger.exception("Errore ricerca canzoni playlist")
                await query.edit_message_text("⚠️ Errore nella ricerca tracce della playlist.")
                return await main_menu(update, context)
        elif "artist_track_" in query.data:
            idx = int(query.data.split("_")[-1])
            track = context.user_data["sp_results_artist_tracks"][idx]
            return await download_spotify_mp3(query, track)
        elif "album_track_" in query.data:
            idx = int(query.data.split("_")[-1])
            track = context.user_data["sp_results_album_tracks"][idx]
            return await download_spotify_mp3(query, track)
        elif "playlist_track_" in query.data:
            idx = int(query.data.split("_")[-1])
            track = context.user_data["sp_results_playlist_tracks"][idx]
            return await download_spotify_mp3(query, track)
        else: # sp_X (track)
            idx = int(query.data.split("_")[-1])
            track = context.user_data["sp_results"][idx]
            return await download_spotify_mp3(query, track)
    else:
        await query.edit_message_text("Errore interno, torno al menù.")
        return await main_menu(update, context)

async def download_spotify_mp3(query, track_info):
    """
    Invece di fare scraping, fornisce direttamente il link di download da SpotifyMate.
    """
    track_id = track_info.get("id")
    if not track_id:
        await query.edit_message_text("❌ Errore: manca l'ID della canzone Spotify.")
        return await main_menu(query, query._application)
    spotify_url = f"https://open.spotify.com/track/{track_id}"
    spotimate_url = f"https://spotimate.io/it?url={spotify_url}"
    await query.edit_message_text(
        f"🎶 *Scarica l’mp3 di questa traccia Spotify gratis usando [SpotifyMate]({spotimate_url})!* \n\n"
        f"Oppure copia il link qui: `{spotify_url}` e incollalo su [SpotifyMate](https://spotimate.io/it).\n\n"
        "✅ *Operazione completata*.",
        parse_mode="Markdown", disable_web_page_preview=True
    )
    await query.message.reply_text("Torna al menù principale 👇", reply_markup=main_keyboard())
    return await main_menu(query, query._application)

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