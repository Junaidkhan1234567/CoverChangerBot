import asyncio
import logging
import random
import string
import pytz
import aiohttp
import os
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from database import db

logger = logging.getLogger(__name__)

# ============ ENVIRONMENT VARIABLES SE READ KAREIN ============

# Verification Toggle
IS_VERIFY = os.environ.get("IS_VERIFY", "True").lower() == "true"

# Shortlink Toggle
USE_SHORTLINK = os.environ.get("USE_SHORTLINK", "True").lower() == "true"

# Shortlink API
SHORTLINK_API = os.environ.get("SHORTLINK_API", "")
SHORTLINK_API_KEY = os.environ.get("SHORTLINK_API_KEY", "")

# Images
VERIFY_START_IMG = os.environ.get("VERIFY_START_IMG", "")
VERIFY_COMPLETE_IMG = os.environ.get("VERIFY_COMPLETE_IMG", "")

# Tutorial Link
TUTORIAL_LINK = os.environ.get("TUTORIAL_LINK", "https://t.me")

# Log Channel
VERIFIED_LOG = os.environ.get("VERIFIED_LOG", "")

# Timezone
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Kolkata")

# Owner Username
OWNER_USERNAME = os.environ.get("OWNER_USERNAME", "")

# In-memory cache for verification
verification_cache = {}

# ============ SHORTLINK GENERATOR ============

async def get_shortlink(long_url: str) -> str:
    """Generate shortlink using API"""
    if not USE_SHORTLINK:
        return long_url
    
    if not SHORTLINK_API or not SHORTLINK_API_KEY:
        logger.warning("Shortlink API or API Key not configured")
        return long_url
    
    try:
        # Example using shorte.st API
        async with aiohttp.ClientSession() as session:
            data = {
                "urlToShorten": long_url,
                "apiKey": SHORTLINK_API_KEY
            }
            
            async with session.post(SHORTLINK_API, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get("shortenedUrl", long_url)
                else:
                    logger.warning(f"Shortlink API error: {response.status}")
                    return long_url
    except Exception as e:
        logger.error(f"Shortlink generation failed: {e}")
        return long_url

# ============ VERIFICATION ID GENERATOR ============

def generate_verify_id():
    """Generate unique verification ID"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

# ============ VERIFICATION FUNCTIONS ============

async def is_user_verified(user_id: int) -> bool:
    """Check if user is verified"""
    # Agar verification OFF hai toh sabko verified maano
    if not IS_VERIFY:
        return True
    
    user = await db.get_user(user_id)
    
    if not user:
        return False
    
    # Check expiry
    if user.get("verify_expires"):
        if datetime.now() > user["verify_expires"]:
            # Expired - reset
            await db.update_user(user_id, {"is_verified": False})
            return False
    
    return user.get("is_verified", False)

async def create_verification(user_id: int) -> str:
    """Create new verification for user"""
    verify_id = generate_verify_id()
    
    await db.update_user(user_id, {
        "verify_id": verify_id,
        "verify_created": datetime.now(),
        "verify_expires": datetime.now() + timedelta(minutes=10),
        "is_verified": False
    })
    
    return verify_id

async def verify_user(user_id: int, verify_id: str) -> bool:
    """Verify user with ID"""
    user = await db.get_user(user_id)
    
    if not user:
        return False
    
    # Check if verify_id matches and not expired
    if user.get("verify_id") == verify_id:
        if datetime.now() < user.get("verify_expires", datetime.now()):
            # ✅ Verified!
            await db.update_user(user_id, {
                "is_verified": True,
                "verified_at": datetime.now()
            })
            # Remove used verify_id
            await db.update_user(user_id, {"verify_id": None, "verify_expires": None})
            return True
    
    return False

async def reset_user_verification(user_id: int):
    """Reset user verification (admin use)"""
    await db.update_user(user_id, {
        "is_verified": False,
        "verify_id": None,
        "verify_expires": None
    })

# ============ SEND VERIFICATION ALERT ============

async def send_verification_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send verification alert to user"""
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name or "User"
    
    # Agar verification OFF hai toh allow karo
    if not IS_VERIFY:
        return True
    
    # Create new verification
    verify_id = await create_verification(user_id)
    
    # Bot username
    bot_username = (await context.bot.get_me()).username
    
    # Generate link
    long_url = f"https://t.me/{bot_username}?start=verify_{user_id}_{verify_id}"
    
    # Try shortlink
    verify_url = await get_shortlink(long_url)
    
    text = f"""🔐 <b>Verification Required!</b>

Hello {first_name},

⚠️ You need to verify before sending videos!

👇 Click the button below to verify:

💡 <b>Why verify?</b>
• 🛡️ Prevent spam
• 🎯 Better experience
• ⚡ Faster processing

⏳ Link expires in 10 minutes!"""

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Verify Now", url=verify_url)],
        [InlineKeyboardButton("❓ How to Verify?", url=TUTORIAL_LINK)],
        [InlineKeyboardButton("💎 Get Premium (No Verification)", callback_data="get_subscription")]
    ])
    
    try:
        # Send with image if available
        if VERIFY_START_IMG:
            await update.message.reply_photo(
                photo=VERIFY_START_IMG,
                caption=text,
                reply_markup=buttons,
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                text,
                reply_markup=buttons,
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Failed to send verification alert: {e}")
        # Fallback without image
        await update.message.reply_text(
            text,
            reply_markup=buttons,
            parse_mode="HTML"
        )
    
    return False

async def send_verification_success(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send verification success message"""
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name or "User"
    
    text = f"""✅ <b>Verification Successful!</b>

Welcome {first_name}! 🎉

You can now:
📸 Set your thumbnail
🎬 Apply covers to videos
📊 Use all bot features

Send a photo first to get started!"""

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Home", callback_data="menu_back")],
        [InlineKeyboardButton("📸 Set Thumbnail", callback_data="submenu_thumbnails")]
    ])
    
    try:
        if VERIFY_COMPLETE_IMG:
            await update.message.reply_photo(
                photo=VERIFY_COMPLETE_IMG,
                caption=text,
                reply_markup=buttons,
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                text,
                reply_markup=buttons,
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Failed to send verification success: {e}")
        await update.message.reply_text(
            text,
            reply_markup=buttons,
            parse_mode="HTML"
        )

# ============ VERIFICATION LOG ============

async def send_verification_log(context: ContextTypes.DEFAULT_TYPE, user_id: int, status: str):
    """Send verification log to channel"""
    if not VERIFIED_LOG:
        return
    
    user = await db.get_user(user_id)
    username = user.get("username", "Unknown") if user else "Unknown"
    
    text = f"""🔐 <b>Verification Log</b>

👤 User ID: <code>{user_id}</code>
📌 Username: @{username}
📊 Status: {status}
⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    
    try:
        await context.bot.send_message(
            chat_id=VERIFIED_LOG,
            text=text,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Failed to send verification log: {e}")

# ============ ADMIN TOGGLE FUNCTIONS ============

async def toggle_verification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle verification ON/OFF - Admin only"""
    from bot import is_admin
    
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized!")
        return
    
    global IS_VERIFY
    IS_VERIFY = not IS_VERIFY
    
    status = "🟢 ON" if IS_VERIFY else "🔴 OFF"
    
    text = f"""🎛️ <b>Verification Toggle</b>

📊 Status: {status}

Users will {'need to verify' if IS_VERIFY else 'not need to verify'} before sending videos."""
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Toggle", callback_data="toggle_verify")],
        [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
    ])
    
    await update.message.reply_text(
        text,
        reply_markup=buttons,
        parse_mode="HTML"
    )

async def toggle_shortlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle shortlink ON/OFF - Admin only"""
    from bot import is_admin
    
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized!")
        return
    
    global USE_SHORTLINK
    USE_SHORTLINK = not USE_SHORTLINK
    
    status = "🟢 ON" if USE_SHORTLINK else "🔴 OFF"
    
    text = f"""🔗 <b>Shortlink Toggle</b>

📊 Status: {status}

Verification links will {'use shortlink' if USE_SHORTLINK else 'use direct link'}."""
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Toggle", callback_data="toggle_shortlink")],
        [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
    ])
    
    await update.message.reply_text(
        text,
        reply_markup=buttons,
        parse_mode="HTML"
    )
