# watermark.py
import os
import logging
import re
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputFile
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, filters
from telegram.error import BadRequest
from database import save_watermark_settings, get_watermark_settings
from video_editor import video_editor

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════
# WATERMARK SETTINGS MENU
# ═══════════════════════════════════════════════════════

async def watermark_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show complete watermark settings menu"""
    query = update.callback_query
    user_id = query.from_user.id
    settings = get_watermark_settings(user_id)
    
    status = "🟢 ON" if settings.get("enabled", False) else "🔴 OFF"
    
    text = (
        "💧 <b>Watermark Settings</b>\n\n"
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
        [InlineKeyboardButton("🖼️ Preview All Positions", callback_data="watermark_preview")],
        [InlineKeyboardButton("⬅️ Back to Settings", callback_data="menu_settings")]
    ])
    
    try:
        msg = query.message
        if hasattr(msg, "photo") and msg.photo:
            await msg.edit_caption(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await msg.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await query.answer()
    except Exception as e:
        logger.error(f"Watermark settings error: {e}")


async def watermark_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle watermark ON/OFF"""
    query = update.callback_query
    user_id = query.from_user.id
    settings = get_watermark_settings(user_id)
    settings["enabled"] = not settings.get("enabled", False)
    save_watermark_settings(user_id, settings)
    
    status = "✅ ENABLED" if settings["enabled"] else "❌ DISABLED"
    await query.answer(f"Watermark {status}")
    await watermark_settings_callback(update, context)


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
    
    # Position options with visual indicators
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
    
    # Visual position guide
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
        "<b>💡 Recommendations:</b>\n"
        "↘️ Bottom Right - Most common, non-intrusive\n"
        "↙️ Bottom Left - Good for branding\n"
        "↖️ Top Left - Good for logos\n"
        "↗️ Top Right - Less intrusive\n"
        "🎯 Center - Not recommended\n\n"
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
    
    # Opacity options with visual indicators
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
    
    # Opacity visual bar
    opacity_bar = _create_opacity_bar(current)
    
    text = (
        "🎚️ <b>Select Watermark Opacity</b>\n\n"
        f"{opacity_bar}\n"
        f"Current: <b>{int(current * 100)}%</b>\n\n"
        "<b>💡 Tips:</b>\n"
        "• 10-30% - Very subtle, almost invisible\n"
        "• 30-50% - Subtle branding\n"
        "• 50-70% - Standard visibility\n"
        "• 70-90% - Bold branding\n"
        "• 100% - Solid text\n\n"
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
        "<b>💡 Recommendations:</b>\n"
        "• 16-24px - Small, subtle\n"
        "• 24-32px - Standard\n"
        "• 32-48px - Large, visible\n"
        "• 48+px - Bold branding\n\n"
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
# WATERMARK PREVIEW FUNCTIONS
# ═══════════════════════════════════════════════════════

async def watermark_preview_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt user to send video for preview"""
    query = update.callback_query
    await query.answer()
    
    text = (
        "🖼️ <b>Watermark Position Preview</b>\n\n"
        "I'll show you how watermark looks at all positions.\n\n"
        "📤 <b>Send me a video</b> and I'll create a preview.\n\n"
        "The preview will show watermark at:\n"
        "↖️ Top Left\n"
        "↗️ Top Right\n"
        "↙️ Bottom Left\n"
        "↘️ Bottom Right\n"
        "🎯 Center\n\n"
        "<b>📌 Note:</b> Only first 10 seconds will be used.\n\n"
        "📤 <b>Send a video now</b>\n"
        "Send /cancel to cancel"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back", callback_data="watermark_settings")]
    ])
    
    context.user_data['awaiting_preview_video'] = True
    
    try:
        msg = query.message
        if hasattr(msg, "photo") and msg.photo:
            await msg.edit_caption(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await msg.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Preview prompt error: {e}")


async def handle_watermark_preview_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle video for watermark preview"""
    if not context.user_data.get('awaiting_preview_video', False):
        return False
    
    user_id = update.message.from_user.id
    
    if not update.message.video:
        await update.message.reply_text("❌ Please send a video file.", parse_mode="HTML")
        return True
    
    msg = await update.message.reply_text(
        "⏳ Creating watermark preview... (This may take a moment)", 
        parse_mode="HTML"
    )
    
    try:
        video = update.message.video.file_id
        video_file = await context.bot.get_file(video)
        
        # Check file size (max 50MB)
        if video_file.file_size > 50 * 1024 * 1024:
            await msg.edit_text(
                "❌ <b>Video too large!</b>\n\n"
                "Maximum size: 50MB\n"
                "Please send a smaller video for preview.",
                parse_mode="HTML"
            )
            context.user_data['awaiting_preview_video'] = False
            return True
        
        temp_path = os.path.join(video_editor.temp_dir, f"preview_input_{user_id}_{int(datetime.now().timestamp())}.mp4")
        await video_file.download_to_drive(temp_path)
        
        # Get watermark text from settings
        watermark_settings = get_watermark_settings(user_id)
        watermark_text = watermark_settings.get("text", "© Video Cover Bot")
        
        # Create preview
        preview_path = video_editor.create_watermark_preview(temp_path, watermark_text)
        
        # Send preview video
        if preview_path and os.path.exists(preview_path):
            with open(preview_path, 'rb') as f:
                await context.bot.send_video(
                    chat_id=update.effective_chat.id,
                    video=InputFile(f),
                    caption=(
                        "🖼️ <b>Watermark Position Preview</b>\n\n"
                        "📌 <b>Position Guide:</b>\n"
                        "↖️ Top Left\n"
                        "↗️ Top Right\n"
                        "↙️ Bottom Left\n"
                        "↘️ Bottom Right\n"
                        "🎯 Center\n\n"
                        "💡 <b>Choose your preferred position:</b>\n"
                        "Go to <b>Settings → Watermark → Change Position</b>\n\n"
                        "⚙️ <b>Adjust other settings:</b>\n"
                        "• Text: Settings → Watermark → Set Text\n"
                        "• Opacity: Settings → Watermark → Adjust Opacity\n"
                        "• Font Size: Settings → Watermark → Font Size"
                    ),
                    parse_mode="HTML"
                )
        else:
            await msg.edit_text(
                "❌ <b>Preview creation failed</b>\n\n"
                "Please try again with a different video.",
                parse_mode="HTML"
            )
        
        # Cleanup
        try:
            os.remove(temp_path)
            if preview_path and os.path.exists(preview_path):
                os.remove(preview_path)
        except:
            pass
        
        await msg.delete()
        context.user_data['awaiting_preview_video'] = False
        
        # Send back to watermark settings
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back to Watermark Settings", callback_data="watermark_settings")]
        ])
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="✅ Preview created! Choose your position from settings.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"❌ Preview error: {e}")
        await msg.edit_text(
            f"❌ <b>Error creating preview:</b>\n\n"
            f"{str(e)[:100]}\n\n"
            "Please try with a smaller video file.",
            parse_mode="HTML"
        )
        context.user_data['awaiting_preview_video'] = False
    
    return True


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
    
    if context.user_data.get('awaiting_preview_video', False):
        context.user_data['awaiting_preview_video'] = False
        await update.message.reply_text(
            "❌ <b>Preview Cancelled</b>\n\n"
            "You can start again anytime from Watermark Settings.",
            parse_mode="HTML"
        )
        logger.info(f"User {user_id} cancelled watermark preview")
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
    
    # Watermark main handlers
    app.add_handler(CallbackQueryHandler(watermark_settings_callback, pattern="^watermark_settings$"))
    app.add_handler(CallbackQueryHandler(watermark_toggle_callback, pattern="^watermark_toggle$"))
    app.add_handler(CallbackQueryHandler(watermark_set_text_callback, pattern="^watermark_set_text$"))
    app.add_handler(CallbackQueryHandler(watermark_position_callback, pattern="^watermark_position$"))
    app.add_handler(CallbackQueryHandler(watermark_opacity_callback, pattern="^watermark_opacity$"))
    app.add_handler(CallbackQueryHandler(watermark_font_size_callback, pattern="^watermark_font_size$"))
    app.add_handler(CallbackQueryHandler(watermark_preview_prompt, pattern="^watermark_preview$"))
    
    # Position and opacity set handlers
    app.add_handler(CallbackQueryHandler(watermark_position_set_callback, pattern="^watermark_pos_"))
    app.add_handler(CallbackQueryHandler(watermark_opacity_set_callback, pattern="^watermark_op_"))
    app.add_handler(CallbackQueryHandler(watermark_font_size_set_callback, pattern="^watermark_font_"))
    
    # Text input handler
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_watermark_text_input
    ), group=21)
    
    # Preview video handler
    app.add_handler(MessageHandler(
        filters.VIDEO,
        handle_watermark_preview_video
    ), group=22)
    
    # Cancel command handler
    app.add_handler(CommandHandler("cancel", cancel_watermark_setup))
    
    logger.info("✅ Watermark handlers registered successfully")
    return app
