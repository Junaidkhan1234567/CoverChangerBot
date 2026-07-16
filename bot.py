import os
import logging
import asyncio
import re
from datetime import datetime, timezone, timedelta
from channel import get_ist_datetime_str
from telegram import InputMediaVideo, Update, InputFile, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
)
from config import config
import sys
from updater import update_from_upstream
from telegram.error import BadRequest, RetryAfter
import random
from database import (
    save_thumbnail, get_thumbnail, delete_thumbnail, has_thumbnail,
    ban_user, unban_user, is_user_banned, get_total_users, get_banned_users_count, get_stats,
    format_log_message, log_new_user, log_user_banned, log_user_unbanned,
    log_thumbnail_set, log_thumbnail_removed
)
from telegram import MessageEntity
from flask import Flask
import threading

# ═══════════════════ CHANNEL IMPORTS ═══════════════════
from channel import (
    show_channel_settings,
    channel_set_prompt,
    channel_remove,
    channel_toggle_forward,
    handle_channel_id_input,
    register_channel_handlers,
    get_user_channel,
    should_forward_to_channel
)
# ═══════════════════════════════════════════════════════

# ✅ LOG UTILS IMPORT
from log_utils import (
    force_send_log,
    log_user_start,
    log_thumbnail_set as log_thumb_set,
    log_video_processed,
    log_thumbnail_deleted
)

app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is running!", 200

def run_flask():
    app.run(host="0.0.0.0", port=8080)

threading.Thread(target=run_flask, daemon=True).start()

def bold_entities(text: str):
    """Return entities list to make full caption bold"""
    if not text:
        return None
    return [MessageEntity(type="bold", offset=0, length=len(text))]

# Logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Token from config or environment
TOKEN = getattr(config, "BOT_TOKEN", None) or os.environ.get("BOT_TOKEN")
if not TOKEN:
    logger.error("BOT_TOKEN not set in config or environment (config.env).")
    raise SystemExit("BOT_TOKEN not set")

OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
FORCE_SUB_CHANNEL_ID = os.environ.get("FORCE_SUB_CHANNEL_ID")
FORCE_SUB_BANNER_URL = os.environ.get("FORCE_SUB_BANNER_URL")
HOME_MENU_BANNER_URL = os.environ.get("HOME_MENU_BANNER_URL")
OWNER_USERNAME = os.environ.get("OWNER_USERNAME", "")
LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID")

# Fallback: collect images from ./ui/ and pick randomly when showing banner
FALLBACK_BANNER = None
UI_BANNERS = []
try:
    ui_dir = os.path.join(os.path.dirname(__file__), "ui")
    if os.path.isdir(ui_dir):
        UI_BANNERS = [os.path.join(ui_dir, f) for f in os.listdir(ui_dir) if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]
        if UI_BANNERS:
            FALLBACK_BANNER = UI_BANNERS[0]
except Exception:
    UI_BANNERS = []
    FALLBACK_BANNER = None

FORCE_SUB_BANNER = FORCE_SUB_BANNER_URL or FALLBACK_BANNER

def get_force_banner():
    if FORCE_SUB_BANNER_URL:
        return FORCE_SUB_BANNER_URL
    try:
        if UI_BANNERS:
            return random.choice(UI_BANNERS)
    except Exception:
        pass
    return FALLBACK_BANNER


verified_users = set()

"""══════════════════ LOGGING HELPER ══════════════════"""
async def send_log(context: ContextTypes.DEFAULT_TYPE, log_message: str) -> bool:
    if not LOG_CHANNEL_ID:
        logger.debug("LOG_CHANNEL_ID not configured")
        return False
    
    try:
        await context.bot.send_message(
            chat_id=LOG_CHANNEL_ID,
            text=log_message,
            parse_mode="HTML"
        )
        logger.debug(f"✅ Log sent to channel {LOG_CHANNEL_ID}")
        return True
    except Exception as e:
        logger.error(f"❌ Error sending log to channel: {e}")
        return False


"""--------------------HELPER FUNCTIONS--------------------"""
async def send_or_edit(update: Update, text, reply_markup=None, force_banner=None):
    if update.callback_query:
        try:
            msg = update.callback_query.message
            if getattr(msg, "photo", None):
                await msg.edit_caption(
                    text,
                    reply_markup=reply_markup,
                    parse_mode="HTML",
                )
            else:
                await msg.edit_text(
                    text,
                    reply_markup=reply_markup,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
        except BadRequest:
            pass
    else:
        await update.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


async def get_invite_link(bot, chat_id):
    try:
        link_obj = await bot.create_chat_invite_link(chat_id=chat_id, member_limit=1)
        return getattr(link_obj, "invite_link", link_obj)
    except RetryAfter as e:
        secs = getattr(e, "retry_after", None) or 30
        logger.info(f"Rate limited while creating invite link: sleeping {secs}s")
        await asyncio.sleep(secs)
        return await get_invite_link(bot, chat_id)
    except Exception as e:
        logger.error(f"get_invite_link failed: {e}")
        return None

"""--------------------ADMIN CHECK-----------------"""

def is_admin(user_id: int) -> bool:
    admin_list = [OWNER_ID]
    return user_id in admin_list


async def check_admin(update: Update) -> bool:
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return False
    return True


async def check_admin_and_banned(update: Update, user_id_to_check: int = None) -> tuple[bool, str]:
    admin = await check_admin(update)
    if not admin:
        return False, None
    
    if user_id_to_check and is_user_banned(user_id_to_check):
        return True, "banned"
    return True, None


"""------------------FORCE-SUB CHECK-----------------"""

async def check_force_sub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id

    if user_id == OWNER_ID:
        return True

    if not FORCE_SUB_CHANNEL_ID:
        return True

    if user_id in verified_users:
        logger.info(f"🔍 User {user_id} is cached - checking if still a member...")
        
        try:
            channel_id_str = str(FORCE_SUB_CHANNEL_ID).strip()
            
            try:
                if channel_id_str.startswith("-"):
                    channel_id = int(channel_id_str)
                else:
                    try:
                        channel_id = int(channel_id_str)
                    except ValueError:
                        channel_id = channel_id_str
            except Exception:
                channel_id = channel_id_str
            
            member = await context.bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            
            if member.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
                logger.info(f"✅ User {user_id} is still a member - access granted")
                return True
            
            logger.warning(f"⚠️ User {user_id} left the channel - removing from cache")
            verified_users.discard(user_id)
            
        except Exception as e:
            logger.warning(f"Could not verify membership for cached user {user_id}: {e}")
            verified_users.discard(user_id)
    
    logger.info(f"🔒 User {user_id} not verified or left channel - showing join prompt")

    try:
        channel_id_str = str(FORCE_SUB_CHANNEL_ID).strip()
        logger.info(f"📌 Channel config: {channel_id_str}")
        
        try:
            if channel_id_str.startswith("-"):
                channel_chat_id = int(channel_id_str)
            else:
                try:
                    channel_chat_id = int(channel_id_str)
                except ValueError:
                    channel_chat_id = channel_id_str
        except Exception as parse_err:
            logger.error(f"❌ Channel ID parse error: {parse_err}")
            channel_chat_id = channel_id_str

        try:
            logger.info(f"📍 Getting chat info for {channel_chat_id}")
            chat = await context.bot.get_chat(channel_chat_id)
            channel_name = chat.title or chat.username or "Channel"
            logger.info(f"✅ Got chat info: {channel_name}")
            
            invite_link = None
            if chat.username:
                invite_link = f"https://t.me/{chat.username}"
            elif hasattr(chat, 'invite_link') and chat.invite_link:
                invite_link = chat.invite_link
            
            if not invite_link:
                try:
                    link_obj = await context.bot.create_chat_invite_link(
                        chat_id=channel_chat_id, 
                        member_limit=1
                    )
                    invite_link = link_obj.invite_link
                except Exception as link_error:
                    logger.warning(f"Could not create invite link: {link_error}")
                    if str(channel_chat_id).startswith('-100'):
                        invite_link = f"https://t.me/c/{str(channel_chat_id)[4:]}"
                    else:
                        invite_link = f"https://t.me/{channel_chat_id}"
            
        except Exception as e:
            logger.error(f"Could not get chat info: {e}")
            return True

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Join Channel", url=invite_link)],
            [
                InlineKeyboardButton("✅ I've Joined", callback_data="check_fsub"),
                InlineKeyboardButton("✖️ Close", callback_data="close_banner")
            ]
        ])
        
        prompt = (
            "🔒 To use this bot, you must join our channel\n\n"
            f"👉 Join our channel:\n\n"
            f"<b>📢 {channel_name}</b>\n\n"
            "👉 Subscribe & hit the bell icon\n\n"
            "👇 Click below after joining 👇"
        )

        try:
            banner = FORCE_SUB_BANNER_URL
            
            if update.message:
                if banner:
                    try:
                        if isinstance(banner, str) and os.path.isfile(banner):
                            await update.message.reply_photo(
                                photo=InputFile(banner),
                                caption=prompt,
                                reply_markup=kb,
                                parse_mode="HTML"
                            )
                        else:
                            await update.message.reply_photo(
                                photo=banner,
                                caption=prompt,
                                reply_markup=kb,
                                parse_mode="HTML"
                            )
                    except Exception as banner_err:
                        logger.warning(f"Could not send banner, sending text instead: {banner_err}")
                        await update.message.reply_text(
                            prompt,
                            reply_markup=kb,
                            parse_mode="HTML"
                        )
                else:
                    await update.message.reply_text(
                        prompt,
                        reply_markup=kb,
                        parse_mode="HTML"
                    )
            elif update.callback_query:
                if banner:
                    try:
                        await update.callback_query.message.edit_caption(
                            caption=prompt,
                            reply_markup=kb,
                            parse_mode="HTML"
                        )
                    except Exception:
                        await update.callback_query.message.edit_text(
                            prompt,
                            reply_markup=kb,
                            parse_mode="HTML"
                        )
                else:
                    await update.callback_query.message.edit_text(
                        prompt,
                        reply_markup=kb,
                        parse_mode="HTML"
                    )
            logger.info(f"🔒 Force-sub prompt shown to user {user_id} with banner")
        except Exception as e:
            logger.error(f"Failed to show prompt: {e}")
            return True

        return False

    except Exception as e:
        logger.error(f"Force-Sub Error: {e}", exc_info=True)
        return True


async def send_home_menu(context, chat_id: int, user_id: int = None):
    """Helper function to send home menu with banner - SAME TEXT AS /start"""
    text = (
        "<b>Welcome to Cover Changer Bot ✅</b>\n\n"
        "• Send/forward Image → Save cover\n"
        "• Send/forward video → Apply cover\n"
        "• /showthumbnail → View cover\n\n"
        "📊 The bot never offline unless maintenance or admin intervention."
    )
    
    kb_rows = [
        [InlineKeyboardButton("❓ Help", callback_data="menu_help"),
         InlineKeyboardButton("ℹ️ About", callback_data="menu_about")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings"),
         InlineKeyboardButton("👨‍💻 Developer", callback_data="menu_developer")],
    ]
    
    if user_id and is_admin(user_id):
        kb_rows.append([InlineKeyboardButton("🛠️ Admin Panel", callback_data="admin_back")])
    
    kb = InlineKeyboardMarkup(kb_rows)
    banner = HOME_MENU_BANNER_URL
    
    if banner:
        try:
            if isinstance(banner, str) and os.path.isfile(banner):
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=InputFile(banner),
                    caption=text,
                    reply_markup=kb,
                    parse_mode="HTML"
                )
            else:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=banner,
                    caption=text,
                    reply_markup=kb,
                    parse_mode="HTML"
                )
            return
        except Exception as e:
            logger.warning(f"Could not send banner: {e}")
    
    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=kb,
        parse_mode="HTML"
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    logger.info(f"🔵 CALLBACK | Data: {query.data}")
    
    if not query or not query.data:
        logger.error("❌ Invalid query!")
        return

    user_id = query.from_user.id
    logger.info(f"👤 User ID: {user_id} | Channel ID Config: {FORCE_SUB_CHANNEL_ID}")
    
    # ═══════════════════ CHANNEL SETTINGS CALLBACKS ═══════════════════
    if query.data == "channel_settings":
        await show_channel_settings(update, context)
        return
    
    if query.data == "channel_set":
        await channel_set_prompt(update, context)
        return
    
    if query.data == "channel_remove":
        await channel_remove(update, context)
        return
    
    if query.data == "channel_toggle_forward":
        await channel_toggle_forward(update, context)
        return
    # ════════════════════════════════════════════════════════════════
    
    # ✅ OLD MESSAGE DELETE KARO
    try:
        await query.message.delete()
    except Exception:
        pass
    
    await query.answer()
    
    if query.data == "check_fsub":
        logger.info(f"🔍 Verify button clicked by user {user_id}")
        
        if not FORCE_SUB_CHANNEL_ID:
            logger.warning("⚠️ FORCE_SUB_CHANNEL_ID not configured")
            await query.answer("✅ Bot configured successfully!", show_alert=False)
            await send_home_menu(context, user_id, user_id)
            return
        
        try:
            channel_id_str = str(FORCE_SUB_CHANNEL_ID).strip()
            logger.info(f"📌 Channel ID string: {channel_id_str}")
            
            try:
                if channel_id_str.startswith("-"):
                    channel_id = int(channel_id_str)
                else:
                    try:
                        channel_id = int(channel_id_str)
                    except ValueError:
                        channel_id = channel_id_str
            except Exception as parse_error:
                logger.error(f"❌ Failed to parse channel ID: {parse_error}")
                channel_id = channel_id_str
            
            logger.info(f"🔎 Checking membership for user {user_id} in channel {channel_id}")
            
            try:
                member = await context.bot.get_chat_member(chat_id=channel_id, user_id=user_id)
                logger.info(f"📊 Member status: {member.status}")
            except Exception as member_error:
                logger.error(f"❌ Error checking membership: {member_error}")
                await query.answer("❌ Channel not found! Please try again.", show_alert=True)
                return
            
            if member.status in (
                ChatMemberStatus.MEMBER,
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.OWNER
            ):
                verified_users.add(user_id)
                logger.info(f"✅ User {user_id} verified successfully with status {member.status}")
                await query.answer("✅ Channel verified successfully!", show_alert=False)
                await send_home_menu(context, user_id, user_id)
                return
            
            logger.warning(f"⚠️ User {user_id} not a member. Status: {member.status}")
            await query.answer("❌ You haven't joined the channel yet!\n\nPlease join the channel then click again.", show_alert=True)
            return
            
        except Exception as e:
            logger.error(f"❌ Verification error: {type(e).__name__}: {e}", exc_info=True)
            await query.answer("❌ Verification failed!\n\nPlease make sure you have joined the channel.", show_alert=True)
            return
    
    if query.data == "close_banner":
        logger.info(f"❌ User {user_id} closed banner")
        return
    
    if query.data == "admin_stats":
        if not is_admin(user_id):
            await query.answer("❌ Unauthorized", show_alert=True)
            return
        stats = get_stats()
        text = (
            "📊 Bot Statistics\n\n"
            f"👥 Total users: {stats['total_users']}\n"
            f"🚫 Banned users: {stats['banned_users']}\n"
            f"🖼 Users with thumbnail: {stats['users_with_thumbnail']}"
        )
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
        ])
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=back_kb,
            parse_mode="HTML"
        )
        return
    
    if query.data == "admin_users":
        if not is_admin(user_id):
            await query.answer("❌ Unauthorized", show_alert=True)
            return
        stats = get_stats()
        total_users = stats['total_users']
        banned_users = stats['banned_users']
        active_users = total_users - banned_users
        
        text = (
            "👥 User Management\n\n"
            f"📊 Total users: {total_users}\n"
            f"✅ Active users: {active_users}\n"
            f"🚫 Banned users: {banned_users}\n\n"
            f"📈 Ban rate: {(banned_users/total_users*100):.1f}%"
        )
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
        ])
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=back_kb,
            parse_mode="HTML"
        )
        return
    
    if query.data == "admin_status":
        if not is_admin(user_id):
            await query.answer("❌ Unauthorized", show_alert=True)
            return
        try:
            import psutil
            import time
            cpu_percent = psutil.cpu_percent(interval=1)
            ram = psutil.virtual_memory()
            text = (
                "⏱️ Bot Status\n\n"
                f"🟢 Status: Online\n\n"
                f"🖥 System Resources:\n"
                f"CPU: {cpu_percent}%\n"
                f"RAM: {ram.percent}%"
            )
        except ImportError:
            text = "⏱️ <b>Bot Status</b>\n\n🟢 Status: <b>Online</b>"
        
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
        ])
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=back_kb,
            parse_mode="HTML"
        )
        return
    
    if query.data == "admin_ban":
        if not is_admin(user_id):
            await query.answer("❌ Unauthorized", show_alert=True)
            return
        text = "🚫 Ban User\n\nSend /ban <user_id> <reason> to ban a user"
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
        ])
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=back_kb, parse_mode="HTML")
        return
    
    if query.data == "admin_unban":
        if not is_admin(user_id):
            await query.answer("❌ Unauthorized", show_alert=True)
            return
        text = "✅ Unban User\n\nSend /unban <user_id> to unban a user"
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
        ])
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=back_kb, parse_mode="HTML")
        return
    
    if query.data == "admin_broadcast":
        if not is_admin(user_id):
            await query.answer("❌ Unauthorized", show_alert=True)
            return
        text = "📢 Broadcast Message\n\nSend /broadcast <message> to send to all users"
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
        ])
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=back_kb, parse_mode="HTML")
        return
    
    if query.data == "admin_back":
        if not is_admin(user_id):
            await query.answer("❌ Unauthorized", show_alert=True)
            return
        text = (
            "🛠️ Admin Control Panel\n\n"
            "<b>Management Options:</b>\n\n"
            "📊 <b>Statistics</b> – View user analytics\n"
            "⏱️ <b>Status</b> – Bot performance\n"
            "🚫 <b>Ban User</b> – Block users\n"
            "✅ <b>Unban</b> – Restore access"
        )
        admin_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats"),
             InlineKeyboardButton("⏱️ Status", callback_data="admin_status")],
            [InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban"),
             InlineKeyboardButton("✅ Unban", callback_data="admin_unban")],
            [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
             InlineKeyboardButton("⬅️ Back", callback_data="menu_back")],
        ])
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=admin_kb,
            parse_mode="HTML"
        )
        return

    if query.data == "contact_owner":
        logger.info(f"📞 Contact owner for user {user_id}")
        if OWNER_USERNAME:
            await context.bot.send_message(chat_id=user_id, text=f"Contact owner: https://t.me/{OWNER_USERNAME}")
        else:
            await context.bot.send_message(chat_id=user_id, text="Owner contact not configured.")
        return

    # ✅ MENU CALLBACKS
    if query.data.startswith("menu_"):
        key = query.data.split("menu_")[1]
        logger.info(f"📋 Menu callback: {key} for user {user_id}")
        
        # ✅ menu_back - DIRECT HOME MENU (BANNER KE SAATH)
        if key == "back":
            await send_home_menu(context, user_id, user_id)
            return
        
        if key == "help":
            text = (
                "ℹ️ Help Menu\n\n"
                "<b>How to use:</b>\n\n"
                "<b>1️⃣ Save Your Thumbnail</b>\n"
                "   • Send any photo\n"
                "   • Automatically saved as cover\n\n"
                "<b>2️⃣ Apply to Videos</b>\n"
                "   • Send any video\n"
                "   • Thumbnail applies instantly\n\n"
                "<b>Additional Commands:</b>\n"
                "/remove – Delete saved thumbnail\n"
                "/showthumbnail – View saved thumbnail\n"
                "/settings – View & manage settings\n"
                "/about – Information about bot"
            )
            back_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back", callback_data="menu_back")]
            ])
            await context.bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=back_kb,
                parse_mode="HTML"
            )
            return
        
        if key == "about":
            text = (
                "🤖 About Cover Changer Bot\n\n"
                "<b>What it does:</b>\n\n"
                "✅ <b>One-Click Thumbnail</b>\n"
                "   Send photo, apply to videos\n\n"
                "✅ <b>Instant Processing</b>\n"
                "   Fast cover application\n\n"
                "✅ <b>Secure & Safe</b>\n"
                "   Your data is protected\n\n"
                "<b>Technology:</b>\n"
                "⚙️ Powered by Python\n"
                "🔒 Secure & Reliable Integration"
            )
            back_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back", callback_data="menu_back")]
            ])
            await context.bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=back_kb,
                parse_mode="HTML"
            )
            return
        
        if key == "settings":
            text = (
                "⏰ <b>Time Now (IST)</b> - {ist_time}\n"
                "⚙️ <b>Config Bot Settings</b>\n\n"
                "Select an option below to change settings 👇\n\n"
            )
            settings_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🖼️ Thumbnails", callback_data="submenu_thumbnails")],
                [InlineKeyboardButton("📢 ᴀᴅᴅ ʏᴏᴜʀ ᴄʜᴀɴɴᴇʟ", callback_data="channel_set")],
                [InlineKeyboardButton("⬅️ Back", callback_data="menu_back")]
            ])
            await context.bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=settings_kb,
                parse_mode="HTML"
            )
            return
        
        if key == "developer":
            dev_contact = f"https://t.me/{OWNER_USERNAME}" if OWNER_USERNAME else f"tg://user?id={OWNER_ID}"
            text = (
                "👨‍💻 <b>Developer</b>\n\n"
                f"Contact: {dev_contact}\n"
                "For help, support, or feedback, contact the developer."
            )
            back_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back", callback_data="menu_back")]
            ])
            await context.bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=back_kb,
                parse_mode="HTML"
            )
            return
        
        text = "ℹ️ <b>Info</b>\n\nNo information available for this section."
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="menu_back")]
        ])
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=back_kb,
            parse_mode="HTML"
        )
        return
    
    if query.data == "submenu_thumbnails":
        thumb_status = "✅ Saved" if has_thumbnail(user_id) else "❌ Not saved"
        text = (
            "🖼️ <b>Thumbnail Manager</b>\n\n"
            f"<b>Current status:</b> {thumb_status}\n\n"
            "📚 <b>Available actions:</b>\n\n"
            "💾 Save Thumbnail\n"
            "Send a new photo as your cover video\n\n"
            "👁️ Show Thumbnail\n"
            "View your currently saved thumbnail\n\n"
            "🗑️ Delete Thumbnail\n"
            "Remove your saved thumbnail"
        )
        thumb_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💾 Save Thumbnail", callback_data="thumb_save_info"),
             InlineKeyboardButton("👁️ Show Thumbnail", callback_data="thumb_show")],
            [InlineKeyboardButton("🗑️ Delete Thumbnail", callback_data="thumb_delete"),
             InlineKeyboardButton("⬅️ Back", callback_data="menu_settings")]
        ])
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=thumb_kb,
            parse_mode="HTML"
        )
        return
    
    if query.data == "thumb_save_info":
        text = (
            "💾 Save Your Thumbnail\n\n"
            "📸 How it works:\n\n"
            "<b>Step 1️⃣:</b> Send a photo\n"
            "→ Go back and send any photo\n"
            "→ This will be your cover\n\n"
            "<b>Step 2️⃣:</b> Automatically Save\n"
            "→ Thumbnail saves automatically\n"
            "→ Ready for use\n\n"
            "<b>Step 3️⃣:</b> Ready to Use\n"
            "→ Send any video\n"
            "→ Cover applies instantly\n\n"
            "💡 Tips:\n"
            "• High-resolution images\n"
            "• Square format 1:1\n"
            "• Max 5MB size\n\n"
            "📸 Ready? Send your photo now"
        )
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="submenu_thumbnails")]
        ])
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=back_kb,
            parse_mode="HTML"
        )
        return
    
    if query.data == "thumb_show":
        photo_id = get_thumbnail(user_id)
        if photo_id:
            text = "👁️ Your current thumbnail\n\nThis photo will be applied to your videos\nChange it by sending a new photo"
            back_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back", callback_data="submenu_thumbnails")]
            ])
            try:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=photo_id,
                    caption=text,
                    reply_markup=back_kb,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Error sending thumbnail: {e}")
                await context.bot.send_message(
                    chat_id=user_id,
                    text="❌ Failed to display thumbnail\n\nPlease send a new photo.",
                    parse_mode="HTML"
                )
        else:
            text = "❌ No thumbnail saved yet\n\nSend a photo to create one now"
            back_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back", callback_data="submenu_thumbnails")]
            ])
            await context.bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=back_kb,
                parse_mode="HTML"
            )
        return
    
    if query.data == "thumb_delete":
        if delete_thumbnail(user_id):
            text = "✅ Thumbnail deleted\n\nRemoved successfully. Send a new photo anytime"
        else:
            text = "⚠️ No thumbnail found\n\nSend a photo to create one now"
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="submenu_thumbnails")]
        ])
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=back_kb,
            parse_mode="HTML"
        )
        return
    
    # ✅ MENU_BACK - DIRECT HOME MENU WITH BANNER (SAME TEXT AS /start)
    if query.data == "menu_back":
        await send_home_menu(context, user_id, user_id)
        return
    
    logger.warning(f"⚠️ Unknown callback: {query.data}")
    try:
        await query.answer("Unknown action", show_alert=False)
    except Exception:
        pass


"""---------------------- Menus--------------------- """

async def open_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if update.callback_query:
        try:
            await update.callback_query.message.delete()
        except Exception:
            pass
        await send_home_menu(context, user_id, user_id)
    else:
        await send_home_menu(context, user_id, user_id)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    first_name = update.effective_user.first_name or "User"
    
    user_check = get_thumbnail(user_id)
    is_new_user = user_check is None
    
    if is_new_user:
        try:
            await log_user_start(
                context.bot,
                LOG_CHANNEL_ID,
                user_id,
                username,
                first_name
            )
            logger.info(f"✅ New user log sent for {user_id}")
        except Exception as e:
            logger.error(f"❌ Start log failed for new user: {e}")
        
        log_data = log_new_user(user_id, username, first_name)
        log_msg = format_log_message(user_id, username, log_data["action"], log_data.get("details", ""))
        await send_log(context, log_msg)
    else:
        logger.info(f"👋 Returning user: {user_id} (no log sent)")
    
    if is_user_banned(user_id):
        await update.message.reply_text("🚫 Access denied\n\nYour account has been restricted. Contact support.", parse_mode="HTML")
        return
    
    if not await check_force_sub(update, context):
        logger.warning(f"❌ User {user_id} blocked by force-sub check")
        return
    
    await send_home_menu(context, user_id, user_id)


async def show_thumbnail_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_sub(update, context):
        return
    
    user_id = update.message.from_user.id
    photo_id = get_thumbnail(user_id)
    
    if photo_id:
        text = (
            "🖼️ <b>Your saved thumbnail</b>\n\n"
            "This photo will be applied to your videos\n"
            "Change it by sending a new photo"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑️ Delete Thumbnail", callback_data="thumb_delete")],
            [InlineKeyboardButton("⬅️ Back", callback_data="menu_back")]
        ])
        try:
            await update.message.reply_photo(
                photo=photo_id,
                caption=text,
                reply_markup=kb,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Error sending thumbnail: {e}")
            await update.message.reply_text(
                "❌ Failed to display thumbnail\n\n"
                "The photo may have been deleted from Telegram's servers.\n"
                "Please send a new photo.",
                parse_mode="HTML"
            )
    else:
        text = (
            "❌ No thumbnail saved yet\n\n"
            "📸 Send a photo to save your thumbnail"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="menu_back")]
        ])
        await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_sub(update, context):
        return
    text = (
        "📖 Complete Guide\n\n"
        "<b>Step-by-step instructions:</b>\n\n"
        "<b>1️⃣ Save Your Thumbnail</b>\n"
        "   • Send a high-quality photo\n"
        "   • It saves automatically as your cover\n\n"
        "<b>2️⃣ Apply to Videos</b>\n"
        "   • Send any video\n"
        "   • Cover applies instantly\n\n"
        "<b>3️⃣ Manage & Share</b>\n"
        "   • Your video with cover is ready\n"
        "   • Download and share anywhere\n\n"
        "<b>💡 Pro Tips:</b>\n"
        "✓ High-quality photos work best\n"
        "✓ Update thumbnail anytime\n"
        "✓ Remove old thumbnails easily\n"
        "✓ Keep your covers fresh\n\n"
        "📞 Need help? Contact: /about"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_sub(update, context):
        return
    text = (
        "🤖 About Cover Changer Bot\n\n"
        "<b>Professional video cover bot</b>\n\n"
        "<b>Features:</b>\n"
        "✅ Lightning-fast processing\n"
        "✅ High-quality thumbnail storage\n"
        "✅ Professional video covers\n"
        "✅ Simple interface\n"
        "✅ Instant results\n\n"
        "<b>Tech Stack:</b>\n"
        "⚙️ Powered by Python\n"
        "<b>Support & Contact:</b>\n"
        f"👨‍💻 Developer: @{OWNER_USERNAME or 'support'}\n"
        "📧 For help: /about → Developer\n\n"
        "Thank you for using this bot! 🎬"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_sub(update, context):
        return
    user_id = update.message.from_user.id
    thumb_status = "✅ Saved & Ready" if has_thumbnail(user_id) else "❌ Not saved yet"
    
    text = (
        "⚙️ Your Settings\n\n"
        "<b>Account information:</b>\n"
        f"👤 User ID: <code>{user_id}</code>\n\n"
        "<b>Thumbnail status:</b>\n"
        f"{thumb_status}\n\n"
        "<b>Management options:</b>\n"
        "🖼️ View and manage your thumbnails"
    )
    settings_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🖼️ Thumbnails", callback_data="submenu_thumbnails")],
        [InlineKeyboardButton("📢 ᴀᴅᴅ ʏᴏᴜʀ ᴄʜᴀɴɴᴇʟ", callback_data="channel_set")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_back")]
    ])
    await update.message.reply_text(text, reply_markup=settings_kb, parse_mode="HTML")


async def remover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_sub(update, context):
        return
    
    user_id = update.message.from_user.id
    username = update.message.from_user.username or "Unknown"
    
    if delete_thumbnail(user_id):
        try:
            await log_thumbnail_deleted(
                context.bot,
                LOG_CHANNEL_ID,
                user_id,
                username
            )
            logger.info(f"✅ Delete log sent for user {user_id}")
        except Exception as e:
            logger.error(f"❌ Delete log failed: {e}")
        
        log_data = log_thumbnail_removed(user_id, username)
        log_msg = format_log_message(user_id, username, log_data["action"])
        await send_log(context, log_msg)
        
        return await update.message.reply_text("✅ Thumbnail removed\n\nDeleted successfully. Send a new photo anytime!", reply_to_message_id=update.message.message_id, parse_mode="HTML")
    
    await update.message.reply_text("⚠️ No thumbnail to remove\n\nSend a photo to create one now!", reply_to_message_id=update.message.message_id, parse_mode="HTML")


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_sub(update, context):
        return
    
    user_id = update.message.from_user.id
    username = update.message.from_user.username or "Unknown"
    photo_id = update.message.photo[-1].file_id
    
    try:
        await log_thumb_set(
            context.bot,
            LOG_CHANNEL_ID,
            user_id,
            username
        )
        logger.info(f"✅ Thumbnail log sent for user {user_id}")
    except Exception as e:
        logger.error(f"❌ Thumbnail log failed: {e}")
    
    old_thumbnail = get_thumbnail(user_id)
    is_replace = old_thumbnail is not None
    
    save_thumbnail(user_id, photo_id)
    logger.info(f"✅ Thumbnail saved to MongoDB for user {user_id}")
    
    log_data = log_thumbnail_set(user_id, username, is_replace=is_replace)
    log_msg = format_log_message(user_id, username, log_data["action"])
    await send_log(context, log_msg)
    
    action_text = "updated" if is_replace else "saved"
    await update.message.reply_text("✅ Thumbnail " + action_text + "\n\nReady! Send any video to apply cover", reply_to_message_id=update.message.message_id, parse_mode="HTML")


async def video_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_sub(update, context):
        return
    
    user_id = update.message.from_user.id
    username = update.message.from_user.username or "No Username"
    cover = get_thumbnail(user_id)
    
    if not cover:
        return await update.message.reply_text("❌ No thumbnail found\n\nSend a photo to save thumbnail first", reply_to_message_id=update.message.message_id, parse_mode="HTML")
    
    try:
        await log_video_processed(
            context.bot,
            LOG_CHANNEL_ID,
            user_id,
            username
        )
        logger.info(f"✅ Video log sent for user {user_id}")
    except Exception as e:
        logger.error(f"❌ Video log failed: {e}")
    
    msg = await update.message.reply_text("⏳ Processing video\n\nPlease wait a few seconds", reply_to_message_id=update.message.message_id, parse_mode="HTML")
    
    video = update.message.video.file_id
    original_caption = update.message.caption or ""
    
    url_pattern = r'https?://[^\s]+|t\.me/[^\s]+|telegram\.me/[^\s]+'
    clean_caption = re.sub(url_pattern, '', original_caption).strip()
    clean_caption = ' '.join(clean_caption.split())
    
    saved_channel = get_user_channel(user_id)
    forward_enabled = should_forward_to_channel(user_id)
    
    logger.info(f"📌 User {user_id} - Channel: {saved_channel}, Forward Enabled: {forward_enabled}")
    
    media = InputMediaVideo(
        media=video, 
        caption=clean_caption,
        supports_streaming=True, 
        cover=cover
    )
    
    try:
        await context.bot.edit_message_media(
            chat_id=update.effective_chat.id, 
            message_id=msg.message_id, 
            media=media
        )
        logger.info(f"✅ Video sent to user {user_id} with cover")
        
        if saved_channel and forward_enabled:
            try:
                channel_media = InputMediaVideo(
                    media=video,
                    caption=f" {clean_caption or 'No caption'}",
                    supports_streaming=True,
                    cover=cover
                )
                
                await context.bot.send_media_group(
                    chat_id=saved_channel,
                    media=[channel_media]
                )
                logger.info(f"✅ Video sent to saved channel {saved_channel} with cover")
                
                await update.message.reply_text(
                    f"✅ Video sent to your channel with cover!",
                    parse_mode="HTML"
                )
                
            except Exception as e:
                logger.error(f"❌ Error sending video to channel: {e}")
                
                try:
                    await context.bot.send_video(
                        chat_id=saved_channel,
                        video=video,
                        caption=f"📺 <b>Video from user</b>\n\n"
                                f"👤 User: @{username}\n"
                                f"📝 Caption: {clean_caption or 'No caption'}",
                        supports_streaming=True,
                        parse_mode="HTML"
                    )
                    logger.info(f"✅ Video sent without cover to channel {saved_channel}")
                    await update.message.reply_text(
                        f"⚠️ Video sent but cover couldn't be applied to channel",
                        parse_mode="HTML"
                    )
                except Exception as e2:
                    logger.error(f"❌ Error sending video without cover: {e2}")
                    await update.message.reply_text(
                        f"⚠️ Video couldn't be sent to channel\n\nError: {str(e2)[:100]}",
                        parse_mode="HTML"
                    )
        elif saved_channel and not forward_enabled:
            logger.info(f"ℹ️ Forwarding disabled for user {user_id}, not sending to channel")
            await update.message.reply_text(
                f"ℹ️ Forward OFF\n",
                parse_mode="HTML"
            )
        elif not saved_channel:
            logger.info(f"ℹ️ No channel set for user {user_id}")
        
        if LOG_CHANNEL_ID:
            try:
                log_caption = (
                    f"🎬 <b>Video Processing Completed</b>\n\n"
                    f"👤 User ID: <code>{user_id}</code>\n"
                    f"📌 Username: @{username}\n"
                    f"📝 Caption: {clean_caption or 'No caption'}\n"
                    f"📢 Channel: {saved_channel or 'Not set'}\n"
                    f"📤 Forward: {'✅ Enabled' if forward_enabled else '❌ Disabled'}\n"
                    f"⏰ Time: {update.message.date}"
                )
                await context.bot.send_video(
                    chat_id=LOG_CHANNEL_ID,
                    video=video,
                    caption=log_caption,
                    supports_streaming=True,
                    thumbnail=cover,
                    parse_mode="HTML"
                )
                logger.debug(f"✅ Video logged to channel")
            except Exception as e:
                logger.error(f"❌ Error forwarding video to log channel: {e}")
                
    except Exception as e:
        logger.error(f"❌ Video processing error: {e}")
        await update.message.reply_text(
            f"❌ Processing failed\n\nError: {str(e)[:100]}", 
            parse_mode="HTML"
        )

async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id != OWNER_ID:
        return await update.message.reply_text("❌ You are not authorized.")

    msg = await update.message.reply_text("🔍 Checking for updates from upstream...")

    try:
        success = update_from_upstream()

        if not success:
            await msg.edit_text(
                "❌ <b>Update failed</b>\n\n"
                "Could not fetch updates from upstream.\n"
                "Please check:\n"
                "• upstream_repo is configured\n"
                "• upstream_branch is configured\n"
                "• internet connectivity is active\n\n"
                "Check logs for more details.",
                parse_mode="HTML"
            )
            logger.error(f"Update failed - bot not restarting")
            return

        await msg.edit_text(
            "✅ <b>Update successful!</b>\n\n"
            "🔄 Restarting bot with new changes...\n"
            "<i>Please wait...</i>",
            parse_mode="HTML"
        )
        
        logger.info("✅ Update completed successfully. Restarting bot...")
        await asyncio.sleep(1)
        
        os.execv(sys.executable, [sys.executable] + sys.argv)
        
    except Exception as e:
        logger.error(f"❌ Error during update/restart: {e}")
        await msg.edit_text(
            f"❌ <b>Error during update</b>\n\n"
            f"An unexpected error occurred:\n"
            f"<code>{str(e)[:100]}</code>\n\n"
            f"Check logs for more details.",
            parse_mode="HTML"
        )


"""══════════════════ ADMIN COMMANDS ══════════════════"""

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    
    text = (
        "🛠️ Admin Control Panel\n\n"
        "👑 <b>Welcome Admin</b>\n\n"
        "<b>Available tools:</b>\n\n"
        "📊 <b>Statistics</b> – User analytics\n"
        "⏱️ <b>Status</b> – Bot performance\n"
        "👥 <b>Users</b> – User count\n"
        "🚫 <b>Ban User</b> – Block users\n"
        "✅ <b>Unban</b> – Restore access\n"
        "📢 <b>Broadcast</b> – Send messages\n\n"
        "Select an option:"
    )
    admin_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats"),
         InlineKeyboardButton("⏱️ Status", callback_data="admin_status")],
        [InlineKeyboardButton("👥 Users", callback_data="admin_users"),
         InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban")],
        [InlineKeyboardButton("✅ Unban", callback_data="admin_unban"),
         InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_back")],
    ])
    
    await update.message.reply_text(text, reply_markup=admin_kb, parse_mode="HTML")


async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    
    args = update.message.text.split(None, 2)
    if len(args) < 2:
        return await update.message.reply_text(
            "❌ Usage: /ban <user_id> [reason]\n"
            "📌 Example: /ban 123456789 Spam"
        )
    
    try:
        user_id = int(args[1])
        reason = args[2] if len(args) > 2 else "No reason"
        
        if ban_user(user_id, reason):
            await update.message.reply_text(
                "✅ User " + str(user_id) + " banned\n"
                f"📌 Reason: {reason}",
                parse_mode="HTML"
            )
            
            log_data = log_user_banned(user_id, "User", reason)
            log_msg = format_log_message(user_id, "User", log_data["action"], log_data.get("details", ""))
            await send_log(context, log_msg)
        else:
            await update.message.reply_text("❌ Failed to ban user")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID")
    except Exception as e:
        await update.message.reply_text("❌ Error: " + str(e))


async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    
    args = update.message.text.split()
    if len(args) < 2:
        return await update.message.reply_text(
            "❌ Usage: /unban <user_id>\n"
            "📌 Example: /unban 123456789"
        )
    
    try:
        user_id = int(args[1])
        if unban_user(user_id):
            await update.message.reply_text("✅ User " + str(user_id) + " unbanned")
            
            log_data = log_user_unbanned(user_id, "User")
            log_msg = format_log_message(user_id, "User", log_data["action"])
            await send_log(context, log_msg)
        else:
            await update.message.reply_text("❌ Failed to unban user")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID")
    except Exception as e:
        await update.message.reply_text("❌ Error: " + str(e))


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    
    stats = get_stats()
    text = (
        "📊 Bot Statistics\n\n"
        f"👥 Total users: {stats['total_users']}\n"
        f"🚫 Banned users: {stats['banned_users']}\n"
        f"🖼 Users with thumbnail: {stats['users_with_thumbnail']}"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    
    import psutil
    import time
    
    try:
        uptime_seconds = time.time() - context.bot_data.get('start_time', time.time())
        uptime_hours = int(uptime_seconds // 3600)
        uptime_mins = int((uptime_seconds % 3600) // 60)
        
        cpu_percent = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        ram_percent = ram.percent
        
        text = (
            "⏱️ Bot Status\n\n"
            f"🟢 Status: Online\n"
            f"⏰ Uptime: {uptime_hours}h {uptime_mins}m\n\n"
            f"🖥 System Resources:\n"
            f"🔴 CPU: {cpu_percent}%\n"
            f"🟡 RAM: {ram_percent}% ({ram.used // (1024**2)} MB / {ram.total // (1024**2)} MB)"
        )
        await update.message.reply_text(text, parse_mode="HTML")
    except ImportError:
        text = (
            "⏱️ Bot Status\n\n"
            f"🟢 Status: Online\n\n"
            "⚠️ psutil not installed for system stats\n"
            "📦 Run: pip install psutil"
        )
        await update.message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text("❌ Error: " + str(e))


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    
    args = update.message.text.split(None, 1)
    if len(args) < 2:
        return await update.message.reply_text(
            "❌ Usage: /broadcast <message>\n\n"
            "📌 Example: /broadcast Hello everyone!\n\n"
            "💡 Tips:\n"
            "• Message sent to all users\n"
            "• HTML formatting supported\n"
            "• Emojis are allowed",
            parse_mode="HTML"
        )
    
    message_text = args[1]
    
    confirm_text = (
        "📢 Broadcast Confirmation\n\n"
        f"📝 Message:\n"
        f"{message_text}\n\n"
        f"👥 Total users: {get_total_users()}\n\n"
        "⚠️ Processing... sending now"
    )
    msg = await update.message.reply_text(confirm_text, parse_mode="HTML")
    
    try:
        from database import db
        users_collection = db.get_collection("users")
        all_users = users_collection.find({}, {"user_id": 1})
        
        user_ids = [user["user_id"] for user in all_users if "user_id" in user]
        
        if not user_ids:
            await msg.edit_text(
                "❌ No users found\n\n"
                "💡 Database might be empty",
                parse_mode="HTML"
            )
            return
        
        sent = 0
        failed = 0
        
        for user_id in user_ids:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"📢 <b>Announcement from Admin</b>\n\n{message_text}",
                    parse_mode="HTML"
                )
                sent += 1
            except Exception as e:
                logger.warning(f"Could not send broadcast to user {user_id}: {e}")
                failed += 1
        
        result_text = (
            "✅ Broadcast Completed\n\n"
            f"📤 Sent: {sent}\n"
            f"❌ Failed: {failed}\n"
            f"👥 Total: {sent + failed}\n\n"
            f"📊 Success: {(sent/(sent+failed)*100):.1f}%"
        )
        
        await msg.edit_text(result_text, parse_mode="HTML")
        
        if LOG_CHANNEL_ID:
            log_text = (
                f"📢 <b>Broadcast Sent</b>\n\n"
                f"👤 Admin: @{update.message.from_user.username or update.message.from_user.id}\n"
                f"📤 Messages Sent: {sent}\n"
                f"❌ Failed: {failed}\n"
                f"📝 Message:\n{message_text}"
            )
            await send_log(context, log_text)
        
    except Exception as e:
        await msg.edit_text(
            f"❌ Broadcast failed\n\n"
            f"Error: {str(e)[:100]}\n\n"
            "Check logs for more details.",
            parse_mode="HTML"
        )
        logger.error(f"Broadcast error: {e}", exc_info=True)


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_sub(update, context):
        return
    
    if await handle_channel_id_input(update, context):
        return
    
    await update.message.reply_text("❓ Unknown command. Use /help for assistance.")


"""-----------MAIN FUNCTION-----------"""

async def post_init(app: Application):
    """Bot start/deploy hone par simple log bhejega"""
    logger.info("🚀 Bot is starting up...")
    
    if LOG_CHANNEL_ID:
    try:
        deploy_message = (
            "🚀 <b>Bot is Live</b>\n\n"
            f"📅 Time: {get_ist_datetime_str()}\n"
            f"👑 Owner: @{OWNER_USERNAME or 'Owner'}"
        )
            
            await app.bot.send_message(
                chat_id=LOG_CHANNEL_ID,
                text=deploy_message,
                parse_mode="HTML"
            )
            logger.info("✅ Deploy log sent successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to send deploy log: {e}")
    
    try:
        from telegram import BotCommand
        commands = [
            BotCommand("start", "🏠 Start bot"),
            BotCommand("help", "ℹ️ How to use"),
            BotCommand("about", "🤖 About bot"),
            BotCommand("settings", "⚙️ Settings"),
            BotCommand("remove", "🗑️ Remove thumbnail"),
            BotCommand("showthumbnail", "🖼️ Show thumbnail"),
            BotCommand("admin", "🛠️ Admin panel"),
            BotCommand("ban", "🚫 Ban user"),
            BotCommand("unban", "✅ Unban user"),
            BotCommand("stats", "📊 Bot statistics"),
            BotCommand("status", "⏱️ Bot status"),
            BotCommand("broadcast", "📢 Broadcast message"),
        ]
        await app.bot.set_my_commands(commands)
        logger.info("✅ Bot commands configured successfully")
    except Exception as e:
        logger.error(f"❌ Error setting bot commands: {e}")


def main() -> None:
    app = Application.builder().token(TOKEN).build()

    async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"🔥 ERROR: {context.error}", exc_info=context.error)

    app.add_error_handler(error_handler)
    
    app.post_init = post_init

    register_channel_handlers(app)

    app.add_handler(CommandHandler("start", start, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("help", help_cmd, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("about", about, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("settings", settings, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("remove", remover, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("showthumbnail", show_thumbnail_cmd, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("restart", restart, filters=filters.ChatType.PRIVATE))
    
    app.add_handler(CommandHandler("admin", admin_menu, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("ban", ban_cmd, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("unban", unban_cmd, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("stats", stats_cmd, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("status", status_cmd, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd, filters=filters.ChatType.PRIVATE))

    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, photo_handler))
    app.add_handler(MessageHandler(filters.VIDEO & filters.ChatType.PRIVATE, video_handler))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, text_handler))
    
    app.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("✅ All handlers registered")
    logger.info("🚀 Bot starting...")
    app.run_polling(
        allowed_updates=[
            "message",
            "callback_query",
        ],
        close_loop=False,
    )


if __name__ == "__main__":
    main()
