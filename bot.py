import os
import aiohttp
import logging
import asyncio
import threading
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

# --- WEB SERVER (For Render/HuggingFace) ---
app = Flask(__name__)

@app.route('/')
def health_check(): 
    return "Bot is Running!"

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

WAITING_FOR_SEARCH = 1

# --- HELPER FUNCTIONS ---
async def fetch_api(url):
    """Fetches data from the Anime API using the proxy."""
    connector = ProxyConnector.from_url(PROXY_URL)
    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            async with session.get(url, timeout=25) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"API Error: Status {response.status}")
        except Exception as e:
            logger.error(f"Fetch Error: {e}")
    return None

def chunk_list(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    text = (
        f"🌸 <b>Welcome, {user_name}!</b>\n\n"
        f"🤖 I am an advanced Anime Bot.\n"
        f"I can help you search for animes, view details, and fetch streaming links!\n\n"
        f"👇 Click the button below to get started."
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
    text = (
        "✏️ <b>What anime are you looking for?</b>\n\n"
        "<i>Please type the name below.</i> ✨"
    )
    await context.bot.send_message(chat_id=query.message.chat_id, text=text, parse_mode='HTML')
    return WAITING_FOR_SEARCH

async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    search_query = update.message.text
    context.user_data['search_query'] = search_query
    await fetch_and_display_search(update.message.chat_id, context, page=1)
    return ConversationHandler.END

async def fetch_and_display_search(chat_id, context, page=1, message_to_edit=None):
    query = context.user_data.get('search_query')
    url = f"{BASE_URL}/search?q={query}&page={page}"
    
    if not message_to_edit:
        loading_msg = await context.bot.send_message(chat_id=chat_id, text="⏳ <i>Searching the database...</i>", parse_mode='HTML')
    else:
        loading_msg = message_to_edit
        await loading_msg.edit_text("⏳ <i>Searching the database...</i>", parse_mode='HTML')

    data = await fetch_api(url)
    
    if not data or data.get('status') != 200 or not data.get('data', {}).get('animes'):
        await loading_msg.edit_text("❌ No animes found. Try again! /start")
        return

    animes = data['data']['animes']
    has_next = data['data'].get('hasNextPage', False)
    
    # Create the Mapping to avoid 64-byte limits
    context.user_data['anime_map'] = {str(i): anime['id'] for i, anime in enumerate(animes)}
    
    keyboard = []
    for i, anime in enumerate(animes):
        # We only pass the map ID (e.g., 'id|0', 'id|1')
        keyboard.append([InlineKeyboardButton(f"🎬 {anime['name']}", callback_data=f"id|{i}")])
        
    nav_buttons = []
    if page > 1: 
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page|{page-1}"))
    if has_next: 
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"page|{page+1}"))
    if nav_buttons: 
        keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"🔎 <b>Results for:</b> <i>{query}</i> (Page {page})"
    
    await loading_msg.edit_text(text=text, parse_mode='HTML', reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    # --- PAGINATION FOR SEARCH ---
    if data.startswith("page|"):
        page = int(data.split("|")[1])
        await fetch_and_display_search(chat_id, context, page, message_to_edit=query.message)

    # --- ANIME SELECTED ---
    elif data.startswith("id|"):
        idx = data.split("|")[1]
        anime_id = context.user_data.get('anime_map', {}).get(idx)
        
        if not anime_id:
            await context.bot.send_message(chat_id=chat_id, text="❌ Session expired. Please search again. /start")
            return

        url = f"{BASE_URL}/anime/{anime_id}"
        loading_msg = await context.bot.send_message(chat_id=chat_id, text="⏳ <i>Fetching details...</i>", parse_mode='HTML')
        api_data = await fetch_api(url)
        await loading_msg.delete()

        if api_data and api_data.get('status') == 200:
            info = api_data['data']['anime']['info']
            stats = info.get('stats', {})
            eps = stats.get('episodes', {})
            caption = (
                f"🌟 <b>{info.get('name', 'Unknown')}</b>\n\n"
                f"📺 <b>Type:</b> {stats.get('type', 'N/A')}\n"
                f"🔊 <b>Episodes:</b> Sub: {eps.get('sub', 0)} | Dub: {eps.get('dub', 0)}\n\n"
                f"📝 <b>Synopsis:</b> {info.get('description', 'No description.')[:400]}..."
            )
            # Pass the mapped index to the episodes button
            keyboard = [[InlineKeyboardButton("▶️ Fetch Episodes", callback_data=f"eps|{idx}|1")]]
            
            if info.get('poster'):
                await context.bot.send_photo(chat_id=chat_id, photo=info.get('poster'), caption=caption, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await context.bot.send_message(chat_id=chat_id, text=caption, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

    # --- FETCH EPISODES ---
        # --- FETCH EPISODES ---
    elif data.startswith("eps|"):
        parts = data.split("|")
        idx, page = parts[1], int(parts[2])
        anime_id = context.user_data.get('anime_map', {}).get(idx)
        
        if not anime_id:
            await context.bot.send_message(chat_id=chat_id, text="❌ Session expired. Please search again. /start")
            return
            
        url = f"{BASE_URL}/anime/{anime_id}/episodes"
        api_data = await fetch_api(url)
        
        if api_data and api_data.get('status') == 200:
            episodes = api_data['data'].get('episodes', [])
            
            if not episodes:
                await context.bot.send_message(chat_id=chat_id, text="❌ No episodes found for this anime.")
                return

            # Create a map for episodes to avoid the 64-byte limit
            context.user_data['ep_map'] = {str(i): ep['episodeId'] for i, ep in enumerate(episodes)}
            
            chunks = list(chunk_list(episodes, 40))
            if not chunks:
                await context.bot.send_message(chat_id=chat_id, text="❌ No episodes found for this anime.")
                return
                
            current_chunk = chunks[page-1]
            start_index = (page - 1) * 40
            
            keyboard = []
            row = []
            for i, ep in enumerate(current_chunk):
                real_idx = start_index + i
                # Make sure to handle missing 'number' gracefully
                ep_num = ep.get('number', real_idx + 1) 
                row.append(InlineKeyboardButton(f"Ep {ep_num}", callback_data=f"srv|{real_idx}"))
                if len(row) == 4:
                    keyboard.append(row)
                    row = []
            if row: keyboard.append(row)
            
            nav = []
            if page > 1: nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"eps|{idx}|{page-1}"))
            if page < len(chunks): nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"eps|{idx}|{page+1}"))
            if nav: keyboard.append(nav)
            
            # FIX: Safely check text content so it doesn't crash on photo captions
            msg_text = query.message.text or query.message.caption or ""
            
            if "Select Episode" in msg_text:
                await query.message.edit_text(
                    text="📺 <b>Select Episode:</b>", 
                    parse_mode='HTML', 
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id, 
                    text="📺 <b>Select Episode:</b>", 
                    parse_mode='HTML', 
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        else:
            await context.bot.send_message(chat_id=chat_id, text="❌ Failed to fetch episodes from the API.")


    # --- SELECT SERVER ---
    elif data.startswith("srv|"):
        ep_idx = data.split("|")[1]
        ep_id = context.user_data.get('ep_map', {}).get(ep_idx)
        
        if not ep_id:
            await context.bot.send_message(chat_id=chat_id, text="❌ Session expired. Please fetch episodes again.")
            return

        url = f"{BASE_URL}/episode/servers?animeEpisodeId={ep_id}"
        api_data = await fetch_api(url)
        
        if api_data and api_data.get('status') == 200:
            servers = api_data['data']
            keyboard = []
            
            # Support for sub, dub, and raw
            for s in servers.get('sub', []):
                keyboard.append([InlineKeyboardButton(f"🟢 SUB: {s['serverName']}", callback_data=f"src|{ep_idx}|{s['serverName']}|sub")])
            for s in servers.get('dub', []):
                keyboard.append([InlineKeyboardButton(f"🔵 DUB: {s['serverName']}", callback_data=f"src|{ep_idx}|{s['serverName']}|dub")])
            for s in servers.get('raw', []):
                keyboard.append([InlineKeyboardButton(f"⚪ RAW: {s['serverName']}", callback_data=f"src|{ep_idx}|{s['serverName']}|raw")])
                
            if not keyboard:
                await context.bot.send_message(chat_id=chat_id, text="❌ No streaming servers found for this episode.")
                return
                
            await context.bot.send_message(chat_id=chat_id, text="🎛️ <b>Select Server:</b>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

    # --- FETCH FINAL STREAM ---
    elif data.startswith("src|"):
        _, ep_idx, s_name, cat = data.split("|")
        ep_id = context.user_data.get('ep_map', {}).get(ep_idx)
        
        url = f"{BASE_URL}/episode/sources?animeEpisodeId={ep_id}&server={s_name}&category={cat}"
        api_data = await fetch_api(url)
        
        if api_data and api_data.get('status') == 200:
            src = api_data['data']
            m3u8 = next((s['url'] for s in src.get('sources', []) if s.get('isM3U8')), None)
            
            if not m3u8:
                await context.bot.send_message(chat_id=chat_id, text="❌ Could not extract M3U8 streaming link from this server.")
                return
                
            text = (
                f"✅ <b>Stream Found!</b>\n\n"
                f"🖥️ <b>Server:</b> {s_name} ({cat.upper()})\n"
                f"🔗 <b>Stream URL:</b>\n<code>{m3u8}</code>\n\n"
                f"🍿 <i>Copy the URL and paste it into a network stream player like VLC!</i>"
            )
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode='HTML')

# --- MAIN INITIALIZATION ---
def main():
    # Setup HTTPX proxy routing
    t_request = HTTPXRequest(
        proxy=PROXY_URL, 
        connect_timeout=30.0, 
        read_timeout=30.0
    )
    t_get_updates_request = HTTPXRequest(
        proxy=PROXY_URL, 
        connect_timeout=30.0, 
        read_timeout=30.0
    )
    
    # Build the Application
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(t_request) 
        .get_updates_request(t_get_updates_request)
        .build()
    )

    # Setup Handlers
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

    # Start the Bot
    logger.info("Bot is starting up via Proxy...")
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
