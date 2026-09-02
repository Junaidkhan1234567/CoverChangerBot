# log_utils.py
import logging
from datetime import datetime
from telegram import Bot

logger = logging.getLogger(__name__)

async def force_send_log(bot: Bot, channel_id: str, message: str) -> bool:
    """Force send log with retry"""
    if not channel_id:
        logger.warning("⚠️ LOG_CHANNEL_ID not set, skipping log")
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
    if not channel_id:
        return
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
    if not channel_id:
        return
    msg = (
        f"🖼️ <b>Thumbnail Set</b>\n\n"
        f"👤 User: <code>{user_id}</code>\n"
        f"📌 Username: @{username}\n"
        f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await force_send_log(bot, channel_id, msg)

async def log_video_processed(bot: Bot, channel_id: str, user_id: int, username: str):
    """Log video processing"""
    if not channel_id:
        return
    msg = (
        f"🎬 <b>Video Processed</b>\n\n"
        f"👤 User: <code>{user_id}</code>\n"
        f"📌 Username: @{username}\n"
        f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await force_send_log(bot, channel_id, msg)

async def log_thumbnail_deleted(bot: Bot, channel_id: str, user_id: int, username: str):
    """Log thumbnail deletion"""
    if not channel_id:
        return
    msg = (
        f"🗑️ <b>Thumbnail Deleted</b>\n\n"
        f"👤 User: <code>{user_id}</code>\n"
        f"📌 Username: @{username}\n"
        f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await force_send_log(bot, channel_id, msg)

# ✅ NEW: Forward photo to log channel with user info
async def forward_photo_to_log(bot: Bot, channel_id: str, photo_id: str, user_id: int, username: str, caption: str = ""):
    """Forward photo to log channel with user info"""
    if not channel_id:
        return
    
    try:
        log_caption = (
            f"📸 <b>User Sent Photo</b>\n\n"
            f"👤 User ID: <code>{user_id}</code>\n"
            f"📌 Username: @{username}\n"
            f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        if caption:
            log_caption += f"\n\n📝 Caption: {caption[:200]}"
        
        await bot.send_photo(
            chat_id=channel_id,
            photo=photo_id,
            caption=log_caption,
            parse_mode="HTML"
        )
        logger.info(f"✅ Photo forwarded to log channel for user {user_id}")
    except Exception as e:
        logger.error(f"❌ Failed to forward photo: {e}")

# ✅ NEW: Forward video to log channel with user info
async def forward_video_to_log(bot: Bot, channel_id: str, video_id: str, user_id: int, username: str, caption: str = ""):
    """Forward video to log channel with user info"""
    if not channel_id:
        return
    
    try:
        log_caption = (
            f"🎬 <b>User Sent Video</b>\n\n"
            f"👤 User ID: <code>{user_id}</code>\n"
            f"📌 Username: @{username}\n"
            f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        if caption:
            log_caption += f"\n\n📝 Caption: {caption[:200]}"
        
        await bot.send_video(
            chat_id=channel_id,
            video=video_id,
            caption=log_caption,
            parse_mode="HTML"
        )
        logger.info(f"✅ Video forwarded to log channel for user {user_id}")
    except Exception as e:
        logger.error(f"❌ Failed to forward video: {e}")
