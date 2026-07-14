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

# ═══════════════════════════════════════════════════════════
# 🔐 VERIFICATION SYSTEM - ALL TOGGLES
# ═══════════════════════════════════════════════════════════

# ─── VERIFICATION TOGGLES ───
VERIFICATION_ENABLED = os.environ.get("VERIFICATION_ENABLED", "True").lower() == "true"

# ─── VERIFICATION IMAGES ───
VERIFY_START_IMG = os.environ.get("VERIFY_START_IMG", "")
VERIFY_COMPLETE_IMG = os.environ.get("VERIFY_COMPLETE_IMG", "")

# ─── TUTORIAL LINK ───
TUTORIAL_LINK = os.environ.get("TUTORIAL_LINK", "")

# ─── LOG CHANNEL ───
VERIFIED_LOG = os.environ.get("VERIFIED_LOG", "")

# ─── TIMEZONE ───
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Kolkata")

# ─── OWNER ───
OWNER_USERNAME = os.environ.get("OWNER_USERNAME", "")

# ─── SHORTLINK CONFIG ───
SHORTLINK_ENABLED = os.environ.get("SHORTLINK_ENABLED", "True").lower() == "true"
SHORTLINK_URL = os.environ.get("SHORTLINK_URL", "gplinks.com")
SHORTLINK_API = os.environ.get("SHORTLINK_API", "")

# ─── POST SHORTLINK CONFIG ───
POST_SHORTLINK_ENABLED = os.environ.get("POST_SHORTLINK_ENABLED", "True").lower() == "true"
POST_SHORTLINK_URL = os.environ.get("POST_SHORTLINK_URL", "gplinks.com")
POST_SHORTLINK_API = os.environ.get("POST_SHORTLINK_API", "")

# ─── VERIFICATION EXPIRY ───
VERIFY_EXPIRE = int(os.environ.get("VERIFY_EXPIRE", "3600"))  # Seconds

# ═══════════════════════════════════════════════════════════

logger.info("🔐 VERIFICATION SETTINGS:")
logger.info(f"VERIFICATION_ENABLED: {VERIFICATION_ENABLED}")
logger.info(f"SHORTLINK_ENABLED: {SHORTLINK_ENABLED}")
logger.info(f"SHORTLINK_URL: {SHORTLINK_URL}")
logger.info(f"POST_SHORTLINK_ENABLED: {POST_SHORTLINK_ENABLED}")
logger.info(f"POST_SHORTLINK_URL: {POST_SHORTLINK_URL}")
logger.info(f"VERIFY_EXPIRE: {VERIFY_EXPIRE} seconds ({VERIFY_EXPIRE//60} minutes)")

# ============ SHORTLINK GENERATOR ============

async def get_shortlink(long_url: str) -> str:
    """Generate shortlink using GP Links or Custom API"""
    if not SHORTLINK_ENABLED:
        logger.info("📌 SHORTLINK_ENABLED is False, using direct link")
        return long_url
    
    if not SHORTLINK_URL:
        logger.warning("⚠️ SHORTLINK_URL not configured")
        return long_url
    
    try:
        # GP Links / Custom API format
        async with aiohttp.ClientSession() as session:
            # Different APIs have different formats
            # GP Links format
            data = {
                "api": SHORTLINK_API,
                "url": long_url,
                "type": "json"  # or "text" depending on API
            }
            
            # Add https:// if not present
            api_url = f"https://{SHORTLINK_URL}/api"
            
            async with session.post(api_url, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    short_url = result.get("shortenedUrl") or result.get("shorturl") or result.get("short_link")
                    if short_url and short_url.startswith("http"):
                        logger.info(f"✅ Shortlink generated: {short_url}")
                        return short_url
                    return long_url
                else:
                    logger.warning(f"⚠️ Shortlink API error: {response.status}")
                    return long_url
    except Exception as e:
        logger.error(f"❌ Shortlink generation failed: {e}")
        return long_url

# ============ POST SHORTLINK GENERATOR ============

async def get_post_shortlink(long_url: str) -> str:
    """Generate shortlink for posts/files using GP Links"""
    if not POST_SHORTLINK_ENABLED:
        logger.info("📌 POST_SHORTLINK_ENABLED is False, using direct link")
        return long_url
    
    if not POST_SHORTLINK_URL:
        logger.warning("⚠️ POST_SHORTLINK_URL not configured")
        return long_url
    
    try:
        async with aiohttp.ClientSession() as session:
            data = {
                "api": POST_SHORTLINK_API,
                "url": long_url,
                "type": "json"
            }
            
            api_url = f"https://{POST_SHORTLINK_URL}/api"
            
            async with session.post(api_url, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    short_url = result.get("shortenedUrl") or result.get("shorturl") or result.get("short_link")
                    if short_url and short_url.startswith("http"):
                        logger.info(f"✅ Post shortlink generated: {short_url}")
                        return short_url
                    return long_url
                else:
                    logger.warning(f"⚠️ Post Shortlink API error: {response.status}")
                    return long_url
    except Exception as e:
        logger.error(f"❌ Post shortlink generation failed: {e}")
        return long_url

# ============ VERIFICATION ID GENERATOR ============

def generate_verify_id():
    """Generate unique verification ID"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

# ============ VERIFICATION FUNCTIONS ============

async def is_user_verified(user_id: int) -> bool:
    """Check if user is verified (with expiry from config)"""
    if not VERIFICATION_ENABLED:
        logger.info(f"ℹ️ Verification is OFF for user {user_id}")
        return True
    
    user = await db.get_user(user_id)
    
    if not user:
        logger.info(f"ℹ️ No user found for {user_id}")
        return False
    
    if not user.get("is_verified", False):
        logger.info(f"❌ User {user_id} is not verified")
        return False
    
    # Check expiry (from VERIFY_EXPIRE in seconds)
    verified_at = user.get("verified_at")
    if verified_at:
        expire_seconds = VERIFY_EXPIRE
        if datetime.now() - verified_at > timedelta(seconds=expire_seconds):
            await db.update_user(user_id, {
                "is_verified": False,
                "verified_at": None
            })
            logger.info(f"⏰ Verification expired for user {user_id} ({expire_seconds} seconds passed)")
            return False
    
    logger.info(f"✅ User {user_id} is verified")
    return True

async def create_verification(user_id: int) -> str:
    """Create new verification for user"""
    verify_id = generate_verify_id()
    link_expiry_seconds = VERIFY_EXPIRE
    
    await db.update_user(user_id, {
        "verify_id": verify_id,
        "verify_created": datetime.now(),
        "verify_expires": datetime.now() + timedelta(seconds=link_expiry_seconds),
        "is_verified": False,
        "verified_at": None
    })
    
    logger.info(f"🔐 Created verification {verify_id} for user {user_id}")
    return verify_id

async def verify_user(user_id: int, verify_id: str) -> bool:
    """Verify user with ID"""
    user = await db.get_user(user_id)
    
    if not user:
        return False
    
    if user.get("verify_id") == verify_id:
        if datetime.now() < user.get("verify_expires", datetime.now()):
            await db.update_user(user_id, {
                "is_verified": True,
                "verified_at": datetime.now()
            })
            await db.update_user(user_id, {"verify_id": None, "verify_expires": None})
            logger.info(f"✅ User {user_id} verified successfully!")
            return True
    
    logger.warning(f"❌ Verification failed for user {user_id}")
    return False

async def reset_user_verification(user_id: int):
    """Reset user verification (admin use)"""
    await db.update_user(user_id, {
        "is_verified": False,
        "verify_id": None,
        "verify_expires": None,
        "verified_at": None
    })
    logger.info(f"🔄 Verification reset for user {user_id}")

# ============ SEND VERIFICATION ALERT ============

async def send_verification_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send verification alert to user"""
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name or "User"
    
    logger.info(f"🔐 Sending verification alert to user {user_id}")
    
    if not VERIFICATION_ENABLED:
        logger.info(f"ℹ️ Verification is OFF, allowing user {user_id}")
        return True
    
    # Check if already verified and within expiry
    user = await db.get_user(user_id)
    if user and user.get("is_verified"):
        verified_at = user.get("verified_at")
        if verified_at:
            expire_seconds = VERIFY_EXPIRE
            if datetime.now() - verified_at < timedelta(seconds=expire_seconds):
                logger.info(f"✅ User {user_id} already verified")
                return True
    
    verify_id = await create_verification(user_id)
    bot_username = (await context.bot.get_me()).username
    
    long_url = f"https://t.me/{bot_username}?start=verify_{user_id}_{verify_id}"
    verify_url = await get_shortlink(long_url)
    
    expire_minutes = VERIFY_EXPIRE // 60
    
    text = f"""🔐 <b>Verification Required!</b>

Hello {first_name},

⚠️ You need to verify before sending videos!

👇 Click the button below to verify:

💡 <b>Why verify?</b>
• 🛡️ Prevent spam
• 🎯 Better experience
• ⚡ Faster processing

⏳ <b>Verification valid for {expire_minutes} minutes</b>
After {expire_minutes} minutes, you'll need to verify again.

🔗 Link expires in {expire_minutes} minutes!"""

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Verify Now", url=verify_url)],
        [InlineKeyboardButton("❓ How to Verify?", url=TUTORIAL_LINK)],
        [InlineKeyboardButton("💎 Get Premium (No Verification)", callback_data="get_subscription")]
    ])
    
    try:
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
        logger.info(f"✅ Verification alert sent to user {user_id}")
    except Exception as e:
        logger.error(f"❌ Failed to send verification alert: {e}")
        await update.message.reply_text(
            text,
            reply_markup=buttons,
            parse_mode="HTML"
        )
    
    return False

async def send_verification_success(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send verification success message with expiry info"""
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name or "User"
    
    user = await db.get_user(user_id)
    verified_at = user.get("verified_at") if user else None
    
    expire_minutes = VERIFY_EXPIRE // 60
    expiry_time = f"{expire_minutes} minutes"
    
    if verified_at:
        expiry = verified_at + timedelta(seconds=VERIFY_EXPIRE)
        expiry_time = expiry.strftime("%I:%M %p, %d %b %Y")
    
    text = f"""✅ <b>Verification Successful!</b>

Welcome {first_name}! 🎉

You can now:
📸 Set your thumbnail
🎬 Apply covers to videos
📊 Use all bot features

⏳ <b>Verification valid until:</b>
{expiry_time}

After {expire_minutes} minutes, you'll need to verify again.

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
    
    global VERIFICATION_ENABLED
    VERIFICATION_ENABLED = not VERIFICATION_ENABLED
    
    status = "🟢 ON" if VERIFICATION_ENABLED else "🔴 OFF"
    expire_minutes = VERIFY_EXPIRE // 60
    
    text = f"""🎛️ <b>Verification Toggle</b>

📊 Status: {status}

Users will {'need to verify every ' + str(expire_minutes) + ' minutes' if VERIFICATION_ENABLED else 'not need to verify'} before sending videos."""
    
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
    
    global SHORTLINK_ENABLED
    SHORTLINK_ENABLED = not SHORTLINK_ENABLED
    
    status = "🟢 ON" if SHORTLINK_ENABLED else "🔴 OFF"
    
    text = f"""🔗 <b>Shortlink Toggle</b>

📊 Status: {status}

Verification links will {'use shortlink' if SHORTLINK_ENABLED else 'use direct link'}."""
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Toggle", callback_data="toggle_shortlink")],
        [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
    ])
    
    await update.message.reply_text(
        text,
        reply_markup=buttons,
        parse_mode="HTML"
    )

async def get_verified_users_count() -> int:
    """Get count of verified users"""
    try:
        from database import db
        users = await db.get_all_users()
        count = 0
        expire_seconds = VERIFY_EXPIRE
        for user in users:
            if user.get("is_verified", False):
                verified_at = user.get("verified_at")
                if verified_at:
                    if datetime.now() - verified_at < timedelta(seconds=expire_seconds):
                        count += 1
        return count
    except Exception as e:
        logger.error(f"Error counting verified users: {e}")
        return 0

# ============ CHECK VERIFICATION STATUS COMMAND ============

async def check_verification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check user's verification status"""
    user_id = update.effective_user.id
    
    user = await db.get_user(user_id)
    
    if not user:
        text = "❌ No user data found. Please /start the bot."
        await update.message.reply_text(text, parse_mode="HTML")
        return
    
    is_verified = user.get("is_verified", False)
    verified_at = user.get("verified_at")
    expire_minutes = VERIFY_EXPIRE // 60
    
    if is_verified and verified_at:
        if datetime.now() - verified_at < timedelta(seconds=VERIFY_EXPIRE):
            expiry = verified_at + timedelta(seconds=VERIFY_EXPIRE)
            text = f"""✅ <b>You are Verified!</b>

⏳ Valid until: {expiry.strftime('%I:%M %p, %d %b %Y')}
⏰ Valid for: {expire_minutes} minutes
🔄 Verification expires after {expire_minutes} minutes

You can send videos without any restrictions."""
        else:
            text = """⏰ <b>Verification Expired!</b>

Your verification period has ended.

Please verify again to continue using the bot."""
    else:
        text = """❌ <b>Not Verified!</b>

You need to verify before sending videos.

Send a video to start verification process."""
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Verify Now", callback_data="verify_now")],
        [InlineKeyboardButton("🏠 Home", callback_data="menu_back")]
    ])
    
    await update.message.reply_text(
        text,
        reply_markup=buttons,
        parse_mode="HTML"
    )
