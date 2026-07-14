# channel.py
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# Database functions for channel management
def get_user_channel(user_id: int) -> str:
    """Get user's saved channel ID"""
    # TODO: Implement database storage for channel IDs
    # For now using a simple in-memory dict (you should use MongoDB)
    if not hasattr(get_user_channel, 'channels'):
        get_user_channel.channels = {}
    return get_user_channel.channels.get(str(user_id), None)

def save_user_channel(user_id: int, channel_id: str) -> None:
    """Save user's channel ID"""
    if not hasattr(save_user_channel, 'channels'):
        save_user_channel.channels = {}
    save_user_channel.channels[str(user_id)] = channel_id

async def show_channel_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show channel settings menu"""
    query = update.callback_query
    user_id = query.from_user.id
    
    current_channel = get_user_channel(user_id)
    
    text = (
        "🔗 <b>Channel Settings</b>\n\n"
        "Set a channel where the bot will send processed videos.\n\n"
    )
    
    if current_channel:
        text += f"📌 <b>Current Channel:</b> <code>{current_channel}</code>\n\n"
    else:
        text += "❌ <b>No channel set yet</b>\n\n"
    
    text += (
        "<b>Options:</b>\n"
        "📝 <b>Set Channel</b> – Send new channel ID\n"
        "🗑️ <b>Remove Channel</b> – Clear current channel"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Set Channel", callback_data="channel_set")],
        [InlineKeyboardButton("🗑️ Remove Channel", callback_data="channel_remove")],
        [InlineKeyboardButton("⬅️ Back to Settings", callback_data="menu_settings")]
    ])
    
    try:
        msg = query.message
        if getattr(msg, "photo", None):
            await msg.edit_caption(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await msg.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await query.answer()
    except Exception as e:
        logger.error(f"Error showing channel settings: {e}")

async def channel_set_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt user to send channel ID"""
    query = update.callback_query
    user_id = query.from_user.id
    
    text = (
        "📝 <b>Set Channel</b>\n\n"
        "Please send me the Channel ID you want to set.\n\n"
        "<b>How to get Channel ID:</b>\n"
        "1️⃣ Forward any message from your channel to @getidsbot\n"
        "2️⃣ Copy the ID (starts with -100)\n\n"
        "Example: <code>-1001234567890</code>\n\n"
        "⚠️ Make sure the bot is an admin in that channel!"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back", callback_data="channel_settings")]
    ])
    
    # Store user state
    context.user_data['awaiting_channel_id'] = True
    
    try:
        msg = query.message
        if getattr(msg, "photo", None):
            await msg.edit_caption(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await msg.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await query.answer()
    except Exception as e:
        logger.error(f"Error in channel set prompt: {e}")

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
        save_user_channel(user_id, None)  # Clear channel
        text = (
            "🗑️ <b>Channel Removed</b>\n\n"
            f"Removed: <code>{current_channel}</code>\n\n"
            "You can set a new channel anytime."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Set New Channel", callback_data="channel_set")],
            [InlineKeyboardButton("⬅️ Back to Settings", callback_data="channel_settings")]
        ])
    
    try:
        msg = query.message
        if getattr(msg, "photo", None):
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
    
    # Check if user is in channel set mode
    if not context.user_data.get('awaiting_channel_id', False):
        return False
    
    # Validate channel ID format
    if not channel_id.startswith('-100'):
        await update.message.reply_text(
            "❌ <b>Invalid Channel ID</b>\n\n"
            "Channel ID must start with <code>-100</code>\n\n"
            "To get your channel ID:\n"
            "1️⃣ Forward any message from your channel to @getidsbot\n"
            "2️⃣ Copy the ID starting with -100\n\n"
            "Try again or click /cancel to exit.",
            parse_mode="HTML"
        )
        return True
    
    try:
        # Try to verify if bot can access the channel
        from telegram.error import BadRequest
        try:
            chat = await context.bot.get_chat(chat_id=channel_id)
            channel_name = chat.title or "Unknown Channel"
            
            # Save channel
            save_user_channel(user_id, channel_id)
            context.user_data['awaiting_channel_id'] = False
            
            text = (
                "✅ <b>Channel Set Successfully!</b>\n\n"
                f"📌 <b>Channel ID:</b> <code>{channel_id}</code>\n"
                f"📢 <b>Channel Name:</b> {channel_name}\n\n"
                "✅ Bot will send processed videos to this channel."
            )
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Back to Settings", callback_data="menu_settings")],
                [InlineKeyboardButton("🔗 Channel Settings", callback_data="channel_settings")]
            ])
            
            await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
            return True
            
        except BadRequest as e:
            if "user not found" in str(e).lower():
                await update.message.reply_text(
                    "❌ <b>Channel Not Found</b>\n\n"
                    "Make sure:\n"
                    "• The channel ID is correct\n"
                    "• The bot is an admin in the channel\n"
                    "• The channel exists\n\n"
                    "Try again or click /cancel to exit.",
                    parse_mode="HTML"
                )
            else:
                await update.message.reply_text(
                    f"❌ <b>Error</b>\n\n"
                    f"Could not verify channel: {str(e)[:100]}\n\n"
                    "Make sure the bot is an admin in the channel.",
                    parse_mode="HTML"
                )
            return True
            
    except Exception as e:
        logger.error(f"Error verifying channel: {e}")
        await update.message.reply_text(
            f"❌ <b>Error</b>\n\n"
            f"Could not verify channel. Error: {str(e)[:100]}\n\n"
            "Please try again.",
            parse_mode="HTML"
        )
        return True