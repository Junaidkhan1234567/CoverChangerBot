# channel.py
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from telegram.error import BadRequest
from database import db

logger = logging.getLogger(__name__)

# ═══════════════════ DATABASE FUNCTIONS ═══════════════════
def get_user_channel(user_id: int) -> str:
    """Get user's saved channel ID from database"""
    try:
        users_collection = db.get_collection("users")
        user_data = users_collection.find_one({"user_id": user_id})
        if user_data and "channel_id" in user_data:
            return user_data["channel_id"]
        return None
    except Exception as e:
        logger.error(f"Error getting channel: {e}")
        return None

def get_forward_enabled(user_id: int) -> bool:
    """Get user's forward enabled status"""
    try:
        users_collection = db.get_collection("users")
        user_data = users_collection.find_one({"user_id": user_id})
        if user_data and "forward_enabled" in user_data:
            return user_data["forward_enabled"]
        return True  # Default: forward enabled
    except Exception as e:
        logger.error(f"Error getting forward enabled status: {e}")
        return True

def should_forward_to_channel(user_id: int) -> bool:
    """Alias for get_forward_enabled - checks if forwarding is enabled"""
    return get_forward_enabled(user_id)

def save_user_channel(user_id: int, channel_id: str) -> None:
    """Save user's channel ID to database"""
    try:
        users_collection = db.get_collection("users")
        if channel_id is None:
            # Remove channel_id from user document
            users_collection.update_one(
                {"user_id": user_id},
                {"$unset": {"channel_id": ""}},
                upsert=True
            )
        else:
            # Save channel_id
            users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"channel_id": channel_id}},
                upsert=True
            )
        logger.info(f"✅ Channel saved for user {user_id}: {channel_id}")
    except Exception as e:
        logger.error(f"Error saving channel: {e}")

def save_forward_enabled(user_id: int, enabled: bool) -> None:
    """Save user's forward enabled status to database"""
    try:
        users_collection = db.get_collection("users")
        users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"forward_enabled": enabled}},
            upsert=True
        )
        logger.info(f"✅ Forward enabled status saved for user {user_id}: {enabled}")
    except Exception as e:
        logger.error(f"Error saving forward enabled status: {e}")

# ═══════════════════ SEND TO CHANNEL HELPER ═══════════════════
async def send_to_channel_if_enabled(context, user_id: int, video_file, caption: str = "", **kwargs):
    """
    Send video to user's channel only if forwarding is enabled.
    Returns: (sent: bool, channel_id: str or None)
    """
    channel_id = get_user_channel(user_id)
    forward_enabled = should_forward_to_channel(user_id)
    
    if not channel_id:
        logger.info(f"ℹ️ No channel set for user {user_id}")
        return False, None
    
    if not forward_enabled:
        logger.info(f"ℹ️ Forwarding disabled for user {user_id}, not sending to channel")
        return False, channel_id
    
    try:
        await context.bot.send_video(
            chat_id=channel_id,
            video=video_file,
            caption=caption,
            **kwargs
        )
        logger.info(f"✅ Video forwarded to channel {channel_id} for user {user_id}")
        return True, channel_id
    except Exception as e:
        logger.error(f"❌ Failed to forward to channel {channel_id}: {e}")
        return False, channel_id

# ═══════════════════ CALLBACK FUNCTIONS ═══════════════════
async def show_channel_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show channel settings menu"""
    query = update.callback_query
    user_id = query.from_user.id
    
    current_channel = get_user_channel(user_id)
    forward_enabled = get_forward_enabled(user_id)
    
    text = "🔗 <b>Channel Settings</b>\n\n"
    text += "Set a channel where the bot will send processed videos.\n\n"
    
    if current_channel:
        text += f"📌 <b>Current Channel:</b> <code>{current_channel}</code>\n"
        forward_status = "✅ Enabled" if forward_enabled else "❌ Disabled"
        text += f"📤 <b>Forward to Channel:</b> {forward_status}\n\n"
    else:
        text += "❌ <b>No channel set yet</b>\n\n"
    
    text += (
        "<b>Options:</b>\n"
        "📝 <b>Set Channel</b> – Send new channel ID\n"
        "🗑️ <b>Remove Channel</b> – Clear current channel\n"
        "📤 <b>Toggle Forward</b> – Enable/disable forwarding"
    )
    
    # Dynamic buttons based on channel status
    keyboard = [
        [InlineKeyboardButton("📝 Set Channel", callback_data="channel_set")],
    ]
    
    if current_channel:
        # Add toggle forward button
        toggle_text = "📤 Forward OFF" if forward_enabled else "📤 Forward ON"
        keyboard.append([
            InlineKeyboardButton(toggle_text, callback_data="channel_toggle_forward"),
            InlineKeyboardButton("🗑️ Remove", callback_data="channel_remove")
        ]) 
    else:
        keyboard.append([InlineKeyboardButton("🗑️ Remove Channel", callback_data="channel_remove")])
    
    keyboard.append([InlineKeyboardButton("⬅️ Back to Settings", callback_data="menu_settings")])
    
    keyboard_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        msg = query.message
        if hasattr(msg, "photo") and msg.photo:
            await msg.edit_caption(text, reply_markup=keyboard_markup, parse_mode="HTML")
        else:
            await msg.edit_text(text, reply_markup=keyboard_markup, parse_mode="HTML")
        await query.answer()
    except Exception as e:
        logger.error(f"Error showing channel settings: {e}")

async def channel_set_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt user to send channel ID"""
    query = update.callback_query
    
    text = (
        "📝 <b>Set Channel</b>\n\n"
        "Please send me the Channel ID you want to set.\n\n"
        "<b>How to get Channel ID:</b>\n"
        "1️⃣ Forward any message from your channel to @getidsbot\n"
        "2️⃣ Copy the ID (starts with -100)\n\n"
        "Example: <code>-1001234567368</code>\n\n"
        "⚠️ Make sure the bot is an admin in that channel!\n\n"
        "To cancel, send /cancel"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back", callback_data="channel_settings")]
    ])
    
    context.user_data['awaiting_channel_id'] = True
    
    try:
        msg = query.message
        if hasattr(msg, "photo") and msg.photo:
            await msg.edit_caption(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await msg.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await query.answer()
    except Exception as e:
        logger.error(f"Error in channel set prompt: {e}")

async def channel_toggle_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle forward enabled/disabled"""
    query = update.callback_query
    user_id = query.from_user.id
    
    current_forward_status = get_forward_enabled(user_id)
    new_status = not current_forward_status
    
    # Save new status to database
    save_forward_enabled(user_id, new_status)
    
    channel_id = get_user_channel(user_id)
    
    if new_status:
        text = (
            "✅ <b>Forwarding Enabled</b>\n\n"
            f"📌 <b>Channel:</b> <code>{channel_id}</code>\n\n"
            "Bot will now forward processed videos to your channel."
        )
    else:
        text = (
            "❌ <b>Forwarding Disabled</b>\n\n"
            f"📌 <b>Channel:</b> <code>{channel_id}</code>\n\n"
            "Bot will <b>NOT</b> forward videos to your channel.\n"
            "Videos will only be sent in the bot chat."
        )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back to Channel Settings", callback_data="channel_settings")],
        [InlineKeyboardButton("⚙️ Main Menu", callback_data="menu_settings")]
    ])
    
    try:
        msg = query.message
        if hasattr(msg, "photo") and msg.photo:
            await msg.edit_caption(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await msg.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await query.answer()
    except Exception as e:
        logger.error(f"Error toggling forward: {e}")

async def channel_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove saved channel"""
    query = update.callback_query
    user_id = query.from_user.id
    
    current_channel = get_user_channel(user_id)
    
    if not current_channel:
        text = "❌ No channel is currently set.\n\nYou can set one by clicking 'Set Channel'."
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Set Channel", callback_data="channel_set")],
            [InlineKeyboardButton("⬅️ Back", callback_data="channel_settings")]
        ])
    else:
        save_user_channel(user_id, None)  # Remove from database
        # Also reset forward enabled to default
        save_forward_enabled(user_id, True)
        text = (
            "🗑️ <b>Channel Removed</b>\n\n"
            f"Removed: <code>{current_channel}</code>\n\n"
            "You can set a new channel anytime.\n"
            "Forwarding has been reset to enabled by default."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Set New Channel", callback_data="channel_set")],
            [InlineKeyboardButton("⬅️ Back to Settings", callback_data="channel_settings")]
        ])
    
    try:
        msg = query.message
        if hasattr(msg, "photo") and msg.photo:
            await msg.edit_caption(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await msg.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await query.answer()
    except Exception as e:
        logger.error(f"Error removing channel: {e}")

async def handle_channel_id_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle channel ID input from user"""
    user_id = update.message.from_user.id
    channel_id = update.message.text.strip()
    
    if not context.user_data.get('awaiting_channel_id', False):
        return False
    
    if not channel_id.startswith('-100'):
        await update.message.reply_text(
            "❌ <b>Invalid Channel ID</b>\n\n"
            "Channel ID must start with <code>-100</code>\n\n"
            "To get your channel ID:\n"
            "1️⃣ Forward any message from your channel to @getidsbot\n"
            "2️⃣ Copy the ID starting with -100\n\n"
            "Try again or send /cancel to exit.",
            parse_mode="HTML"
        )
        return True
    
    try:
        try:
            chat = await context.bot.get_chat(chat_id=channel_id)
            channel_name = chat.title or "Unknown Channel"
            
            # ═══════ SAVE TO DATABASE ═══════
            save_user_channel(user_id, channel_id)
            # By default, forward is enabled when setting new channel
            save_forward_enabled(user_id, True)
            # ═══════════════════════════════
            
            context.user_data['awaiting_channel_id'] = False
            
            text = (
                "✅ <b>Channel Set Successfully!</b>\n\n"
                f"📌 <b>Channel ID:</b> <code>{channel_id}</code>\n"
                f"📢 <b>Channel Name:</b> {channel_name}\n\n"
                "✅ Bot will send processed videos to this channel.\n"
                "ℹ️ You can disable forwarding from Channel Settings."
            )
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Back to Settings", callback_data="menu_settings")],
                [InlineKeyboardButton("🔗 Channel Settings", callback_data="channel_settings")]
            ])
            
            await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
            
            # ═══════ DEBUG LOG ═══════
            logger.info(f"✅ Channel saved for user {user_id}: {channel_id}")
            # ════════════════════════
            
            return True
            
        except BadRequest as e:
            if "user not found" in str(e).lower():
                await update.message.reply_text(
                    "❌ <b>Channel Not Found</b>\n\n"
                    "Make sure:\n"
                    "• The channel ID is correct\n"
                    "• The bot is an admin in the channel\n"
                    "• The channel exists\n\n"
                    "Try again or send /cancel to exit.",
                    parse_mode="HTML"
                )
            else:
                await update.message.reply_text(
                    f"❌ <b>Error</b>\n\n"
                    f"Could not verify channel: {str(e)[:100]}\n\n"
                    "Make sure the bot is an admin in the channel.\n"
                    "Try again or send /cancel to exit.",
                    parse_mode="HTML"
                )
            return True
            
    except Exception as e:
        logger.error(f"Error verifying channel: {e}")
        await update.message.reply_text(
            f"❌ <b>Error</b>\n\n"
            f"Could not verify channel. Error: {str(e)[:100]}\n\n"
            "Please try again or send /cancel to exit.",
            parse_mode="HTML"
        )
        return True

async def cancel_channel_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel channel setup process"""
    user_id = update.message.from_user.id
    
    if context.user_data.get('awaiting_channel_id', False):
        context.user_data['awaiting_channel_id'] = False
        await update.message.reply_text(
            "❌ <b>Channel Setup Cancelled</b>\n\n"
            "You can start again anytime from Settings.",
            parse_mode="HTML"
        )
        logger.info(f"User {user_id} cancelled channel setup")
    else:
        await update.message.reply_text(
            "ℹ️ No ongoing channel setup to cancel.",
            parse_mode="HTML"
        )

# ═══════════════════ REGISTER HANDLERS ═══════════════════
def register_channel_handlers(app):
    """Register all channel-related handlers with the bot application"""
    
    app.add_handler(CallbackQueryHandler(show_channel_settings, pattern="^channel_settings$"))
    app.add_handler(CallbackQueryHandler(channel_set_prompt, pattern="^channel_set$"))
    app.add_handler(CallbackQueryHandler(channel_toggle_forward, pattern="^channel_toggle_forward$"))
    app.add_handler(CallbackQueryHandler(channel_remove, pattern="^channel_remove$"))
    
    app.add_handler(CommandHandler("cancel", cancel_channel_setup))
    
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, 
        handle_channel_id_input
    ), group=10)
    
    logger.info("✅ Channel handlers registered successfully")
    return app


async def show_channel_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show channel settings menu"""
    query = update.callback_query
    user_id = query.from_user.id
    
    current_channel = get_user_channel(user_id)
    forward_enabled = get_forward_enabled(user_id)
    
    text = "🔗 <b>Channel Settings</b>\n\n"
    text += "Set a channel where the bot will send processed videos.\n\n"
    
    if current_channel:
        text += f"📌 <b>Current Channel:</b> <code>{current_channel}</code>\n"
        forward_status = "✅ Enabled" if forward_enabled else "❌ Disabled"
        text += f"📤 <b>Forward to Channel:</b> {forward_status}\n\n"
    else:
        text += "❌ <b>No channel set yet</b>\n\n"
    
    text += (
        "<b>Options:</b>\n"
        "📝 <b>Set Channel</b> – Send new channel ID\n"
        "📤 <b>Toggle Forward</b> – Enable/disable forwarding\n"
        "🗑️ <b>Remove Channel</b> – Clear current channel"
    )
    
