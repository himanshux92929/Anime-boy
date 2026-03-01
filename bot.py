import os
import aiohttp
import logging
import asyncio
import threading
import json
import base64
import secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from flask import Flask
from aiohttp_socks import ProxyConnector
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)
from telegram.request import HTTPXRequest

# --- WEB SERVER (For Deployment) ---
app = Flask(__name__)

@app.route('/')
def health_check():
    return "✨ Bot is sparkling and running! ✨"

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

threading.Thread(target=run_web_server, daemon=True).start()

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
BASE_URL = "https://aniwatch-api-six-theta.vercel.app/api/v2/hianime"
PROXY_URL = "socks5://zqxtpjjc:cknwbdszk5ux@31.59.20.176:6754"
BOT_TOKEN = "8271227515:AAGZK8k7bARC7VmTkE6UUfOPyg5ZvjGxQ-k"
DEV_CONTACT = "@smarterz_bot"

WAITING_FOR_SEARCH = 1

# --- SHARED ENCRYPTION KEY (must match generator.html) ---
KEY_HEX = 'a3f8c2e1b4d7f6a0c9e2b5d8f1a4c7e0b3d6f9a2c5e8b1d4f7a0c3e6b9d2f5a8'

def generate_token(cfg: dict) -> str:
    """Encrypt config dict using AES-GCM, matching the generator.html logic."""
    key_bytes = bytes.fromhex(KEY_HEX)
    iv = secrets.token_bytes(12)
    aesgcm = AESGCM(key_bytes)
    plaintext = json.dumps(cfg, separators=(',', ':')).encode('utf-8')
    ciphertext = aesgcm.encrypt(iv, plaintext, None)
    combined = iv + ciphertext
    token = base64.urlsafe_b64encode(combined).rstrip(b'=').decode('ascii')
    return token

# --- HELPER FUNCTIONS ---
async def fetch_api(url, retries=1):
    """Fetch API with optional retry logic for high reliability."""
    for attempt in range(retries):
        connector = ProxyConnector.from_url(PROXY_URL)
        async with aiohttp.ClientSession(connector=connector) as session:
            try:
                async with session.get(url, timeout=25) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data
                    logger.error(f"Attempt {attempt+1}: API Error {response.status}")
            except Exception as e:
                logger.error(f"Attempt {attempt+1}: Fetch Error {e}")
        if attempt < retries - 1:
            await asyncio.sleep(1.5)
    return None

def chunk_list(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    user_name = update.effective_user.first_name
    text = (
        f"🌸 <b>Kon'nichiwa, {user_name}-chan!</b> 🌸\n\n"
        f"I'm your super cute <b>Anime Assistant</b>! I can find any anime and get you those high-speed stream links! ✨\n\n"
        f"🎀 <i>What would you like to do?</i>"
    )
    keyboard = [
        [InlineKeyboardButton("🔍 Search Anime", callback_data="start_search")],
        [InlineKeyboardButton("☁️ About Smarterz", callback_data="about_bot")]
    ]
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END

async def about_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    about_text = (
        "⭐ <b>About This Bot</b> ⭐\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "This bot was handcrafted with ❤️ by <b>Smarterz Animes</b>.\n\n"
        "It uses advanced API fetching to bring you the best streaming experience directly to Telegram!\n\n"
        f"💌 <b>Developer:</b> {DEV_CONTACT}\n"
        "✨ <i>Thank you for using our service!</i>"
    )
    await context.bot.send_message(chat_id=query.message.chat_id, text=about_text, parse_mode='HTML')

async def start_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="✏️ <b>Please type the name of the Anime:</b>\n(Example: <i>Naruto</i> or <i>Solo Leveling</i>)",
        parse_mode='HTML'
    )
    return WAITING_FOR_SEARCH

async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    search_query = update.message.text
    context.user_data['search_query'] = search_query
    context.user_data['anime_map'] = {}   # fresh map for new search
    await fetch_and_display_search(update.message.chat_id, context, api_page=1)
    return ConversationHandler.END

# -----------------------------------------------------------------------
# THE CORE FIX:
#   1. Fetch only ONE API page per request — no sequential multi-fetch that
#      times out for popular anime like Naruto.
#   2. Buttons use numeric keys like "1_0", "1_1" as callback data instead
#      of the raw anime ID string, so even very long IDs never exceed
#      Telegram's 64-byte callback data limit.
#   3. status==200 check (correct) instead of the broken success-field check.
# -----------------------------------------------------------------------
async def fetch_and_display_search(chat_id, context, api_page=1):
    query_str = context.user_data.get('search_query')

    loading_msg = await context.bot.send_message(
        chat_id=chat_id,
        text="🍭 <b>Searching the database for you...</b>",
        parse_mode='HTML'
    )

    url = f"{BASE_URL}/search?q={query_str}&page={api_page}"
    data = await fetch_api(url, retries=2)

    # Correct status check — API returns {"status": 200, "data": {...}}
    if not data or data.get('status') != 200 or not data.get('data', {}).get('animes'):
        await loading_msg.edit_text(
            "💔 <b>Aww, I couldn't find that!</b>\nTry a different name or check /start."
        )
        return

    animes = data['data']['animes']
    has_next = data['data'].get('hasNextPage', False)

    # Build short numeric keys so callback data stays safely under 64 bytes.
    # e.g. key = "3_7" for page 3, index 7 → callback "id|3_7" = 7 bytes ✓
    if 'anime_map' not in context.user_data:
        context.user_data['anime_map'] = {}

    keyboard = []
    for i, anime in enumerate(animes):
        key = f"{api_page}_{i}"
        context.user_data['anime_map'][key] = anime['id']
        keyboard.append([InlineKeyboardButton(
            f"🎬 {anime['name']}",
            callback_data=f"id|{key}"
        )])

    nav_buttons = []
    if api_page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page|{api_page-1}"))
    if has_next:
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"page|{api_page+1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)

    text = (
        f"🔎 <b>Results for:</b> <i>{query_str}</i>\n"
        f"📄 Page: <b>{api_page}</b>\n\n"
        f"✨ <i>Pick one below to see more!</i>"
    )

    await loading_msg.delete()
    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    chat_id = query.message.chat_id
    await query.answer("Processing... ✨")

    try:
        # --- SEARCH PAGINATION (one API call per page, instant) ---
        if data.startswith("page|"):
            api_page = int(data.split("|")[1])
            await fetch_and_display_search(chat_id, context, api_page=api_page)

        # --- ANIME DETAILS ---
        elif data.startswith("id|"):
            key = data.split("|")[1]
            anime_id = context.user_data.get('anime_map', {}).get(key)

            if not anime_id:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ <b>Session expired!</b> Please /start and search again.",
                    parse_mode='HTML'
                )
                return

            loading = await context.bot.send_message(
                chat_id=chat_id,
                text="🎀 <b>Fetching cute details...</b>",
                parse_mode='HTML'
            )
            api_data = await fetch_api(f"{BASE_URL}/anime/{anime_id}")

            if api_data and (api_data.get('status') == 200 or api_data.get('data')):
                info = api_data['data']['anime']['info']
                stats = info.get('stats', {})
                caption = (
                    f"🌟 <b>{info.get('name', 'Unknown')}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"📺 <b>Type:</b> {stats.get('type', 'N/A')}\n"
                    f"🔊 <b>Episodes:</b> Sub {stats.get('episodes', {}).get('sub', 0)} | Dub {stats.get('episodes', {}).get('dub', 0)}\n\n"
                    f"📝 <b>Synopsis:</b>\n<i>{info.get('description', 'No description.')[:400]}...</i>"
                )
                keyboard = [[InlineKeyboardButton("▶️ View Episodes", callback_data=f"eps|{anime_id}|1")]]
                await loading.delete()
                if info.get('poster'):
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=info.get('poster'),
                        caption=caption,
                        parse_mode='HTML',
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=caption,
                        parse_mode='HTML',
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
            else:
                await loading.edit_text("❌ <b>Could not fetch anime details.</b> Please try again.")

        # --- EPISODE LIST ---
        elif data.startswith("eps|"):
            _, anime_id, page = data.split("|")
            page = int(page)
            loading = await context.bot.send_message(
                chat_id=chat_id,
                text="🌈 <b>Getting the episodes...</b>",
                parse_mode='HTML'
            )

            api_data = await fetch_api(f"{BASE_URL}/anime/{anime_id}/episodes")

            if api_data and (api_data.get('status') == 200 or api_data.get('data')):
                episodes = api_data['data'].get('episodes', [])

                if not episodes:
                    await loading.edit_text("❌ <b>No episodes found for this anime!</b>")
                    return

                if 'ep_map' not in context.user_data:
                    context.user_data['ep_map'] = {}

                chunks = list(chunk_list(episodes, 40))
                page = max(1, min(page, len(chunks)))
                current_chunk = chunks[page - 1]

                keyboard = []
                row = []
                for ep in current_chunk:
                    ep_id = ep['episodeId']
                    # Short key to stay within Telegram's callback data limit
                    short_key = ep_id.split('=')[-1]
                    context.user_data['ep_map'][short_key] = ep_id
                    row.append(InlineKeyboardButton(f"Ep {ep['number']}", callback_data=f"srv|{short_key}"))
                    if len(row) == 4:
                        keyboard.append(row)
                        row = []
                if row:
                    keyboard.append(row)

                nav = []
                if page > 1:
                    nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"eps|{anime_id}|{page-1}"))
                if page < len(chunks):
                    nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"eps|{anime_id}|{page+1}"))
                if nav:
                    keyboard.append(nav)

                await loading.delete()
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"📺 <b>Select an Episode:</b>\n📄 Page <b>{page}</b> of <b>{len(chunks)}</b>",
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await loading.edit_text("❌ <b>Could not load episodes.</b> Please try again.")

        # --- SERVER SELECTION ---
        elif data.startswith("srv|"):
            short_key = data.split("|")[1]
            ep_id = context.user_data.get('ep_map', {}).get(short_key)

            if not ep_id:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ <b>Session expired!</b> Please /start and search again.",
                    parse_mode='HTML'
                )
                return

            loading = await context.bot.send_message(
                chat_id=chat_id,
                text="⚡ <b>Finding servers...</b>",
                parse_mode='HTML'
            )
            api_data = await fetch_api(f"{BASE_URL}/episode/servers?animeEpisodeId={ep_id}")

            if api_data and (api_data.get('status') == 200 or api_data.get('data')):
                servers = api_data['data']
                keyboard = []
                for cat in ['sub', 'dub']:
                    for s in servers.get(cat, []):
                        icon = "🟢" if cat == "sub" else "🔵"
                        keyboard.append([InlineKeyboardButton(
                            f"{icon} {cat.upper()}: {s['serverName']}",
                            callback_data=f"src|{short_key}|{s['serverName']}|{cat}"
                        )])

                await loading.delete()
                if not keyboard:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="❌ <b>No servers found for this episode!</b>",
                        parse_mode='HTML'
                    )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="🎛️ <b>Select your Server:</b>",
                        parse_mode='HTML',
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
            else:
                await loading.edit_text("❌ <b>Could not fetch servers.</b> Please try again.")

        # --- FINAL SOURCE LINK ---
        elif data.startswith("src|"):
            _, short_key, s_name, cat = data.split("|")
            ep_id = context.user_data.get('ep_map', {}).get(short_key)

            if not ep_id:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ <b>Session expired!</b> Please /start and search again.",
                    parse_mode='HTML'
                )
                return

            loading = await context.bot.send_message(
                chat_id=chat_id,
                text="🚀 <b>Generating High-Speed Link...</b>",
                parse_mode='HTML'
            )

            url = f"{BASE_URL}/episode/sources?animeEpisodeId={ep_id}&server={s_name}&category={cat}"
            api_data = await fetch_api(url, retries=3)

            if api_data and (api_data.get('status') == 200 or api_data.get('data')):
                res = api_data['data']
                m3u8 = next((s['url'] for s in res.get('sources', []) if s.get('isM3U8')), None)

                if not m3u8:
                    await loading.edit_text(
                        "❌ <b>Generation Failed!</b> Link not found. Try another server.",
                        parse_mode='HTML'
                    )
                    return

                # --- Build token config ---
                cfg = {"url": m3u8}

                # Intro segment
                intro = res.get('intro', {})
                if intro.get('start') is not None and intro.get('end') is not None:
                    intro_start = intro['start']
                    intro_end = intro['end']
                    if intro_end > intro_start:
                        cfg['introStart'] = intro_start
                        cfg['introEnd'] = intro_end

                # Outro segment
                outro = res.get('outro', {})
                if outro.get('start') is not None and outro.get('end') is not None:
                    outro_start = outro['start']
                    outro_end = outro['end']
                    if outro_end > outro_start:
                        cfg['outroStart'] = outro_start
                        cfg['outroEnd'] = outro_end

                # Subtitle tracks
                sub_urls = []
                sub_names = []
                for t in res.get('tracks', []):
                    if t.get('lang') and t.get('lang') != 'thumbnails' and t.get('url'):
                        sub_urls.append(t['url'])
                        sub_names.append(t['lang'].upper())
                if sub_urls:
                    cfg['subs'] = sub_urls
                    cfg['names'] = sub_names

                # Generate encrypted token
                token = generate_token(cfg)
                player_url = f"https://animerz.vercel.app?token={token}"

                subs_text = "".join([
                    f"▪️ <a href='{t['url']}'>{t['lang'].upper()}</a>\n"
                    for t in res.get('tracks', [])
                    if t.get('lang') != 'thumbnails'
                ])
                ref = res.get('headers', {}).get('Referer', 'Not Always Needed')

                # Build intro/outro info lines
                extra_info = ""
                if 'introStart' in cfg:
                    extra_info += f"⏩ <b>Intro:</b> {cfg['introStart']}s → {cfg['introEnd']}s\n"
                if 'outroStart' in cfg:
                    extra_info += f"⏭️ <b>Outro:</b> {cfg['outroStart']}s → {cfg['outroEnd']}s\n"
                if extra_info:
                    extra_info = extra_info + "\n"

                final_text = (
                    f"✅ <b>Link Ready!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🖥️ <b>Server:</b> {s_name} ({cat.upper()})\n\n"
                    f"{extra_info}"
                    f"🔗 <b>Stream URL:</b>\n<code>{m3u8}</code>\n\n"
                    f"🌐 <b>Referer:</b> (Only use if player fails)\n<code>{ref}</code>\n\n"
                    f"📝 <b>Subtitles:</b>\n{subs_text if subs_text else '<i>None</i>'}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🍿 <b>How to play:</b> Paste the URL into <b>VLC</b> or <b>KMPlayer</b>. "
                    f"If it doesn't play, set the <b>Referer</b> in your player settings!\n\n"
                    f"⚠️ <i>If the current server doesn't work, please go back and try another server.\n"
                    f"For any issues, report to the admin: {DEV_CONTACT}</i>"
                )

                keyboard = [[InlineKeyboardButton("🎬 Watch Now", url=player_url)]]

                await loading.delete()
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=final_text,
                    parse_mode='HTML',
                    disable_web_page_preview=True,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await loading.edit_text(
                    f"⚠️ <b>Generation failed after 3 tries.</b>\n\n"
                    f"🕙 Please <b>wait 2 minutes</b> before trying this episode again.\n"
                    f"🆘 If this persists, contact {DEV_CONTACT}!",
                    parse_mode='HTML'
                )

    except Exception as e:
        logger.error(f"Logic Error: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="🌸 <b>Something went wrong!</b> Please try /start to reset.",
            parse_mode='HTML'
        )

# --- MAIN ---
def main():
    t_request = HTTPXRequest(proxy=PROXY_URL, connect_timeout=30.0, read_timeout=30.0)
    application = Application.builder().token(BOT_TOKEN).request(t_request).get_updates_request(t_request).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_search, pattern="^start_search$")],
        states={WAITING_FOR_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search)]},
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(about_bot, pattern="^about_bot$"))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Bot is spinning up... 🚀")
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
