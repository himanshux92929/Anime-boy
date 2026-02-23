import os
import aiohttp
import logging
import asyncio
import threading
from flask import Flask
from aiohttp_socks import ProxyConnector 
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telegram.request import HTTPXRequest

app = Flask(__name__)

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

threading.Thread(target=run_web_server, daemon=True).start()

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
BASE_URL = "https://aniwatch-api-six-theta.vercel.app/api/v2/hianime"
PROXY_URL = "socks5://zqxtpjjc:cknwbdszk5ux@31.59.20.176:6754"
BOT_TOKEN = "8271227515:AAGZK8k7bARC7VmTkE6UUfOPyg5ZvjGxQ-k"

WAITING_FOR_SEARCH = 1

# --- Helper Functions ---

async def fetch_api(url):
    """Fetches data from the Anime API using the proxy."""
    connector = ProxyConnector.from_url(PROXY_URL)
    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            async with session.get(url, timeout=20) as response:
                if response.status == 200:
                    return await response.json()
                logger.error(f"API Error: Status {response.status}")
        except Exception as e:
            logger.error(f"Fetch Error: {e}")
    return None

def chunk_list(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

# --- Bot Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    text = (
        f"🌸 <b>Welcome, {user_name}!</b>\n\n"
        f"🤖 I am an advanced Anime Bot.\n"
        f"I can help you search for animes and fetch streaming links!\n\n"
        f"👇 Click the button below to start searching."
    )
    keyboard = [[InlineKeyboardButton("🔍 Search Animes", callback_data="start_search")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(text, parse_mode='HTML', reply_markup=reply_markup)
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode='HTML', reply_markup=reply_markup)

async def start_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await context.bot.send_message(chat_id=query.message.chat_id, text="✏️ <b>Type the anime name:</b>", parse_mode='HTML')
    return WAITING_FOR_SEARCH

async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    search_query = update.message.text
    context.user_data['search_query'] = search_query
    await fetch_and_display_search(update.message.chat_id, context, page=1)
    return ConversationHandler.END

async def fetch_and_display_search(chat_id, context, page=1):
    query = context.user_data.get('search_query')
    url = f"{BASE_URL}/search?q={query}&page={page}"
    
    loading_msg = await context.bot.send_message(chat_id=chat_id, text="⏳ <i>Searching...</i>", parse_mode='HTML')
    data = await fetch_api(url)
    
    # FIXED: Check for status == 200 instead of .get('success')
    if not data or data.get('status') != 200 or not data['data'].get('animes'):
        await loading_msg.edit_text("❌ No animes found. Try a different name! /start")
        return

    animes = data['data']['animes']
    has_next = data['data'].get('hasNextPage', False)
    
    keyboard = []
    for anime in animes:
        # Use a short ID or slice to prevent Telegram's 64-byte callback limit
        callback_data = f"anime|{anime['id']}"
        keyboard.append([InlineKeyboardButton(f"🎬 {anime['name']}", callback_data=callback_data[:60])])
        
    nav_buttons = []
    if page > 1: 
        nav_buttons.append(InlineKeyboardButton(f"⬅️ Page {page-1}", callback_data=f"page|{page-1}"))
    if has_next: 
        nav_buttons.append(InlineKeyboardButton(f"Page {page+1} ➡️", callback_data=f"page|{page+1}"))
    
    if nav_buttons: 
        keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=chat_id, 
        text=f"🔎 <b>Results for:</b> <i>{query}</i>\n📄 <b>Page:</b> {page}", 
        parse_mode='HTML', 
        reply_markup=reply_markup
    )
    await loading_msg.delete()

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("page|"):
        page = int(data.split("|")[1])
        await fetch_and_display_search(query.message.chat_id, context, page)

    elif data.startswith("anime|"):
        anime_id = data.split("|")[1]
        url = f"{BASE_URL}/anime/{anime_id}"
        api_data = await fetch_api(url)

        # FIXED: Check for status == 200
        if api_data and api_data.get('status') == 200:
            info = api_data['data']['anime']['info']
            stats = info.get('stats', {})
            eps = stats.get('episodes', {})
            caption = (
                f"🌟 <b>{info.get('name')}</b>\n\n"
                f"📺 <b>Type:</b> {stats.get('type', 'N/A')}\n"
                f"🔊 <b>Episodes:</b> Sub: {eps.get('sub', 0)} | Dub: {eps.get('dub', 0)}\n\n"
                f"📝 <b>Synopsis:</b> {info.get('description', 'No description.')[:350]}..."
            )
            keyboard = [[InlineKeyboardButton("▶️ Fetch Episodes", callback_data=f"eps|{anime_id}|1")]]
            await context.bot.send_photo(
                chat_id=query.message.chat_id, 
                photo=info.get('poster'), 
                caption=caption, 
                parse_mode='HTML', 
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    elif data.startswith("eps|"):
        parts = data.split("|")
        anime_id, page = parts[1], int(parts[2])
        url = f"{BASE_URL}/anime/{anime_id}/episodes"
        api_data = await fetch_api(url)
        
        # FIXED: Check for status == 200
        if api_data and api_data.get('status') == 200:
            episodes = api_data['data']['episodes']
            chunks = list(chunk_list(episodes, 20)) # Reduced chunk size for better display
            current_chunk = chunks[page-1]
            keyboard = []
            row = []
            for ep in current_chunk:
                row.append(InlineKeyboardButton(f"Ep {ep['number']}", callback_data=f"srv|{ep['episodeId']}"))
                if len(row) == 4:
                    keyboard.append(row)
                    row = []
            if row: keyboard.append(row)
            
            nav = []
            if page > 1: nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"eps|{anime_id}|{page-1}"))
            if page < len(chunks): nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"eps|{anime_id}|{page+1}"))
            if nav: keyboard.append(nav)
            
            await context.bot.send_message(chat_id=query.message.chat_id, text="📺 <b>Select Episode:</b>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("srv|"):
        ep_id = data.split("|")[1]
        url = f"{BASE_URL}/episode/servers?animeEpisodeId={ep_id}"
        api_data = await fetch_api(url)
        
        if api_data and api_data.get('status') == 200:
            servers = api_data['data']
            keyboard = []
            for s in servers.get('sub', []):
                keyboard.append([InlineKeyboardButton(f"🟢 SUB: {s['serverName']}", callback_data=f"src|{ep_id}|{s['serverName']}|sub")])
            for s in servers.get('dub', []):
                keyboard.append([InlineKeyboardButton(f"🔵 DUB: {s['serverName']}", callback_data=f"src|{ep_id}|{s['serverName']}|dub")])
            await context.bot.send_message(chat_id=query.message.chat_id, text="🎛️ <b>Select Server:</b>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("src|"):
        _, ep_id, s_name, cat = data.split("|")
        url = f"{BASE_URL}/episode/sources?animeEpisodeId={ep_id}&server={s_name}&category={cat}"
        api_data = await fetch_api(url)
        
        if api_data and api_data.get('status') == 200:
            src = api_data['data']
            m3u8 = next((s['url'] for s in src.get('sources', []) if s.get('isM3U8')), "Not found")
            text = (
                f"✅ <b>Stream Found!</b>\n\n"
                f"🖥️ <b>Server:</b> {s_name} ({cat.upper()})\n"
                f"🔗 <b>Stream URL:</b>\n<code>{m3u8}</code>\n\n"
                f"🍿 <i>Copy URL to VLC or a web player!</i>"
            )
            await context.bot.send_message(chat_id=query.message.chat_id, text=text, parse_mode='HTML')

# --- Main Initialization ---
def main():
    t_request = HTTPXRequest(proxy=PROXY_URL, connect_timeout=30.0, read_timeout=30.0)
    t_get_updates_request = HTTPXRequest(proxy=PROXY_URL, connect_timeout=30.0, read_timeout=30.0)
    
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(t_request) 
        .get_updates_request(t_get_updates_request)
        .build()
    )

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_search, pattern="^start_search$")],
        states={
            WAITING_FOR_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search)]
        },
        fallbacks=[CommandHandler("start", start)]
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Bot is starting...")
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
