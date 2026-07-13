# log_utils.py
import logging
from datetime import datetime
from telegram import Bot

logger = logging.getLogger(__name__)

async def force_send_log(bot: Bot, channel_id: str, message: str) -> bool:
    """Force send log with retry"""
    if not channel_id:
        return False
    
    try:
        await bot.send_message(
            chat_id=channel_id,
            text=message,
            parse_mode="HTML"
        )
        logger.info(f"✅ Log sent to {channel_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Log send failed: {e}")
        # Without HTML
        try:
            clean = message.replace('<', '').replace('>', '')
            await bot.send_message(
                chat_id=channel_id,
                text=clean
            )
            logger.info(f"✅ Log sent (without HTML)")
            return True
        except Exception as e2:
            logger.error(f"❌ Both attempts failed: {e2}")
            return False

async def log_user_start(bot: Bot, channel_id: str, user_id: int, username: str, first_name: str):
    """Log user start"""
    msg = (
        f"🆕 <b>User Started Bot</b>\n\n"
        f"👤 ID: <code>{user_id}</code>\n"
        f"📌 Username: @{username}\n"
        f"📝 Name: {first_name}\n"
        f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await force_send_log(bot, channel_id, msg)

async def log_thumbnail_set(bot: Bot, channel_id: str, user_id: int, username: str):
    """Log thumbnail set"""
    msg = (
        f"🖼️ <b>Thumbnail Set</b>\n\n"
        f"👤 User: <code>{user_id}</code>\n"
        f"📌 Username: @{username}\n"
        f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await force_send_log(bot, channel_id, msg)

async def log_video_processed(bot: Bot, channel_id: str, user_id: int, username: str):
    """Log video processing"""
    msg = (
        f"🎬 <b>Video Processed</b>\n\n"
        f"👤 User: <code>{user_id}</code>\n"
        f"📌 Username: @{username}\n"
        f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await force_send_log(bot, channel_id, msg)

async def log_thumbnail_deleted(bot: Bot, channel_id: str, user_id: int, username: str):
    """Log thumbnail deletion"""
    msg = (
        f"🗑️ <b>Thumbnail Deleted</b>\n\n"
        f"👤 User: <code>{user_id}</code>\n"
        f"📌 Username: @{username}\n"
        f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await force_send_log(bot, channel_id, msg)
