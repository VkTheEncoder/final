#!/usr/bin/env python3
import os
import logging
import subprocess
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

#─── Load config ────────────────────────────────────────────────────────────────
load_dotenv()
TOKEN    = os.getenv("TELEGRAM_TOKEN")
API_BASE = os.getenv(
    "ANIWATCH_API_BASE",
    "https://api-aniwatch.onrender.com/api/v2/hianime"
)
if not TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN not set in .env")

#─── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

#─── Helpers ───────────────────────────────────────────────────────────────────
def extract_slug_ep(hianime_url: str):
    """
    From https://hianime.to/watch/steinsgate-3/episode-230
    → slug='steinsgate-3', ep='230'
    """
    parts = urlparse(hianime_url).path.strip("/").split("/")
    return parts[-2], parts[-1].split("-")[-1]

def get_m3u8(slug: str, ep: str,
            server: str = "hd-1", category: str = "sub") -> str:
    """
    Calls the Aniwatch API to get the HLS (.m3u8) URL.
    """
    resp = requests.get(
        f"{API_BASE}/episode/sources",
        params={
            "animeEpisodeId": f"{slug}?ep={ep}",
            "server": server,
            "category": category
        }
    )
    resp.raise_for_status()
    sources = resp.json().get("data", {}).get("sources", [])
    for s in sources:
        if s.get("isM3U8"):
            return s["url"]
    raise RuntimeError("No HLS source found")

#─── Bot handlers ───────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hi! Send me a Hianime.to episode URL and I'll download the video for you."
    )

async def download_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info(f"💬 got message: {update.message.text!r}")
    url = update.message.text.strip()
    chat_id = update.effective_chat.id
    status = await update.message.reply_text("⏳ Fetching stream URL…")

    try:
        slug, ep = extract_slug_ep(url)
        m3u8  = get_m3u8(slug, ep)

        os.makedirs("downloads", exist_ok=True)
        out_file = f"downloads/{slug}_{ep}.mp4"

        subprocess.run(
            ["ffmpeg", "-y", "-i", m3u8, "-c", "copy", out_file],
            check=True
        )

        with open(out_file, "rb") as vid:
            await context.bot.send_video(chat_id=chat_id, video=vid)

        await status.edit_text("✅ Here’s your video!")
    except Exception as e:
        await status.edit_text(f"❌ Failed: {e}")

#─── Main ───────────────────────────────────────────────────────────────────────
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, download_and_send)
    )
    app.run_polling()

if __name__ == "__main__":
    main()
