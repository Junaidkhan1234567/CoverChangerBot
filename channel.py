# channel.py - Complete with RED buttons

import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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
    """Show channel settings with COLORED buttons"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if query:
        await query.answer()
    
    current_channel = get_user_channel(user_id)
    forward_enabled = get_forward_enabled(user_id)
    
    text = "🔗 <b>Channel Settings</b>\n\n"
    
    if current_channel:
        text += f"📌 <b>Current Channel:</b> <code>{current_channel}</code>\n"
        forward_status = "✅ Enabled" if forward_enabled else "❌ Disabled"
        text += f"📤 <b>Forward to Channel:</b> {forward_status}\n\n"
        text += "To change channel, send new Channel ID.\n\n"
    else:
        text += "❌ <b>No channel set yet</b>\n\n"
    
    text += "📝 <b>Send me your Channel ID to set it.</b>\n"
    text += "Example: <code>-1001234567890</code>\n\n"
    text += "ℹ️ To get your channel ID:\n"
    text += "1️⃣ Forward any message from your channel to @getidsbot\n"
    text += "2️⃣ Copy the ID starting with -100\n\n"
    text += "⚠️ Make sure bot is admin in your channel!"
    
    # ✅ COLORED BUTTONS
    toggle_text = "📤 Forward OFF" if forward_enabled else "📤 Forward ON"
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                toggle_text,
                callback_data="channel_toggle_forward",
                style="success" if forward_enabled else "danger"  # GREEN if ON, RED if OFF
            ),
            InlineKeyboardButton(
                "🗑️ Remove Channel",
                callback_data="channel_remove",
                style="danger"  # 🔴 RED
            ),
        ],
        [
            InlineKeyboardButton(
                "⬅️ Back to Settings",
                callback_data="menu_settings",
                style="primary"  # 🔵 BLUE
            ),
        ]
    ])
    
    context.user_data['awaiting_channel_id'] = True
    
    try:
        if query and query.message:
            context.user_data['channel_settings_message_id'] = query.message.message_id
            context.user_data['channel_settings_chat_id'] = query.message.chat_id
            
            await query.message.edit_text(
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        else:
            msg = await context.bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            context.user_data['channel_settings_message_id'] = msg.message_id
            context.user_data['channel_settings_chat_id'] = msg.chat_id
    except Exception as e:
        logger.error(f"Error in channel set prompt: {e}")

async def channel_toggle_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle forward enabled/disabled - WITH COLOR"""
    query = update.callback_query
    user_id = query.from_user.id
    
    await query.answer()
    
    current_forward_status = get_forward_enabled(user_id)
    new_status = not current_forward_status
    
    save_forward_enabled(user_id, new_status)
    
    logger.info(f"✅ Forward toggled for user {user_id}: {'ON' if new_status else 'OFF'}")
    
    current_channel = get_user_channel(user_id)
    
    text = "🔗 <b>Channel Settings</b>\n\n"
    
    if current_channel:
        text += f"📌 <b>Current Channel:</b> <code>{current_channel}</code>\n"
        forward_status = "✅ Enabled" if new_status else "❌ Disabled"
        text += f"📤 <b>Forward to Channel:</b> {forward_status}\n\n"
        text += "To change channel, send new Channel ID.\n\n"
    else:
        text += "❌ <b>No channel set yet</b>\n\n"
    
    text += "📝 <b>Send me your Channel ID to set it.</b>\n"
    text += "Example: <code>-1001234567890</code>\n\n"
    text += "ℹ️ To get your channel ID:\n"
    text += "1️⃣ Forward any message from your channel to @getidsbot\n"
    text += "2️⃣ Copy the ID starting with -100\n\n"
    text += "⚠️ Make sure bot is admin in your channel!"
    
    toggle_text = "📤 Forward OFF" if new_status else "📤 Forward ON"
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                toggle_text,
                callback_data="channel_toggle_forward",
                style="success" if new_status else "danger"  # GREEN if ON, RED if OFF
            ),
            InlineKeyboardButton(
                "🗑️ Remove Channel",
                callback_data="channel_remove",
                style="danger"  # 🔴 RED
            ),
        ],
        [
            InlineKeyboardButton(
                "⬅️ Back to Settings",
                callback_data="menu_settings",
                style="primary"  # 🔵 BLUE
            ),
        ]
    ])
    
    try:
        await query.message.edit_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        context.user_data['channel_settings_message_id'] = query.message.message_id
        context.user_data['channel_settings_chat_id'] = query.message.chat_id
    except Exception as e:
        logger.error(f"Error toggling forward: {e}")

async def channel_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove saved channel - WITH RED BUTTONS"""
    query = update.callback_query
    user_id = query.from_user.id
    
    await query.answer()
    
    current_channel = get_user_channel(user_id)
    
    try:
        await query.message.delete()
    except Exception:
        pass
    
    context.user_data['awaiting_channel_id'] = True
    
    if not current_channel:
        text = "❌ <b>No channel is currently set.</b>"
        
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🏠 Back to Home",
                    callback_data="channel_back_home",
                    style="danger"  # 🔴 RED
                ),
            ]
        ])
        
        msg = await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        context.user_data['channel_settings_message_id'] = msg.message_id
        context.user_data['channel_settings_chat_id'] = msg.chat_id
    else:
        save_user_channel(user_id, None)
        save_forward_enabled(user_id, True)
        
        text = "✅ <b>Channel removed successfully!</b>\n\n"
        text += "📝 Send me a new Channel ID to set it.\n"
        text += "Example: <code>-1001234567890</code>\n\n"
        text += "ℹ️ To get your channel ID:\n"
        text += "1️⃣ Forward any message from your channel to @getidsbot\n"
        text += "2️⃣ Copy the ID starting with -100\n\n"
        text += "⚠️ Make sure bot is admin in your channel!"
        
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⬅️ Back to Settings",
                    callback_data="menu_settings",
                    style="danger"  # 🔴 RED
                ),
            ]
        ])
        
        msg = await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        context.user_data['channel_settings_message_id'] = msg.message_id
        context.user_data['channel_settings_chat_id'] = msg.chat_id

async def channel_back_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Go back to Home Menu with banner"""
    query = update.callback_query
    user_id = query.from_user.id
    
    try:
        await query.message.delete()
    except Exception:
        pass
    
    await query.answer()
    
    from bot import send_home_menu
    await send_home_menu(context, user_id, user_id)

async def handle_channel_id_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle channel ID input from user"""
    user_id = update.message.from_user.id
    channel_id = update.message.text.strip()
    
    if not context.user_data.get('awaiting_channel_id', False):
        return False
    
    try:
        old_msg_id = context.user_data.get('channel_settings_message_id')
        old_chat_id = context.user_data.get('channel_settings_chat_id')
        
        if old_msg_id and old_chat_id:
            await context.bot.delete_message(
                chat_id=old_chat_id,
                message_id=old_msg_id
            )
            logger.info(f"✅ Old channel settings message deleted: {old_msg_id}")
    except Exception as e:
        logger.warning(f"Could not delete old message: {e}")
    
    try:
        await update.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete user message: {e}")
    
    context.user_data['awaiting_channel_id'] = False
    context.user_data['channel_settings_message_id'] = None
    context.user_data['channel_settings_chat_id'] = None
    
    if not channel_id.startswith('-100'):
        text = (
            "❌ <b>Invalid Channel ID</b>\n\n"
            "Channel ID must start with <code>-100</code>\n\n"
            "To get your channel ID:\n"
            "1️⃣ Forward any message from your channel to @getidsbot\n"
            "2️⃣ Copy the ID starting with -100\n\n"
            "Try again or send correct Channel ID."
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⬅️ Back to Settings",
                    callback_data="menu_settings",
                    style="primary"  # 🔵 BLUE
                ),
            ]
        ])
        
        msg = await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        context.user_data['channel_settings_message_id'] = msg.message_id
        context.user_data['channel_settings_chat_id'] = msg.chat_id
        context.user_data['awaiting_channel_id'] = True
        return True
    
    try:
        try:
            chat = await context.bot.get_chat(chat_id=channel_id)
            channel_name = chat.title or "Unknown Channel"
            
            save_user_channel(user_id, channel_id)
            save_forward_enabled(user_id, True)
            
            text = (
                "✅ <b>Channel Set Successfully!</b>\n\n"
                f"📌 <b>Channel ID:</b> <code>{channel_id}</code>\n"
                f"📢 <b>Channel Name:</b> {channel_name}\n\n"
                "✅ Bot will send processed videos to this channel.\n"
                "ℹ️ You can manage from Settings menu."
            )
            
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "📤 Forward OFF",
                        callback_data="channel_toggle_forward",
                        style="danger"  # 🔴 RED (Initially OFF)
                    ),
                    InlineKeyboardButton(
                        "🗑️ Remove Channel",
                        callback_data="channel_remove",
                        style="danger"  # 🔴 RED
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ Back to Settings",
                        callback_data="menu_settings",
                        style="primary"  # 🔵 BLUE
                    ),
                ]
            ])
            
            msg = await context.bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            context.user_data['channel_settings_message_id'] = msg.message_id
            context.user_data['channel_settings_chat_id'] = msg.chat_id
            
            logger.info(f"✅ Channel saved for user {user_id}: {channel_id}")
            
            return True
            
        except BadRequest as e:
            if "user not found" in str(e).lower():
                text = (
                    "❌ <b>Channel Not Found</b>\n\n"
                    "Make sure:\n"
                    "• The channel ID is correct\n"
                    "• The bot is an admin in the channel\n"
                    "• The channel exists\n\n"
                    "Try again or send correct Channel ID."
                )
            else:
                text = (
                    f"❌ <b>Error</b>\n\n"
                    f"Could not verify channel: {str(e)[:100]}\n\n"
                    "Make sure the bot is an admin in the channel.\n"
                    "Try again or send correct Channel ID."
                )
            
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Back to Settings",
                        callback_data="menu_settings",
                        style="primary"  # 🔵 BLUE
                    ),
                ]
            ])
            
            msg = await context.bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            context.user_data['channel_settings_message_id'] = msg.message_id
            context.user_data['channel_settings_chat_id'] = msg.chat_id
            context.user_data['awaiting_channel_id'] = True
            return True
            
    except Exception as e:
        logger.error(f"Error verifying channel: {e}")
        text = (
            f"❌ <b>Error</b>\n\n"
            f"Could not verify channel. Error: {str(e)[:100]}\n\n"
            "Please try again or send correct Channel ID."
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⬅️ Back to Settings",
                    callback_data="menu_settings",
                    style="primary"  # 🔵 BLUE
                ),
            ]
        ])
        
        msg = await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        context.user_data['channel_settings_message_id'] = msg.message_id
        context.user_data['channel_settings_chat_id'] = msg.chat_id
        context.user_data['awaiting_channel_id'] = True
        return True

async def cancel_channel_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel channel setup process"""
    user_id = update.message.from_user.id
    
    if context.user_data.get('awaiting_channel_id', False):
        context.user_data['awaiting_channel_id'] = False
        context.user_data['channel_settings_message_id'] = None
        context.user_data['channel_settings_chat_id'] = None
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
    app.add_handler(CallbackQueryHandler(show_channel_settings, pattern="^channel_settings$"))
    app.add_handler(CallbackQueryHandler(channel_set_prompt, pattern="^channel_set$"))
    app.add_handler(CallbackQueryHandler(channel_toggle_forward, pattern="^channel_toggle_forward$"))
    app.add_handler(CallbackQueryHandler(channel_remove, pattern="^channel_remove$"))
    app.add_handler(CallbackQueryHandler(channel_back_home, pattern="^channel_back_home$"))
    
    app.add_handler(CommandHandler("cancel", cancel_channel_setup))
    
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, 
        handle_channel_id_input
    ), group=10)
    
    logger.info("✅ Channel handlers registered successfully")
    return app
