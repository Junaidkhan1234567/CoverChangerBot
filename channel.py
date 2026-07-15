# channel.py
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from telegram.error import BadRequest
from database import db

logger = logging.getLogger(__name__)

# ═══════════════════ DATABASE FUNCTIONS ═══════════════════
def get_user_channel(user_id: int) -> str:
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
    try:
        users_collection = db.get_collection("users")
        user_data = users_collection.find_one({"user_id": user_id})
        if user_data and "forward_enabled" in user_data:
            return user_data["forward_enabled"]
        return True
    except Exception as e:
        logger.error(f"Error getting forward enabled status: {e}")
        return True

def should_forward_to_channel(user_id: int) -> bool:
    return get_forward_enabled(user_id)

def save_user_channel(user_id: int, channel_id: str) -> None:
    try:
        users_collection = db.get_collection("users")
        if channel_id is None:
            users_collection.update_one(
                {"user_id": user_id},
                {"$unset": {"channel_id": ""}},
                upsert=True
            )
        else:
            users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"channel_id": channel_id}},
                upsert=True
            )
        logger.info(f"✅ Channel saved for user {user_id}: {channel_id}")
    except Exception as e:
        logger.error(f"Error saving channel: {e}")

def save_forward_enabled(user_id: int, enabled: bool) -> None:
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

# ═══════════════════ CALLBACK FUNCTIONS ═══════════════════

async def show_channel_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await channel_set_prompt(update, context)

async def channel_set_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show message with reply keyboard buttons"""
    query = update.callback_query
    user_id = query.from_user.id
    
    # ✅ PEHLE OLD MESSAGE DELETE KARO
    try:
        await query.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete old message: {e}")
    
    current_channel = get_user_channel(user_id)
    forward_enabled = get_forward_enabled(user_id)
    
    # ✅ TEXT MESSAGE
    text = "👇 <b>Click below button to manage your channel</b>"
    
    # ✅ REPLY KEYBOARD BUTTONS (NORMAL KEYBOARD)
    reply_keyboard = ReplyKeyboardMarkup(
        [
            ["📤 Toggle Forward", "🗑️ Remove Channel"],
            ["⬅️ Back to Settings"]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    
    context.user_data['awaiting_channel_id'] = True
    context.user_data['channel_settings_active'] = True
    
    try:
        # ✅ NAYA MESSAGE BHEJO SIRF TEXT KE SATH + REPLY KEYBOARD
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=reply_keyboard,
            parse_mode="HTML"
        )
        await query.answer()
        logger.info(f"✅ Channel settings message sent to user {user_id}")
    except Exception as e:
        logger.error(f"Error in channel set prompt: {e}")

async def channel_toggle_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle forward enabled/disabled"""
    user_id = update.message.from_user.id
    
    # ✅ CHECK KARO KE YEH CHANNEL SETTINGS SE AYA HAI
    if not context.user_data.get('channel_settings_active', False):
        return
    
    current_forward_status = get_forward_enabled(user_id)
    new_status = not current_forward_status
    
    save_forward_enabled(user_id, new_status)
    
    channel_id = get_user_channel(user_id)
    
    # ✅ TEXT MESSAGE
    if new_status:
        text = (
            "✅ <b>Forwarding Enabled</b>\n\n"
            f"📌 <b>Channel:</b> <code>{channel_id}</code>\n\n"
            "Bot will now forward processed videos to your channel.\n\n"
            "👇 <b>Click below to manage your channel</b>"
        )
    else:
        text = (
            "❌ <b>Forwarding Disabled</b>\n\n"
            f"📌 <b>Channel:</b> <code>{channel_id}</code>\n\n"
            "Bot will <b>NOT</b> forward videos to your channel.\n"
            "Videos will only be sent in the bot chat.\n\n"
            "👇 <b>Click below to manage your channel</b>"
        )
    
    # ✅ REPLY KEYBOARD
    reply_keyboard = ReplyKeyboardMarkup(
        [
            ["📤 Toggle Forward", "🗑️ Remove Channel"],
            ["⬅️ Back to Settings"]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    
    try:
        await update.message.reply_text(
            text=text,
            reply_markup=reply_keyboard,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error toggling forward: {e}")

async def channel_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove saved channel"""
    user_id = update.message.from_user.id
    
    # ✅ CHECK KARO KE YEH CHANNEL SETTINGS SE AYA HAI
    if not context.user_data.get('channel_settings_active', False):
        return
    
    current_channel = get_user_channel(user_id)
    
    if not current_channel:
        text = "❌ No channel is currently set.\n\nSend me your Channel ID to set it.\nExample: <code>-1001234567890</code>"
        reply_keyboard = ReplyKeyboardMarkup(
            [
                ["⬅️ Back to Settings"]
            ],
            resize_keyboard=True,
            one_time_keyboard=False
        )
        context.user_data['awaiting_channel_id'] = True
    else:
        save_user_channel(user_id, None)
        save_forward_enabled(user_id, True)
        context.user_data['awaiting_channel_id'] = True
        
        text = "✅ Channel removed successfully!\n\n👇 <b>Click below to manage your channel</b>"
        
        reply_keyboard = ReplyKeyboardMarkup(
            [
                ["📤 Toggle Forward", "🗑️ Remove Channel"],
                ["⬅️ Back to Settings"]
            ],
            resize_keyboard=True,
            one_time_keyboard=False
        )
    
    try:
        await update.message.reply_text(
            text=text,
            reply_markup=reply_keyboard,
            parse_mode="HTML"
        )
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
            "Try again or click 'Back to Settings'.",
            parse_mode="HTML"
        )
        return True
    
    try:
        try:
            chat = await context.bot.get_chat(chat_id=channel_id)
            channel_name = chat.title or "Unknown Channel"
            
            save_user_channel(user_id, channel_id)
            save_forward_enabled(user_id, True)
            
            context.user_data['awaiting_channel_id'] = False
            
            text = (
                "✅ <b>Channel Set Successfully!</b>\n\n"
                f"📌 <b>Channel ID:</b> <code>{channel_id}</code>\n"
                f"📢 <b>Channel Name:</b> {channel_name}\n\n"
                "✅ Bot will send processed videos to this channel.\n"
                "ℹ️ You can disable forwarding from Channel Settings.\n\n"
                "👇 <b>Click below to manage your channel</b>"
            )
            
            reply_keyboard = ReplyKeyboardMarkup(
                [
                    ["📤 Toggle Forward", "🗑️ Remove Channel"],
                    ["⬅️ Back to Settings"]
                ],
                resize_keyboard=True,
                one_time_keyboard=False
            )
            
            await update.message.reply_text(
                text=text,
                reply_markup=reply_keyboard,
                parse_mode="HTML"
            )
            
            logger.info(f"✅ Channel saved for user {user_id}: {channel_id}")
            
            return True
            
        except BadRequest as e:
            if "user not found" in str(e).lower():
                await update.message.reply_text(
                    "❌ <b>Channel Not Found</b>\n\n"
                    "Make sure:\n"
                    "• The channel ID is correct\n"
                    "• The bot is an admin in the channel\n"
                    "• The channel exists\n\n"
                    "Try again or click 'Back to Settings'.",
                    parse_mode="HTML"
                )
            else:
                await update.message.reply_text(
                    f"❌ <b>Error</b>\n\n"
                    f"Could not verify channel: {str(e)[:100]}\n\n"
                    "Make sure the bot is an admin in the channel.\n"
                    "Try again or click 'Back to Settings'.",
                    parse_mode="HTML"
                )
            return True
            
    except Exception as e:
        logger.error(f"Error verifying channel: {e}")
        await update.message.reply_text(
            f"❌ <b>Error</b>\n\n"
            f"Could not verify channel. Error: {str(e)[:100]}\n\n"
            "Please try again or click 'Back to Settings'.",
            parse_mode="HTML"
        )
        return True

async def cancel_channel_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel channel setup process"""
    user_id = update.message.from_user.id
    
    if context.user_data.get('awaiting_channel_id', False):
        context.user_data['awaiting_channel_id'] = False
        context.user_data['channel_settings_active'] = False
        
        # ✅ REMOVE KEYBOARD
        reply_keyboard = ReplyKeyboardMarkup(
            [[]],
            resize_keyboard=True
        )
        
        await update.message.reply_text(
            "❌ <b>Channel Setup Cancelled</b>\n\n"
            "You can start again anytime from Settings.",
            reply_markup=reply_keyboard,
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
    app.add_handler(CallbackQueryHandler(show_channel_settings, pattern="^channel_settings$"))
    app.add_handler(CallbackQueryHandler(channel_set_prompt, pattern="^channel_set$"))
    
    # ✅ TEXT HANDLERS FOR REPLY KEYBOARD BUTTONS
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex('^📤 Toggle Forward$'),
        channel_toggle_forward
    ))
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex('^🗑️ Remove Channel$'),
        channel_remove
    ))
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex('^⬅️ Back to Settings$'),
        channel_set_prompt
    ))
    
    app.add_handler(CommandHandler("cancel", cancel_channel_setup))
    
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, 
        handle_channel_id_input
    ), group=10)
    
    logger.info("✅ Channel handlers registered successfully")
    return app
