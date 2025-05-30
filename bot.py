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
TOKEN         = os.getenv("TELEGRAM_TOKEN")
LOCAL_API_URL = os.getenv("TELEGRAM_LOCAL_API")  # e.g. "http://127.0.0.1:8081/bot/"
API_BASE      = os.getenv(
    "ANIWATCH_API_BASE",
    "http://localhost:4000/api/v2/hianime"
)

if not TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN not set in .env")
if not LOCAL_API_URL:
    raise RuntimeError("TELEGRAM_LOCAL_API not set in .env (must end in /bot/)")

#─── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

#─── Helpers ────────────────────────────────────────────────────────────────────
def extract_slug_ep(hianime_url: str) -> tuple[str, str]:
    parts = urlparse(hianime_url).path.strip("/").split("/")
    return parts[-2], parts[-1].split("-")[-1]

def get_m3u8_and_referer(
    slug: str,
    ep: str,
    server: str = "hd-1",
    category: str = "sub"
) -> tuple[str, str|None]:
    resp = requests.get(
        f"{API_BASE}/episode/sources",
        params={
            "animeEpisodeId": f"{slug}?ep={ep}",
            "server": server,
            "category": category,
        }
    )
    resp.raise_for_status()
    data    = resp.json().get("data", {})
    sources = data.get("sources", [])
    for s in sources:
        if s.get("type") == "hls" or s.get("url", "").endswith(".m3u8"):
            m3u8 = s["url"]
            break
    else:
        raise RuntimeError("No HLS source found")
    referer = data.get("headers", {}).get("Referer")
    return m3u8, referer

def remux_hls_to_mp4(m3u8_url: str, referer: str|None, output_path: str) -> None:
    cmd = ["ffmpeg", "-y"]
    if referer:
        cmd += ["-headers", f"Referer: {referer}\r\n"]
    cmd += ["-i", m3u8_url, "-c", "copy", output_path]
    subprocess.run(cmd, check=True)

#─── Bot handlers ───────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Hi! Send me a Hianime.to episode URL and I'll download and send the MP4 (up to 2 GB)."
    )

async def download_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    url = update.message.text.strip()
    chat_id = update.effective_chat.id
    logging.info("Received URL: %s", url)

    status = await update.message.reply_text("⏳ Fetching stream URL…")
    try:
        slug, ep = extract_slug_ep(url)
        m3u8_url, referer = get_m3u8_and_referer(slug, ep)

        os.makedirs("downloads", exist_ok=True)
        out_file = f"downloads/{slug}_{ep}.mp4"
        await status.edit_text("⏳ Downloading & remuxing…")
        remux_hls_to_mp4(m3u8_url, referer, out_file)

        await status.edit_text("🚀 Uploading to Telegram…")
        with open(out_file, "rb") as video:
            await context.bot.send_video(chat_id=chat_id, video=video)

        await status.edit_text("✅ Done!")
    except Exception as e:
        logging.exception("Error in download_and_send")
        await status.edit_text(f"❌ Failed: {e}")

#─── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    # LOCAL_API_URL already ends in "/bot/", so Python-telegram-bot will build:
    #   LOCAL_API_URL + TOKEN + "/" + METHOD
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .base_url(LOCAL_API_URL)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, download_and_send)
    )
    app.run_polling()

if __name__ == "__main__":
    main()
