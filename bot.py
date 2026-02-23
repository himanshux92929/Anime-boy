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

# --- WEB SERVER (For Deployment) ---
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
DEV_CONTACT = "@smarterz_bot" # Replace with your telegram username

WAITING_FOR_SEARCH = 1

# --- HELPER FUNCTIONS ---
async def fetch_api(url):
    connector = ProxyConnector.from_url(PROXY_URL)
    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            async with session.get(url, timeout=25) as response:
                if response.status == 200:
                    return await response.json()
                logger.error(f"API Error: {response.status}")
        except Exception as e:
            logger.error(f"Fetch Error: {e}")
    return None

def chunk_list(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    text = (
        f"🌸 <b>Kon'nichiwa, {user_name}!</b>\n\n"
        f"I am your advanced <b>Anime Assistant</b>. Search for any title and I'll fetch the best streaming links for you.\n\n"
        f"✨ <i>Ready to dive in?</i>"
    )
    keyboard = [[InlineKeyboardButton("🔍 Search Anime", callback_data="start_search")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(text, parse_mode='HTML', reply_markup=reply_markup)
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode='HTML', reply_markup=reply_markup)

async def start_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("✏️ <b>Enter the Anime Name:</b>", parse_mode='HTML')
    return WAITING_FOR_SEARCH

async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    search_query = update.message.text
    context.user_data['search_query'] = search_query
    await fetch_and_display_search(update.message.chat_id, context, page=1)
    return ConversationHandler.END

async def fetch_and_display_search(chat_id, context, page=1, message_to_edit=None):
    query_str = context.user_data.get('search_query')
    url = f"{BASE_URL}/search?q={query_str}&page={page}"
    
    status_text = "⏳ <b>Searching the database...</b>"
    if message_to_edit:
        loading_msg = await message_to_edit.edit_text(status_text, parse_mode='HTML')
    else:
        loading_msg = await context.bot.send_message(chat_id=chat_id, text=status_text, parse_mode='HTML')

    data = await fetch_api(url)
    
    if not data or data.get('status') != 200 or not data.get('data', {}).get('animes'):
        await loading_msg.edit_text("❌ <b>No results found.</b> Please try a different name or /start.")
        return

    animes = data['data']['animes']
    has_next = data['data'].get('hasNextPage', False)
    
    context.user_data['anime_map'] = {str(i): anime['id'] for i, anime in enumerate(animes)}
    
    keyboard = []
    for i, anime in enumerate(animes):
        keyboard.append([InlineKeyboardButton(f"🎬 {anime['name']}", callback_data=f"id|{i}")])
        
    nav_buttons = []
    if page > 1: nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page|{page-1}"))
    if has_next: nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"page|{page+1}"))
    if nav_buttons: keyboard.append(nav_buttons)

    text = f"🔎 <b>Results for:</b> <i>{query_str}</i>\n📄 Page: <b>{page}</b>"
    await loading_msg.edit_text(text=text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    chat_id = query.message.chat_id

    # IMMEDIATE PROCESSING FEEDBACK
    await query.answer("Processing...")

    try:
        if data.startswith("page|"):
            page = int(data.split("|")[1])
            await fetch_and_display_search(chat_id, context, page, message_to_edit=query.message)

        elif data.startswith("id|"):
            idx = data.split("|")[1]
            anime_id = context.user_data.get('anime_map', {}).get(idx)
            
            if not anime_id:
                await query.message.reply_text("❌ <b>Session Expired.</b> Please search again.")
                return

            await query.edit_message_text("⏳ <b>Fetching Anime Details...</b>", parse_mode='HTML')
            api_data = await fetch_api(f"{BASE_URL}/anime/{anime_id}")

            if api_data and api_data.get('status') == 200:
                info = api_data['data']['anime']['info']
                stats = info.get('stats', {})
                caption = (
                    f"🌟 <b>{info.get('name', 'Unknown')}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"📺 <b>Type:</b> {stats.get('type', 'N/A')}\n"
                    f"🔊 <b>Episodes:</b> Sub: {stats.get('episodes', {}).get('sub', 0)} | Dub: {stats.get('episodes', {}).get('dub', 0)}\n\n"
                    f"📝 <b>Synopsis:</b>\n<i>{info.get('description', 'No description.')[:350]}...</i>"
                )
                keyboard = [[InlineKeyboardButton("▶️ View Episodes", callback_data=f"eps|{idx}|1")]]
                
                await query.message.delete() # Clean up old message
                if info.get('poster'):
                    await context.bot.send_photo(chat_id=chat_id, photo=info.get('poster'), caption=caption, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
                else:
                    await context.bot.send_message(chat_id=chat_id, text=caption, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

        elif data.startswith("eps|"):
            _, idx, page = data.split("|")
            page = int(page)
            anime_id = context.user_data.get('anime_map', {}).get(idx)
            
            # Show processing
            loading_text = "⏳ <b>Loading Episode List...</b>"
            if query.message.caption:
                await context.bot.send_message(chat_id=chat_id, text=loading_text, parse_mode='HTML')
            else:
                await query.edit_message_text(loading_text, parse_mode='HTML')

            api_data = await fetch_api(f"{BASE_URL}/anime/{anime_id}/episodes")
            
            if api_data and api_data.get('status') == 200:
                episodes = api_data['data'].get('episodes', [])
                context.user_data['ep_map'] = {str(i): ep['episodeId'] for i, ep in enumerate(episodes)}
                
                chunks = list(chunk_list(episodes, 40))
                current_chunk = chunks[page-1]
                start_index = (page - 1) * 40
                
                keyboard = []
                row = []
                for i, ep in enumerate(current_chunk):
                    real_idx = start_index + i
                    row.append(InlineKeyboardButton(f"Ep {ep['number']}", callback_data=f"srv|{real_idx}"))
                    if len(row) == 4:
                        keyboard.append(row)
                        row = []
                if row: keyboard.append(row)
                
                nav = []
                if page > 1: nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"eps|{idx}|{page-1}"))
                if page < len(chunks): nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"eps|{idx}|{page+1}"))
                if nav: keyboard.append(nav)
                
                text = "📺 <b>Select an Episode to Stream:</b>"
                if query.message.caption: # If coming from a photo message
                    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
                else:
                    await query.edit_message_text(text=text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

        elif data.startswith("srv|"):
            ep_idx = data.split("|")[1]
            ep_id = context.user_data.get('ep_map', {}).get(ep_idx)
            
            await query.edit_message_text("⏳ <b>Fetching Servers...</b>", parse_mode='HTML')
            api_data = await fetch_api(f"{BASE_URL}/episode/servers?animeEpisodeId={ep_id}")
            
            if api_data and api_data.get('status') == 200:
                servers = api_data['data']
                keyboard = []
                for cat in ['sub', 'dub', 'raw']:
                    for s in servers.get(cat, []):
                        color = "🟢" if cat == "sub" else "🔵" if cat == "dub" else "⚪"
                        keyboard.append([InlineKeyboardButton(f"{color} {cat.upper()}: {s['serverName']}", callback_data=f"src|{ep_idx}|{s['serverName']}|{cat}")])
                
                if not keyboard:
                    await query.edit_message_text("❌ No servers available.")
                    return
                await query.edit_message_text("🎛️ <b>Select Quality/Server:</b>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

        elif data.startswith("src|"):
            _, ep_idx, s_name, cat = data.split("|")
            ep_id = context.user_data.get('ep_map', {}).get(ep_idx)
            
            await query.edit_message_text("🚀 <b>Generating High-Speed Link...</b>", parse_mode='HTML')
            url = f"{BASE_URL}/episode/sources?animeEpisodeId={ep_id}&server={s_name}&category={cat}"
            api_data = await fetch_api(url)
            
            if api_data and api_data.get('status') == 200:
                res = api_data['data']
                m3u8 = next((s['url'] for s in res.get('sources', []) if s.get('isM3U8')), None)
                
                if not m3u8:
                    await query.edit_message_text("❌ <b>Error:</b> Streaming link not found.")
                    return

                # Parse Subtitles
                subs_text = ""
                for track in res.get('tracks', []):
                    if track.get('lang') != 'thumbnails':
                        subs_text += f"▪️ <a href='{track['url']}'>{track['lang'].upper()}</a>\n"
                
                referer = res.get('headers', {}).get('Referer', 'Not Required')
                
                final_text = (
                    f"✅ <b>Link Ready!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🖥️ <b>Server:</b> {s_name} ({cat.upper()})\n\n"
                    f"🔗 <b>Stream URL (M3U8):</b>\n<code>{m3u8}</code>\n\n"
                    f"🌐 <b>Referer:</b>\n<code>{referer}</code>\n\n"
                    f"📝 <b>Available Subtitles:</b>\n{subs_text if subs_text else '<i>None Found</i>'}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🍿 <i>Tip: Use <b>VLC Player</b> or <b>KMPlayer</b>. Paste the URL and the Referer if needed.</i>"
                )
                await query.edit_message_text(final_text, parse_mode='HTML', disable_web_page_preview=True)

    except Exception as e:
        logger.error(f"Error in button handler: {e}")
        error_msg = f"⚠️ <b>An unexpected error occurred.</b>\n\nTry again later. If this persists, contact {DEV_CONTACT}."
        if query.message:
            await context.bot.send_message(chat_id=chat_id, text=error_msg, parse_mode='HTML')

# --- MAIN INITIALIZATION ---
def main():
    t_request = HTTPXRequest(proxy=PROXY_URL, connect_timeout=30.0, read_timeout=30.0)
    application = Application.builder().token(BOT_TOKEN).request(t_request).get_updates_request(t_request).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_search, pattern="^start_search$")],
        states={WAITING_FOR_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search)]},
        fallbacks=[CommandHandler("start", start)]
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Bot is alive and running...")
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
