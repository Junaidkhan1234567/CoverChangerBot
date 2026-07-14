# verification_handlers.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import logging
import os
from datetime import datetime
from verification import (
    create_verification, verify_user, is_user_verified,
    send_verification_alert, send_verification_success,
    reset_user_verification, send_verification_log,
    toggle_verification, toggle_shortlink, check_verification
)
from database import db

logger = logging.getLogger(__name__)

OWNER_USERNAME = os.environ.get("OWNER_USERNAME", "")

async def handle_verification_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start verify_xxx_xxx"""
    user_id = update.effective_user.id
    
    if context.args and len(context.args) > 0:
        arg = context.args[0]
        
        if arg.startswith("verify_"):
            parts = arg.split("_")
            
            if len(parts) == 3:
                target_user_id = int(parts[1])
                verify_id = parts[2]
                
                if user_id != target_user_id:
                    await update.message.reply_text(
                        "❌ <b>This link is not for you!</b>",
                        parse_mode="HTML"
                    )
                    return
                
                if await verify_user(user_id, verify_id):
                    await send_verification_success(update, context)
                    await send_verification_log(context, user_id, "✅ Verified")
                else:
                    await update.message.reply_text(
                        "❌ <b>Invalid or Expired Link!</b>\n\nPlease try again.",
                        parse_mode="HTML"
                    )
                return
    
    from bot import start
    await start(update, context)

async def verification_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle verification callbacks"""
    query = update.callback_query
    user_id = query.from_user.id
    
    from bot import is_admin
    
    if query.data == "toggle_verify":
        if not is_admin(user_id):
            await query.answer("❌ Unauthorized!", show_alert=True)
            return
        
        from verification import VERIFICATION_ENABLED
        VERIFICATION_ENABLED = not VERIFICATION_ENABLED
        status = "🟢 ON" if VERIFICATION_ENABLED else "🔴 OFF"
        
        from verification import VERIFY_EXPIRE
        expire_minutes = VERIFY_EXPIRE // 60
        
        text = f"""🎛️ <b>Verification Toggle</b>

📊 Status: {status}

Users will {'need to verify every ' + str(expire_minutes) + ' minutes' if VERIFICATION_ENABLED else 'not need to verify'} before sending videos."""
        
        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Toggle", callback_data="toggle_verify")],
                [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
            ]),
            parse_mode="HTML"
        )
        await query.answer(f"Verification turned {status}")
    
    elif query.data == "toggle_shortlink":
        if not is_admin(user_id):
            await query.answer("❌ Unauthorized!", show_alert=True)
            return
        
        from verification import SHORTLINK_ENABLED
        SHORTLINK_ENABLED = not SHORTLINK_ENABLED
        status = "🟢 ON" if SHORTLINK_ENABLED else "🔴 OFF"
        
        text = f"""🔗 <b>Shortlink Toggle</b>

📊 Status: {status}

Verification links will {'use shortlink' if SHORTLINK_ENABLED else 'use direct link'}."""
        
        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Toggle", callback_data="toggle_shortlink")],
                [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
            ]),
            parse_mode="HTML"
        )
        await query.answer(f"Shortlink turned {status}")
    
    elif query.data == "get_subscription":
        await query.answer()
        text = f"""💎 <b>Premium Subscription</b>

Get premium and skip verification!

✨ <b>Benefits:</b>
• No verification required
• Priority processing
• Faster video handling
• Direct access

👨‍💻 <b>Contact Admin:</b>
@{OWNER_USERNAME}"""
        
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("👨‍💻 Contact Admin", url=f"https://t.me/{OWNER_USERNAME}")],
            [InlineKeyboardButton("⬅️ Back", callback_data="menu_back")]
        ])
        
        await query.message.edit_text(
            text,
            reply_markup=buttons,
            parse_mode="HTML"
        )
    
    elif query.data == "verify_now":
        await query.answer()
        await send_verification_alert(update, context)
