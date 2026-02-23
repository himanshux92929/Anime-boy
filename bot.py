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

# --- HELPER FUNCTIONS ---
async def fetch_api(url, retries=1):
    """Fetch API with optional retry logic."""
    connector = ProxyConnector.from_url(PROXY_URL)
    for attempt in range(retries):
        async with aiohttp.ClientSession(connector=connector) as session:
            try:
                async with session.get(url, timeout=20) as response:
                    if response.status == 200:
                        return await response.json()
                    logger.error(f"Attempt {attempt+1}: API Error {response.status}")
            except Exception as e:
                logger.error(f"Attempt {attempt+1}: Fetch Error {e}")
        if attempt < retries - 1:
            await asyncio.sleep(2) # Wait before retrying
    return None

def chunk_list(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode='HTML', reply_markup=reply_markup)

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
    await context.bot.send_message(chat_id=query.message.chat_id, text="✏️ <b>Please type the name of the Anime:</b>\n(Example: <i>Naruto</i> or <i>Solo Leveling</i>)", parse_mode='HTML')
    return WAITING_FOR_SEARCH

async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    search_query = update.message.text
    context.user_data['search_query'] = search_query
    await fetch_and_display_search(update.message.chat_id, context, page=1)
    return ConversationHandler.END

async def fetch_and_display_search(chat_id, context, page=1):
    query_str = context.user_data.get('search_query')
    url = f"{BASE_URL}/search?q={query_str}&page={page}"
    
    loading_msg = await context.bot.send_message(chat_id=chat_id, text="🍭 <b>Searching for your favorites...</b>", parse_mode='HTML')

    data = await fetch_api(url)
    
    if not data or data.get('status') != 200 or not data.get('data', {}).get('animes'):
        await loading_msg.edit_text("💔 <b>Aww, I couldn't find that!</b>\nTry a different spelling or check /start.")
        return

    animes = data['data']['animes']
    has_next = data['data'].get('hasNextPage', False)
    
    # Store IDs using names to keep them persistent across messages
    if 'anime_map' not in context.user_data: context.user_data['anime_map'] = {}
    
    keyboard = []
    for anime in animes:
        # We use short hash or part of ID for callback to avoid 64-byte limit
        short_id = anime['id']
        context.user_data['anime_map'][short_id] = anime['id']
        keyboard.append([InlineKeyboardButton(f"🎬 {anime['name']}", callback_data=f"id|{short_id}")])
        
    nav_buttons = []
    if page > 1: nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page|{page-1}"))
    if has_next: nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"page|{page+1}"))
    if nav_buttons: keyboard.append(nav_buttons)

    text = f"🔎 <b>Results for:</b> <i>{query_str}</i>\n📄 Page: <b>{page}</b>\n\n✨ <i>Pick one to see details!</i>"
    await loading_msg.delete() # Remove the "Searching..." message
    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    chat_id = query.message.chat_id
    await query.answer("Working on it... ✨")

    try:
        if data.startswith("page|"):
            page = int(data.split("|")[1])
            await fetch_and_display_search(chat_id, context, page)

        elif data.startswith("id|"):
            anime_id = data.split("|")[1]
            loading = await context.bot.send_message(chat_id=chat_id, text="🎀 <b>Fetching cute details...</b>", parse_mode='HTML')
            api_data = await fetch_api(f"{BASE_URL}/anime/{anime_id}")

            if api_data and api_data.get('status') == 200:
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
                    await context.bot.send_photo(chat_id=chat_id, photo=info.get('poster'), caption=caption, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
                else:
                    await context.bot.send_message(chat_id=chat_id, text=caption, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

        elif data.startswith("eps|"):
            _, anime_id, page = data.split("|")
            page = int(page)
            loading = await context.bot.send_message(chat_id=chat_id, text="🌈 <b>Getting the episode list for you...</b>", parse_mode='HTML')

            api_data = await fetch_api(f"{BASE_URL}/anime/{anime_id}/episodes")
            if api_data and api_data.get('status') == 200:
                episodes = api_data['data'].get('episodes', [])
                if 'ep_map' not in context.user_data: context.user_data['ep_map'] = {}
                
                chunks = list(chunk_list(episodes, 40))
                current_chunk = chunks[page-1]
                
                keyboard = []
                row = []
                for ep in current_chunk:
                    # Map the episodeId to a key to avoid long callback data
                    ep_key = ep['episodeId'].split('?ep=')[-1]
                    context.user_data['ep_map'][ep_key] = ep['episodeId']
                    row.append(InlineKeyboardButton(f"Ep {ep['number']}", callback_data=f"srv|{ep_key}"))
                    if len(row) == 4:
                        keyboard.append(row)
                        row = []
                if row: keyboard.append(row)
                
                nav = []
                if page > 1: nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"eps|{anime_id}|{page-1}"))
                if page < len(chunks): nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"eps|{anime_id}|{page+1}"))
                if nav: keyboard.append(nav)
                
                await loading.delete()
                await context.bot.send_message(chat_id=chat_id, text="📺 <b>Which episode will we watch?</b>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

        elif data.startswith("srv|"):
            ep_key = data.split("|")[1]
            ep_id = context.user_data.get('ep_map', {}).get(ep_key)
            
            loading = await context.bot.send_message(chat_id=chat_id, text="⚡ <b>Looking for the best servers...</b>", parse_mode='HTML')
            api_data = await fetch_api(f"{BASE_URL}/episode/servers?animeEpisodeId={ep_id}")
            
            if api_data and api_data.get('status') == 200:
                servers = api_data['data']
                keyboard = []
                for cat in ['sub', 'dub']:
                    for s in servers.get(cat, []):
                        icon = "🟢" if cat == "sub" else "🔵"
                        keyboard.append([InlineKeyboardButton(f"{icon} {cat.upper()}: {s['serverName']}", callback_data=f"src|{ep_key}|{s['serverName']}|{cat}")])
                
                await loading.delete()
                await context.bot.send_message(chat_id=chat_id, text="🎛️ <b>Select your preferred Quality/Server:</b>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

        elif data.startswith("src|"):
            _, ep_key, s_name, cat = data.split("|")
            ep_id = context.user_data.get('ep_map', {}).get(ep_key)
            
            loading = await context.bot.send_message(chat_id=chat_id, text="🚀 <b>Generating your magic link...</b>", parse_mode='HTML')
            
            url = f"{BASE_URL}/episode/sources?animeEpisodeId={ep_id}&server={s_name}&category={cat}"
            # RETRY LOGIC: Try 3 times
            api_data = await fetch_api(url, retries=3)
            
            if api_data and api_data.get('status') == 200:
                res = api_data['data']
                m3u8 = next((s['url'] for s in res.get('sources', []) if s.get('isM3U8')), None)
                
                if not m3u8:
                    await loading.edit_text("❌ <b>Oopsie!</b> Link generation failed. Please try a different server!")
                    return

                subs_text = "".join([f"▪️ <a href='{track['url']}'>{track['lang'].upper()}</a>\n" for track in res.get('tracks', []) if track.get('lang') != 'thumbnails'])
                referer = res.get('headers', {}).get('Referer', 'None')
                
                final_text = (
                    f"✅ <b>Link Ready to Sparkle!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🖥️ <b>Server:</b> {s_name} ({cat.upper()})\n\n"
                    f"🔗 <b>Stream URL (M3U8):</b>\n<code>{m3u8}</code>\n\n"
                    f"🌐 <b>Referer:</b> (Use only if it doesn't play!)\n<code>{referer}</code>\n\n"
                    f"📝 <b>Available Subtitles:</b>\n{subs_text if subs_text else '<i>None Found</i>'}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🍿 <b>Instructions:</b>\n"
                    f"1. Copy the URL.\n"
                    f"2. Open <b>VLC</b> or <b>KMPlayer</b>.\n"
                    f"3. Paste URL. If it fails, add the <b>Referer</b> in settings!"
                )
                await loading.delete()
                await context.bot.send_message(chat_id=chat_id, text=final_text, parse_mode='HTML', disable_web_page_preview=True)
            else:
                await loading.edit_text(
                    f"⚠️ <b>I'm so sorry!</b> I tried 3 times but the link wouldn't generate.\n\n"
                    f"🕙 Please <b>wait 2 minutes</b> and try again!\n"
                    f"🆘 If it keeps failing, tell {DEV_CONTACT}!"
                )

    except Exception as e:
        logger.error(f"Error: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"🌸 <b>Something went a bit wrong!</b>\nPlease try again or contact {DEV_CONTACT}.", parse_mode='HTML')

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
    application.add_handler(CallbackQueryHandler(about_bot, pattern="^about_bot$"))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(button_handler))

    logger.info("The cutie bot is alive!")
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
