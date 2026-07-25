# watermark.py
import os
import logging
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, filters, CommandHandler
from database import db

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════
# DATABASE FUNCTIONS FOR WATERMARK
# ═══════════════════════════════════════════════════════

def get_watermark_settings(user_id: int) -> dict:
    """Get watermark settings for user"""
    try:
        users_collection = db.get_collection("users")
        user_data = users_collection.find_one({"user_id": user_id})
        if user_data and "watermark" in user_data:
            return user_data["watermark"]
        return {
            "enabled": False,
            "text": "© {username} • Cover Bot",
            "position": "bottom-right",
            "opacity": 0.7,
            "font_size": 30
        }
    except Exception as e:
        logger.error(f"Error getting watermark settings: {e}")
        return {
            "enabled": False,
            "text": "© {username} • Cover Bot",
            "position": "bottom-right",
            "opacity": 0.7,
            "font_size": 30
        }

def save_watermark_settings(user_id: int, settings: dict) -> bool:
    """Save watermark settings for user"""
    try:
        users_collection = db.get_collection("users")
        users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"watermark": settings}},
            upsert=True
        )
        logger.info(f"✅ Watermark settings saved for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Error saving watermark settings: {e}")
        return False

# ═══════════════════════════════════════════════════════
# WATERMARK MENU FUNCTIONS
# ═══════════════════════════════════════════════════════

async def watermark_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show watermark main menu with all options"""
    query = update.callback_query
    user_id = query.from_user.id
    settings = get_watermark_settings(user_id)
    
    await query.answer()
    
    status = "🟢 ON" if settings.get("enabled", False) else "🔴 OFF"
    
    text = (
        "🎨 <b>Watermark System</b>\n\n"
        f"<b>Status:</b> {status}\n"
        f"<b>Text:</b> <code>{settings.get('text', 'Not set') or 'Not set'}</code>\n"
        f"<b>Position:</b> {settings.get('position', 'bottom-right').replace('-', ' ').title()}\n"
        f"<b>Opacity:</b> {int(settings.get('opacity', 0.7) * 100)}%\n"
        f"<b>Font Size:</b> {settings.get('font_size', 30)}px\n\n"
        "👇 <b>Select an option below:</b>"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔘 Toggle Watermark", callback_data="watermark_toggle")],
        [InlineKeyboardButton("✏️ Set Text", callback_data="watermark_set_text")],
        [InlineKeyboardButton("📌 Change Position", callback_data="watermark_position")],
        [InlineKeyboardButton("🎚️ Adjust Opacity", callback_data="watermark_opacity")],
        [InlineKeyboardButton("📏 Font Size", callback_data="watermark_font_size")],
        [InlineKeyboardButton("⬅️ Back to Settings", callback_data="menu_settings")]
    ])
    
    try:
        msg = query.message
        if hasattr(msg, "photo") and msg.photo:
            await msg.edit_caption(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await msg.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Watermark menu error: {e}")
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

async def watermark_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle watermark ON/OFF"""
    query = update.callback_query
    user_id = query.from_user.id
    settings = get_watermark_settings(user_id)
    settings["enabled"] = not settings.get("enabled", False)
    save_watermark_settings(user_id, settings)
    
    status = "✅ ENABLED" if settings["enabled"] else "❌ DISABLED"
    await query.answer(f"Watermark {status}")
    await watermark_menu_callback(update, context)

async def watermark_set_text_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt for watermark text input"""
    query = update.callback_query
    await query.answer()
    
    text = (
        "✏️ <b>Set Watermark Text</b>\n\n"
        "Send me your watermark text.\n\n"
        "<b>📌 Variables you can use:</b>\n"
        "• <code>{username}</code> – User's Telegram username\n"
        "• <code>{first_name}</code> – User's first name\n"
        "• <code>{bot_name}</code> – Bot name\n"
        "• <code>{date}</code> – Current date\n"
        "• <code>{time}</code> – Current time\n\n"
        "<b>💡 Examples:</b>\n"
        "<code>© {username} • Cover Bot</code>\n"
        "<code>Made with ❤️ by {first_name}</code>\n"
        "<code>{date} • {bot_name}</code>\n\n"
        "📤 <b>Send your text now</b>\n"
        "Send /cancel to cancel"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back", callback_data="watermark_settings")]
    ])
    
    context.user_data['awaiting_watermark_text'] = True
    
    try:
        msg = query.message
        if hasattr(msg, "photo") and msg.photo:
            await msg.edit_caption(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await msg.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error setting watermark text: {e}")

async def handle_watermark_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle watermark text input from user"""
    if not context.user_data.get('awaiting_watermark_text', False):
        return False
    
    user_id = update.message.from_user.id
    text_input = update.message.text.strip()
    
    if text_input.lower() == "/cancel":
        context.user_data['awaiting_watermark_text'] = False
        await update.message.reply_text("❌ Cancelled", parse_mode="HTML")
        return True
    
    if len(text_input) > 100:
        await update.message.reply_text(
            "❌ <b>Text too long!</b>\n\n"
            "Maximum 100 characters allowed.\n"
            "Please send a shorter text.",
            parse_mode="HTML"
        )
        return True
    
    settings = get_watermark_settings(user_id)
    settings["text"] = text_input
    settings["enabled"] = True
    save_watermark_settings(user_id, settings)
    context.user_data['awaiting_watermark_text'] = False
    
    text = (
        "✅ <b>Watermark Text Saved!</b>\n\n"
        f"📝 <b>Your watermark:</b>\n<code>{text_input}</code>\n\n"
        "💡 <b>Variables will be replaced automatically:</b>\n"
        "• {username} → Your username\n"
        "• {date} → Current date\n"
        "• {time} → Current time\n\n"
        "Watermark has been automatically <b>enabled</b>."
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Back to Watermark Settings", callback_data="watermark_settings")]
    ])
    
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
    return True

# ═══════════════════════════════════════════════════════
# WATERMARK POSITION FUNCTIONS
# ═══════════════════════════════════════════════════════

async def watermark_position_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show watermark position selection"""
    query = update.callback_query
    user_id = query.from_user.id
    settings = get_watermark_settings(user_id)
    current = settings.get("position", "bottom-right")
    
    positions = [
        ("↖️ Top Left", "top-left"),
        ("↗️ Top Right", "top-right"),
        ("↙️ Bottom Left", "bottom-left"),
        ("↘️ Bottom Right", "bottom-right"),
        ("🎯 Center", "center")
    ]
    
    keyboard = []
    for label, value in positions:
        is_current = " ✅" if value == current else ""
        keyboard.append([InlineKeyboardButton(f"{label}{is_current}", callback_data=f"watermark_pos_{value}")])
    
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="watermark_settings")])
    
    guide = (
        "┌─────────────────────┐\n"
        "│ ↖️ TL      ↗️ TR   │\n"
        "│                     │\n"
        "│      🎯 Center      │\n"
        "│                     │\n"
        "│ ↙️ BL      ↘️ BR   │\n"
        "└─────────────────────┘"
    )
    
    text = (
        "📌 <b>Select Watermark Position</b>\n\n"
        f"Current: <b>{current.replace('-', ' ').title()}</b>\n\n"
        "<b>🖼️ Position Guide:</b>\n"
        f"<code>{guide}</code>\n\n"
        "👇 <b>Select a position:</b>"
    )
    
    try:
        msg = query.message
        if hasattr(msg, "photo") and msg.photo:
            await msg.edit_caption(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        else:
            await msg.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        await query.answer()
    except Exception as e:
        logger.error(f"Watermark position error: {e}")

async def watermark_position_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set watermark position"""
    query = update.callback_query
    user_id = query.from_user.id
    position = query.data.replace("watermark_pos_", "")
    
    settings = get_watermark_settings(user_id)
    settings["position"] = position
    save_watermark_settings(user_id, settings)
    
    await query.answer(f"✅ Position: {position.replace('-', ' ').title()}")
    # ✅ Return to position selection menu
    await watermark_position_callback(update, context)

# ═══════════════════════════════════════════════════════
# WATERMARK OPACITY FUNCTIONS
# ═══════════════════════════════════════════════════════

async def watermark_opacity_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show opacity selection with visual preview"""
    query = update.callback_query
    user_id = query.from_user.id
    settings = get_watermark_settings(user_id)
    current = settings.get("opacity", 0.7)
    
    opacities = [
        (0.1, "10% - Very Subtle"),
        (0.2, "20% - Light"),
        (0.3, "30% - Soft"),
        (0.4, "40% - Medium Light"),
        (0.5, "50% - Medium"),
        (0.6, "60% - Medium Dark"),
        (0.7, "70% - Dark"),
        (0.8, "80% - Very Dark"),
        (0.9, "90% - Almost Solid"),
        (1.0, "100% - Solid")
    ]
    
    keyboard = []
    for value, label in opacities:
        is_current = " ✅" if abs(value - current) < 0.01 else ""
        keyboard.append([InlineKeyboardButton(f"{label}{is_current}", callback_data=f"watermark_op_{value}")])
    
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="watermark_settings")])
    
    opacity_bar = _create_opacity_bar(current)
    
    text = (
        "🎚️ <b>Select Watermark Opacity</b>\n\n"
        f"{opacity_bar}\n"
        f"Current: <b>{int(current * 100)}%</b>\n\n"
        "👇 <b>Select opacity level:</b>"
    )
    
    try:
        msg = query.message
        if hasattr(msg, "photo") and msg.photo:
            await msg.edit_caption(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        else:
            await msg.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        await query.answer()
    except Exception as e:
        logger.error(f"Watermark opacity error: {e}")

async def watermark_opacity_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set watermark opacity"""
    query = update.callback_query
    user_id = query.from_user.id
    opacity = float(query.data.replace("watermark_op_", ""))
    
    settings = get_watermark_settings(user_id)
    settings["opacity"] = opacity
    save_watermark_settings(user_id, settings)
    
    await query.answer(f"✅ Opacity: {int(opacity * 100)}%")
    await watermark_opacity_callback(update, context)

def _create_opacity_bar(current_opacity: float) -> str:
    """Create visual opacity bar"""
    total_bars = 20
    filled = int(current_opacity * total_bars)
    empty = total_bars - filled
    bar = "█" * filled + "░" * empty
    return f"<code>{bar}</code>"

# ═══════════════════════════════════════════════════════
# WATERMARK FONT SIZE FUNCTIONS
# ═══════════════════════════════════════════════════════

async def watermark_font_size_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show font size selection"""
    query = update.callback_query
    user_id = query.from_user.id
    settings = get_watermark_settings(user_id)
    current = settings.get("font_size", 30)
    
    font_sizes = [16, 20, 24, 28, 30, 32, 36, 40, 48, 56, 64]
    
    keyboard = []
    row = []
    for i, size in enumerate(font_sizes):
        is_current = " ✅" if size == current else ""
        row.append(InlineKeyboardButton(f"{size}px{is_current}", callback_data=f"watermark_font_{size}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="watermark_settings")])
    
    text = (
        "📏 <b>Select Font Size</b>\n\n"
        f"Current: <b>{current}px</b>\n\n"
        "👇 <b>Select a size:</b>"
    )
    
    try:
        msg = query.message
        if hasattr(msg, "photo") and msg.photo:
            await msg.edit_caption(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        else:
            await msg.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        await query.answer()
    except Exception as e:
        logger.error(f"Font size error: {e}")

async def watermark_font_size_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set watermark font size"""
    query = update.callback_query
    user_id = query.from_user.id
    font_size = int(query.data.replace("watermark_font_", ""))
    
    settings = get_watermark_settings(user_id)
    settings["font_size"] = font_size
    save_watermark_settings(user_id, settings)
    
    await query.answer(f"✅ Font Size: {font_size}px")
    await watermark_font_size_callback(update, context)

# ═══════════════════════════════════════════════════════
# CANCEL FUNCTION
# ═══════════════════════════════════════════════════════

async def cancel_watermark_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel watermark setup process"""
    user_id = update.message.from_user.id
    
    if context.user_data.get('awaiting_watermark_text', False):
        context.user_data['awaiting_watermark_text'] = False
        await update.message.reply_text(
            "❌ <b>Watermark Setup Cancelled</b>\n\n"
            "You can start again anytime from Settings.",
            parse_mode="HTML"
        )
        logger.info(f"User {user_id} cancelled watermark text setup")
        return True
    
    await update.message.reply_text(
        "ℹ️ No ongoing watermark setup to cancel.",
        parse_mode="HTML"
    )
    return True

# ═══════════════════════════════════════════════════════
# REGISTER HANDLERS
# ═══════════════════════════════════════════════════════

def register_watermark_handlers(app):
    """Register all watermark-related handlers with the bot application"""
    
    # ⚠️ IMPORTANT: Pattern exact match karo
    app.add_handler(CallbackQueryHandler(watermark_menu_callback, pattern="^watermark_settings$"))
    
    app.add_handler(CallbackQueryHandler(watermark_toggle_callback, pattern="^watermark_toggle$"))
    app.add_handler(CallbackQueryHandler(watermark_set_text_callback, pattern="^watermark_set_text$"))
    app.add_handler(CallbackQueryHandler(watermark_position_callback, pattern="^watermark_position$"))
    app.add_handler(CallbackQueryHandler(watermark_opacity_callback, pattern="^watermark_opacity$"))
    app.add_handler(CallbackQueryHandler(watermark_font_size_callback, pattern="^watermark_font_size$"))
    
    app.add_handler(CallbackQueryHandler(watermark_position_set_callback, pattern="^watermark_pos_"))
    app.add_handler(CallbackQueryHandler(watermark_opacity_set_callback, pattern="^watermark_op_"))
    app.add_handler(CallbackQueryHandler(watermark_font_size_set_callback, pattern="^watermark_font_"))
    
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_watermark_text_input
    ), group=21)
    
    app.add_handler(CommandHandler("cancel", cancel_watermark_setup))
    
    logger.info("✅ Watermark handlers registered successfully")
    return app
