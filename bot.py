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
    "http://localhost:4000/api/v2/hianime"
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

def get_m3u8_and_referer(
    slug: str,
    ep: str,
    server: str = "hd-1",
    category: str = "sub"
) -> tuple[str, str|None]:
    """
    Calls the Aniwatch API to get the HLS (.m3u8) URL plus any required Referer.
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
    data    = resp.json().get("data", {})
    sources = data.get("sources", [])
    # find the HLS stream entry
    for s in sources:
        if s.get("type") == "hls" or s.get("url", "").endswith(".m3u8"):
            m3u8 = s["url"]
            break
    else:
        raise RuntimeError("No HLS source found")

    # extract Referer header if provided
    referer = data.get("headers", {}).get("Referer")
    return m3u8, referer

#─── Bot handlers ───────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hi! Send me a Hianime.to episode URL and I'll download the video for you."
    )

async def download_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info(f"💬 got message: {update.message.text!r}")
    url = update.message.text.strip()
    chat_id = update.effective_chat.id

    # let user know we're working
    status = await update.message.reply_text("⏳ Fetching stream URL…")

    try:
        slug, ep = extract_slug_ep(url)
        m3u8, referer = get_m3u8_and_referer(slug, ep)

        # prepare download folder
        os.makedirs("downloads", exist_ok=True)
        out_file = f"downloads/{slug}_{ep}.mp4"

        # build ffmpeg command
        cmd = ["ffmpeg", "-y"]
        if referer:
            # pass the Referer header to ffmpeg
            cmd += ["-headers", f"Referer: {referer}\r\n"]
        cmd += ["-i", m3u8, "-c", "copy", out_file]

        # run ffmpeg to remux HLS → MP4
        subprocess.run(cmd, check=True)

        # send the resulting MP4 back to the user
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
