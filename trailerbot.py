import asyncio
import logging
import requests
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode

# Load environment variables
load_dotenv()
# ── CONFIG ─────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN")
TARGET_CHANNEL = "-1003600503921"
ADMIN_ID = 1059586105
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

SEARCH_QUERIES = [
    "official trailer",
    "official teaser",
    "new movie trailer",
]

MAX_PER_QUERY = 5
sessions = {}

# ── FILTERED FETCH ─────────────────────────────────
def _fetch_sync():
    results = []
    seen = set()

    bad_keywords = [
        "reaction", "review", "breakdown",
        "explained", "fan", "edit", "spoof"
    ]

    good_channels = [
    "Sony Pictures", "Warner Bros", "Marvel",
    "Netflix", "Prime Video", "Disney",
    "Universal Pictures", "Paramount",

    # Add more here 👇
    "A24", "Lionsgate", "20th Century Studios",
    "StudioCanal", "Columbia Pictures",
    "Focus Features", "Searchlight Pictures",

    # Indian (important for you)
    "T-Series", "Sony Music India",
    "Zee Studios", "Dharma Productions",
    "Lyca Productions", "Sun TV",
    "Think Music India", "Aditya Music"
]

    recent_limit = datetime.utcnow() - timedelta(days=7)

    for query in SEARCH_QUERIES:
        url = "https://www.googleapis.com/youtube/v3/search"

        params = {
            "part": "snippet",
            "q": query,
            "key": YOUTUBE_API_KEY,
            "maxResults": MAX_PER_QUERY,
            "type": "video",
            "order": "date",
        }

        try:
            res = requests.get(url, params=params, timeout=10)
            data = res.json()
        except Exception as e:
            logger.error(f"Request failed for {query}: {e}")
            continue

        for item in data.get("items", []):
            sn = item["snippet"]
            title = sn["title"].lower()
            channel = sn["channelTitle"]
            date_str = sn["publishedAt"]

            vid_id = item["id"]["videoId"]

            if vid_id in seen:
                continue

            # ❌ 1. remove junk FIRST (very important)
            if any(word in title for word in bad_keywords):
                continue

            # ✅ 2. allow if official channel
            if any(gc.lower() in channel.lower() for gc in good_channels):
             pass

            # ✅ 3. OR allow strong trailer titles
            elif "official trailer" in title or "official teaser" in title:
             pass

            # ❌ 4. reject everything else
            else:
             continue

            # ❌ remove old videos
            video_date = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ")
            if video_date < recent_limit:
                continue

            seen.add(vid_id)

            thumb = (
                sn["thumbnails"].get("high")
                or sn["thumbnails"].get("medium")
                or {}
            )

            results.append({
                "id": vid_id,
                "title": sn["title"],
                "channel": channel,
                "thumb": thumb.get("url", ""),
                "date": date_str[:10],
                "url": f"https://youtu.be/{vid_id}",
            })

    return results


async def fetch_videos():
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_sync)

# ── KEYBOARD ───────────────────────────────────────
def build_keyboard(videos, selected):
    rows = []

    for i, v in enumerate(videos):
        icon = "✅" if i in selected else "🎬"
        label = v["title"][:45]
        rows.append([InlineKeyboardButton(f"{icon} {label}", callback_data=f"t:{i}")])

    actions = []
    if selected:
        actions.append(InlineKeyboardButton(f"✈️ Send {len(selected)}", callback_data="send"))
    actions.append(InlineKeyboardButton("🏁 Finish", callback_data="finish"))

    rows.append(actions)
    return InlineKeyboardMarkup(rows)

# ── COMMANDS ───────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎬 TrailerBot\n\nUse /fetch to get latest official trailers")


async def cmd_fetch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Not authorized")
        return

    msg = await update.message.reply_text("🔍 Fetching latest official trailers...")

    videos = await fetch_videos()

    if not videos:
        await msg.edit_text("❌ No official trailers found (last 7 days)")
        return

    sessions[update.effective_user.id] = {
        "videos": videos,
        "selected": set()
    }

    await msg.edit_text(
        f"🎬 Found {len(videos)} official trailers",
        reply_markup=build_keyboard(videos, set())
    )

# ── CALLBACKS ──────────────────────────────────────
async def cb_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    sess = sessions.get(uid)

    if not sess:
        return

    idx = int(q.data.split(":")[1])

    if idx in sess["selected"]:
        sess["selected"].remove(idx)
    else:
        sess["selected"].add(idx)

    await q.edit_message_reply_markup(
        reply_markup=build_keyboard(sess["videos"], sess["selected"])
    )


async def cb_send(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    sess = sessions.get(uid)

    if not sess:
        return

    for idx in sess["selected"]:
        v = sess["videos"][idx]

        caption = f"""🎬 *{v['title']}*

📺 {v['channel']}
📅 {v['date']}

🔗 {v['url']}"""

        await ctx.bot.send_message(
            chat_id=TARGET_CHANNEL,
            text=caption,
            parse_mode=ParseMode.MARKDOWN
        )

        await asyncio.sleep(0.5)

    await q.edit_message_text("✅ Sent to channel")


async def cb_finish(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    sessions.pop(q.from_user.id, None)
    await q.edit_message_text("Session closed")

# ── MAIN ───────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("fetch", cmd_fetch))

    app.add_handler(CallbackQueryHandler(cb_toggle, pattern=r"^t:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_send, pattern="send"))
    app.add_handler(CallbackQueryHandler(cb_finish, pattern="finish"))

    print("🤖 Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()