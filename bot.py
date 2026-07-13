import os
import logging
import asyncio
import re
from datetime import datetime
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

"""═════════════════ LOGGING HELPER ═════════════════"""
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
        if force_banner:
            try:
                if isinstance(force_banner, str) and os.path.isfile(force_banner):
                    photo = InputFile(force_banner)
                else:
                    photo = force_banner
            except Exception:
                photo = force_banner

            await update.message.reply_photo(
                photo=photo,
                caption=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
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
        await update.message.reply_text("❌ ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ")
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
            [InlineKeyboardButton("📢 ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ", url=invite_link)],
            [
                InlineKeyboardButton("✅ ᴠᴇʀɪꜰʏ", callback_data="check_fsub"),
                InlineKeyboardButton("✖️ ᴄʟᴏsᴇ", callback_data="close_banner")
            ]
        ])
        
        prompt = (
            "🔒 ᴄʜᴀɴɴᴇʟ ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ ʀᴇqᴜɪʀᴇᴅ\n\n"
            f"→ ᴊᴏɪɴ ᴏᴜʀ ᴄᴏᴍᴍᴜɴɪᴛʏ ᴄʜᴀɴɴᴇʟ:\n\n"
            f"<b>📢 {channel_name}</b>\n\n"
            "→ ᴇxᴄʟᴜsɪᴠᴇ ᴜᴘᴅᴀᴛᴇs & ᴛɪᴘs\n\n"
            "👇 ᴄʟɪᴄᴋ ʙᴇʟᴏᴡ ᴛᴏ ᴠᴇʀɪꜰʏ 👇"
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




async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    logger.info(f"🔵 CALLBACK | Data: {query.data}")
    
    if not query or not query.data:
        logger.error("❌ Invalid query!")
        return

    user_id = query.from_user.id
    logger.info(f"👤 User ID: {user_id} | Channel ID Config: {FORCE_SUB_CHANNEL_ID}")
    
    if query.data == "check_fsub":
        logger.info(f"🔍 Verify button clicked by user {user_id}")
        
        if not FORCE_SUB_CHANNEL_ID:
            logger.warning("⚠️ FORCE_SUB_CHANNEL_ID not configured")
            await query.answer("✅ Bot configured successfully!", show_alert=False)
            await open_home(update, context)
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
                await query.answer("❌ ᴄʜᴀɴɴᴇʟ ᴄʜᴇᴄᴋ ꜰᴀɪʟᴇᴅ! ᴛʀʏ ᴀɢᴀɪɴ ʟᴀᴛᴇʀ.", show_alert=True)
                return
            
            if member.status in (
                ChatMemberStatus.MEMBER,
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.OWNER
            ):
                verified_users.add(user_id)
                logger.info(f"✅ User {user_id} verified successfully with status {member.status}")
                
                await query.answer("✅ ᴄʜᴀɴɴᴇʟ ᴠᴇʀɪꜰɪᴇᴅ sᴜᴄᴄᴇssꜰᴜʟʟʏ!", show_alert=False)
                
                try:
                    await query.message.delete()
                    logger.info(f"🗑️ Verification message deleted")
                except Exception as del_error:
                    logger.warning(f"Could not delete message: {del_error}")
                
                logger.info(f"🏠 Showing home screen for user {user_id}")
                await open_home(update, context)
                return
            
            logger.warning(f"⚠️ User {user_id} not a member. Status: {member.status}")
            await query.answer("❌ ᴊᴏɪɴ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ꜰɪʀsᴛ!\n\nᴘʟᴇᴀsᴇ ᴊᴏɪɴ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ᴀɴᴅ ᴛʜᴇɴ ᴄʟɪᴄᴋ ᴠᴇʀɪꜰʏ.", show_alert=True)
            return
            
        except Exception as e:
            logger.error(f"❌ Verification error: {type(e).__name__}: {e}", exc_info=True)
            await query.answer("❌ ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ ꜰᴀɪʟᴇᴅ!\n\nᴘʟᴇᴀsᴇ ᴍᴀᴋᴇ sᴜʀᴇ ʏᴏᴜ ᴊᴏɪɴᴇᴅ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ꜰɪʀsᴛ.", show_alert=True)
            return
    
    if query.data == "close_banner":
        logger.info(f"❌ User {user_id} closed banner")
        try:
            await query.answer()
            await query.message.delete()
        except Exception as e:
            logger.error(f"Close error: {e}")
            try:
                await query.message.edit_text("Closed", parse_mode="HTML")
            except Exception:
                pass
        return
    
    if query.data == "admin_stats":
        if not is_admin(user_id):
            await query.answer("❌ Unauthorized", show_alert=True)
            return
        await query.answer()
        stats = get_stats()
        text = (
            "📊 ʙᴏᴛ sᴛᴀᴛɪsᴛɪᴄs\n\n"
            f"👥 ᴛᴏᴛᴀʟ ᴜsᴇʀs: {stats['total_users']}\n"
            f"🚫 ʙᴀɴɴᴇᴅ ᴜsᴇʀs: {stats['banned_users']}\n"
            f"🖼 ᴡɪᴛʜ ᴛʜᴜᴍʙɴᴀɪʟ: {stats['users_with_thumbnail']}"
        )
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
        ])
        try:
            msg = query.message
            if getattr(msg, "photo", None):
                await msg.edit_caption(text, reply_markup=back_kb, parse_mode="HTML")
            else:
                await msg.edit_text(text, reply_markup=back_kb, parse_mode="HTML")
        except Exception:
            pass
        return
    
    if query.data == "admin_users":
        if not is_admin(user_id):
            await query.answer("❌ Unauthorized", show_alert=True)
            return
        await query.answer()
        stats = get_stats()
        total_users = stats['total_users']
        banned_users = stats['banned_users']
        active_users = total_users - banned_users
        
        text = (
            "👥 ᴜsᴇʀ ᴍᴀɴᴀɢᴇᴍᴇɴᴛ\n\n"
            f"📊 ᴛᴏᴛᴀʟ ᴜsᴇʀs: {total_users}\n"
            f"✅ ᴀᴄᴛɪᴠᴇ ᴜsᴇʀs: {active_users}\n"
            f"🚫 ʙᴀɴɴᴇᴅ ᴜsᴇʀs: {banned_users}\n\n"
            f"📈 ʙᴀɴ ʀᴀᴛᴇ: {(banned_users/total_users*100):.1f}%"
        )
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
        ])
        try:
            msg = query.message
            if getattr(msg, "photo", None):
                await msg.edit_caption(text, reply_markup=back_kb, parse_mode="HTML")
            else:
                await msg.edit_text(text, reply_markup=back_kb, parse_mode="HTML")
        except Exception:
            pass
        return
    
    if query.data == "admin_status":
        if not is_admin(user_id):
            await query.answer("❌ Unauthorized", show_alert=True)
            return
        await query.answer()
        try:
            import psutil
            import time
            cpu_percent = psutil.cpu_percent(interval=1)
            ram = psutil.virtual_memory()
            text = (
                "⏱️ ʙᴏᴛ sᴛᴀᴛᴜs\n\n"
                f"🟢 sᴛᴀᴛᴜs: ᴏɴʟɪɴᴇ\n\n"
                f"🖥 sʏsᴛᴇᴍ ʀᴇsᴏᴜʀᴄᴇs:\n"
                f"ᴄᴘᴜ: {cpu_percent}%\n"
                f"ʀᴀᴍ: {ram.percent}%"
            )
        except ImportError:
            text = "⏱️ <b>Bot Status</b>\n\n🟢 Status: <b>Online</b>"
        
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
        ])
        try:
            msg = query.message
            if getattr(msg, "photo", None):
                await msg.edit_caption(text, reply_markup=back_kb, parse_mode="HTML")
            else:
                await msg.edit_text(text, reply_markup=back_kb, parse_mode="HTML")
        except Exception:
            pass
        return
    
    if query.data == "admin_ban":
        if not is_admin(user_id):
            await query.answer("❌ Unauthorized", show_alert=True)
            return
        await query.answer()
        text = "🚫 ʙᴀɴ ᴜsᴇʀ\n\nꜱᴇɴᴅ ᴜsᴇʀ ɪᴅ ᴛᴏ ʙᴀɴ ᴏʀ /ʙᴀɴ ᴜsᴇʀɪᴅ ʀᴇᴀsᴏɴ"
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
        ])
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=back_kb, parse_mode="HTML")
        return
    
    if query.data == "admin_unban":
        if not is_admin(user_id):
            await query.answer("❌ Unauthorized", show_alert=True)
            return
        await query.answer()
        text = "✅ ᴜɴʙᴀɴ ᴜsᴇʀ\n\nꜱᴇɴᴅ ᴜsᴇʀ ɪᴅ ᴛᴏ ᴜɴʙᴀɴ ᴏʀ /ᴜɴʙᴀɴ ᴜsᴇʀɪᴅ"
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
        ])
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=back_kb, parse_mode="HTML")
        return
    
    if query.data == "admin_broadcast":
        if not is_admin(user_id):
            await query.answer("❌ Unauthorized", show_alert=True)
            return
        await query.answer()
        text = "📢 ʙʀᴏᴀᴅᴄᴀsᴛ ᴍᴇssᴀɢᴇ\n\nꜱᴇɴᴅ ᴍᴇssᴀɢᴇ ᴛᴏ ʙʀᴏᴀᴅᴄᴀsᴛ ᴛᴏ ᴀʟʟ ᴜsᴇʀs"
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
        ])
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=back_kb, parse_mode="HTML")
        return
    
    if query.data == "admin_back":
        if not is_admin(user_id):
            await query.answer("❌ Unauthorized", show_alert=True)
            return
        await query.answer()
        text = (
            "🛡️ ᴀᴅᴍɪɴ ᴄᴏɴᴛʀᴏʟ ᴘᴀɴᴇʟ\n\n"
            "<b>Management Options:</b>\n\n"
            "📊 <b>Statistics</b> – View user analytics\n"
            "⏱️ <b>Status</b> – Bot performance\n"
            "🚫 <b>Ban User</b> – Block users\n"
            "✅ <b>Unban</b> – Restore access"
        )
        admin_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 sᴛᴀᴛɪsᴛɪᴄs", callback_data="admin_stats"),
             InlineKeyboardButton("⏱️ sᴛᴀᴛᴜs", callback_data="admin_status")],
            [InlineKeyboardButton("🚫 ʙᴀɴ ᴜsᴇʀ", callback_data="admin_ban"),
             InlineKeyboardButton("✅ ᴜɴʙᴀɴ ᴜsᴇʀ", callback_data="admin_unban")],
            [InlineKeyboardButton("📢 ʙʀᴏᴀᴅᴄᴀsᴛ", callback_data="admin_broadcast"),
             InlineKeyboardButton("⬅️ ʙᴀᴄᴋ", callback_data="menu_back")],
        ])
        try:
            msg = query.message
            if getattr(msg, "photo", None):
                await msg.edit_caption(text, reply_markup=admin_kb, parse_mode="HTML")
            else:
                await msg.edit_text(text, reply_markup=admin_kb, parse_mode="HTML")
        except Exception:
            pass
        return

    if query.data == "contact_owner":
        logger.info(f"📞 Contact owner for user {user_id}")
        try:
            await query.answer()
            if OWNER_USERNAME:
                await context.bot.send_message(chat_id=query.message.chat_id, text=f"Contact owner: https://t.me/{OWNER_USERNAME}")
            else:
                await context.bot.send_message(chat_id=query.message.chat_id, text="Owner contact not configured.")
        except Exception as e:
            logger.error(f"Contact error: {e}")
        return

    if query.data.startswith("menu_"):
        key = query.data.split("menu_")[1]
        logger.info(f"📋 Menu callback: {key} for user {user_id}")
        await query.answer()
        
        if key == "back":
            text = (
                "👋 ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ɪɴsᴛᴀɴᴛ ᴄᴏᴠᴇʀ ʙᴏᴛ\n\n"
                "<b>Quick Start Guide:</b>\n\n"
                "📸 <b>Step 1:</b> Send a photo as thumbnail\n"
                "🎥 <b>Step 2:</b> Send a video to apply cover\n\n"
                "<b>Navigation:</b>\n"
                "❓ /help – Usage guide\n"
                "⚙️ /settings – Manage thumbnails\n"
                "ℹ️ /about – Bot information"
            )
            kb_rows = [
                [InlineKeyboardButton("❓ ʜᴇʟᴘ", callback_data="menu_help"),
                 InlineKeyboardButton("ℹ️ ᴀʙᴏᴜᴛ", callback_data="menu_about")],
                [InlineKeyboardButton("⚙️ sᴇᴛᴛɪɴɢs", callback_data="menu_settings"),
                 InlineKeyboardButton("👨‍💻 ᴅᴇᴠᴇʟᴏᴘᴇʀ", callback_data="menu_developer")],
            ]
            kb = InlineKeyboardMarkup(kb_rows)
            try:
                msg = query.message
                if getattr(msg, "photo", None):
                    await msg.edit_caption(text, reply_markup=kb, parse_mode="HTML")
                else:
                    await msg.edit_text(text, reply_markup=kb, parse_mode="HTML")
            except Exception as e:
                logger.debug(f"Back button message edit error: {e}")
            return
        
        try:
            if key == "help":
                text = (
                    "ℹ️ ʜᴇʟᴘ ᴍᴇɴᴜ\n\n"
                    "<b>ʜᴏᴡ ᴛᴏ ᴜsᴇ:</b>\n\n"
                    "<b>1️⃣ ᴜᴘʟᴏᴀᴅ ᴛʜᴜᴍʙɴᴀɪʟ</b>\n"
                    "   • sᴇɴᴅ ᴀɴʏ ᴘʜᴏᴛᴏ\n"
                    "   • ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ sᴀᴠᴇᴅ ᴛᴏ ᴘʀᴏꜰɪʟᴇ\n\n"
                    "<b>2️⃣ ᴀᴘᴘʟʏ ᴛᴏ ᴠɪᴅᴇᴏ</b>\n"
                    "   • sᴇɴᴅ ᴀ ᴠɪᴅᴇᴏ ꜰɪʟᴇ\n"
                    "   • ᴛʜᴜᴍʙɴᴀɪʟ ᴀᴘᴘʟɪᴇᴅ ɪɴsᴛᴀɴᴛʟʏ\n\n"
                    "<b>ᴀᴅᴅɪᴛɪᴏɴᴀʟ ᴄᴏᴍᴍᴀɴᴅs:</b>\n"
                    "/remove – ᴅᴇʟᴇᴛᴇ sᴀᴠᴇᴅ ᴛʜᴜᴍʙɴᴀɪʟ\n"
                    "/showthumbnail – ᴠɪᴇᴡ sᴀᴠᴇᴅ ᴛʜᴜᴍʙɴᴀɪʟ\n"
                    "/settings – ᴠɪᴇᴡ & ᴍᴀɴᴀɢᴇ sᴇᴛᴛɪɴɢs\n"
                    "/about – ɪɴꜰᴏʀᴍᴀᴛɪᴏɴ ᴀʙᴏᴜᴛ ʙᴏᴛ"
                )
            elif key == "about":
                text = (
                    "🤖 ɪɴsᴛᴀɴᴛ ᴠɪᴅᴇᴏ ᴄᴏᴠᴇʀ ʙᴏᴛ\n\n"
                    "<b>ᴘʀᴇᴍɪᴜᴍ ꜰᴇᴀᴛᴜʀᴇs:</b>\n\n"
                    "✅ <b>ᴏɴᴇ-ᴄʟɪᴄᴋ ᴛʜᴜᴍʙɴᴀɪʟ</b>\n"
                    "   ᴜᴘʟᴏᴀᴅ ᴏɴᴄᴇ, ᴀᴘᴘʟʏ ᴛᴏ ᴜɴʟɪᴍɪᴛᴇᴅ ᴠɪᴅᴇᴏs\n\n"
                    "✅ <b>ɪɴsᴛᴀɴᴛ ᴘʀᴏᴄᴇssɪɴɢ</b>\n"
                    "   ꜰᴀsᴛ ᴄᴏᴠᴇʀ ᴀᴘᴘʟɪᴄᴀᴛɪᴏɴ\n\n"
                    "✅ <b>sᴇᴄᴜʀᴇ & ᴘʀɪᴠᴀᴛᴇ</b>\n"
                    "   ʏᴏᴜʀ ᴅᴀᴛᴀ sᴛᴀʏs ᴇɴᴄʀʏᴘᴛᴇᴅ\n\n"
                    "<b>ᴛᴇᴄʜɴᴏʟᴏɢʏ:</b>\n"
                    "⚙️ ᴀᴅᴠᴀɴᴄᴇᴅ ᴘʏᴛʜᴏɴ ᴀᴘɪ\n"
                    "🔐 sᴇᴄᴜʀᴇ ᴛᴇʟᴇɢʀᴀᴍ ɪɴᴛᴇɢʀᴀᴛɪᴏɴ"
                )
            elif key == "settings":
                uid = query.from_user.id
                text = (
                    "⚙️ sᴇᴛᴛɪɴɢs\n\n"
                    "<b>ᴍᴀɴᴀɢᴇ ʏᴏᴜʀ ᴄᴏɴᴛᴇɴᴛ:</b>\n\n"
                    "🖼️ <b>ᴛʜᴜᴍʙɴᴀɪʟ ᴍᴀɴᴀɢᴇᴍᴇɴᴛ</b>\n"
                    "   • ᴠɪᴇᴡ ᴄᴜʀʀᴇɴᴛ ᴛʜᴜᴍʙɴᴀɪʟ\n"
                    "   • ᴅᴇʟᴇᴛᴇ & ᴜᴘʟᴏᴀᴅ ɴᴇᴡ\n\n"
                    "sᴇʟᴇᴄᴛ ᴏᴘᴛɪᴏɴ ᴛᴏ ᴄᴏɴᴛɪɴᴜᴇ:"
                )
                settings_kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🖼 ᴛʜᴜᴍʙɴᴀɪʟs", callback_data="submenu_thumbnails")],
                    [InlineKeyboardButton("⬅️ ʙᴀᴄᴋ", callback_data="menu_back")]
                ])
                try:
                    msg = query.message
                    if getattr(msg, "photo", None):
                        await msg.edit_caption(text, reply_markup=settings_kb, parse_mode="HTML")
                    else:
                        await msg.edit_text(text, reply_markup=settings_kb, parse_mode="HTML")
                except Exception as e:
                    logger.debug(f"Settings menu edit error: {e}")
                return
            elif key == "developer":
                dev_contact = f"https://t.me/{OWNER_USERNAME}" if OWNER_USERNAME else f"tg://user?id={OWNER_ID}"
                text = (
                    "👨‍💻 <b>ᴅᴇᴠᴇʟᴏᴘᴇʀ</b>\n\n"
                    f"ᴄᴏɴᴛᴀᴄᴛ: {dev_contact}\n"
                    "ɪꜰ ʏᴏᴜ ɴᴇᴇᴅ ʜᴇʟᴘ, ʀᴇᴀᴄʜ ᴏᴜᴛ ᴛᴏ ᴛʜᴇ ᴅᴇᴠᴇʟᴏᴘᴇʀ."
                )
            else:
                text = (
                    "ℹ️ <b>ɪɴꜰᴏ</b>\n\n"
                    "ɴᴏ ɪɴꜰᴏʀᴍᴀᴛɪᴏɴ ᴀᴠᴀɪʟᴀʙʟᴇ ꜰᴏʀ ᴛʜɪs ᴍᴇɴᴜ."
                )
            
            if key != "settings":
                back_kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back", callback_data="menu_back")]
                ])
                
                try:
                    msg = query.message
                    if getattr(msg, "photo", None):
                        await msg.edit_caption(text, reply_markup=back_kb, parse_mode="HTML")
                    else:
                        await msg.edit_text(text, reply_markup=back_kb, parse_mode="HTML")
                except Exception as e:
                    logger.debug(f"Menu edit error: {e}")
                    await context.bot.send_message(chat_id=query.message.chat.id, text=text, reply_markup=back_kb, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Menu error: {e}", exc_info=True)
        return
    
    if query.data == "submenu_thumbnails":
        await query.answer()
        uid = query.from_user.id
        thumb_status = "✅ sᴀᴠᴇᴅ" if has_thumbnail(uid) else "❌ ɴᴏᴛ sᴀᴠᴇᴅ"
        text = (
            "🖼️ <b>ᴛʜᴜᴍʙɴᴀɪʟ ᴍᴀɴᴀɢᴇʀ</b>\n\n"
            f"<b>ᴄᴜʀʀᴇɴᴛ sᴛᴀᴛᴜs:</b> {thumb_status}\n\n"
            "📚 <b>ᴀᴠᴀɪʟᴀʙʟᴇ ᴀᴄᴛɪᴏɴs:</b>\n\n"
            "💾 sᴀᴠᴇ ᴛʜᴜᴍʙɴᴀɪʟ\n"
            "ᴜᴘʟᴏᴀᴅ ᴀ ɴᴇᴡ ᴘʜᴏᴛᴏ ᴀs ʏᴏᴜʀ ᴠɪᴅᴇᴏ ᴄᴏᴠᴇʀ\n\n"
            "👁️ sʜᴏᴡ ᴛʜᴜᴍʙɴᴀɪʟ\n"
            "ᴘʀᴇᴠɪᴇᴡ ʏᴏᴜʀ ᴄᴜʀʀᴇɴᴛʟʏ sᴀᴠᴇᴅ ᴛʜᴜᴍʙɴᴀɪʟ\n\n"
            "🗑️ ᴅᴇʟᴇᴛᴇ ᴛʜᴜᴍʙɴᴀɪʟ\n"
            "ʀᴇᴍᴏᴠᴇ ʏᴏᴜʀ sᴀᴠᴇᴅ ᴛʜᴜᴍʙɴᴀɪʟ"
        )
        thumb_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💾 sᴀᴠᴇ ᴛʜᴜᴍʙɴᴀɪʟ", callback_data="thumb_save_info"),
             InlineKeyboardButton("👁️ sʜᴏᴡ ᴛʜᴜᴍʙɴᴀɪʟ", callback_data="thumb_show")],
            [InlineKeyboardButton("🗑️ ᴅᴇʟᴇᴛᴇ ᴛʜᴜᴍʙɴᴀɪʟ", callback_data="thumb_delete"),
             InlineKeyboardButton("⬅️ ʙᴀᴄᴋ", callback_data="menu_settings")]
        ])
        try:
            msg = query.message
            if getattr(msg, "photo", None):
                await msg.edit_caption(text, reply_markup=thumb_kb, parse_mode="HTML")
            else:
                await msg.edit_text(text, reply_markup=thumb_kb, parse_mode="HTML")
        except Exception as e:
            logger.debug(f"Thumbnails submenu edit error: {e}")
        return
    
    if query.data == "thumb_save_info":
        await query.answer()
        text = (
            "💾 sᴀᴠᴇ ʏᴏᴜʀ ᴛʜᴜᴍʙɴᴀɪʟ\n\n"
            "📸 ʜᴏᴡ ɪᴛ ᴡᴏʀᴋs:\n\n"
            "<b>sᴛᴇᴘ 1️⃣:</b> sᴇɴᴅ ᴀ ᴘʜᴏᴛᴏ\n"
            "→ ɢᴏ ʙᴀᴄᴋ ᴀɴᴅ sᴇɴᴅ ᴀɴʏ ᴘʜᴏᴛᴏ\n"
            "→ ᴛʜɪs ᴡɪʟʟ ʙᴇ ʏᴏᴜʀ ᴄᴏᴠᴇʀ\n\n"
            "<b>sᴛᴇᴘ 2️⃣:</b> ᴀᴜᴛᴏᴍᴀᴛɪᴄ sᴀᴠᴇ\n"
            "→ ᴛʜᴜᴍʙɴᴀɪʟ sᴀᴠᴇs ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ\n"
            "→ ʀᴇᴘʟᴀᴄᴇ ᴀɴʏᴛɪᴍᴇ\n\n"
            "<b>sᴛᴇᴘ 3️⃣:</b> ʀᴇᴀᴅʏ ᴛᴏ ᴜsᴇ\n"
            "→ sᴇɴᴅ ᴀɴʏ ᴠɪᴅᴇᴏ\n"
            "→ ᴄᴏᴠᴇʀ ᴀᴘᴘʟɪᴇs ɪɴsᴛᴀɴᴛʟʏ\n\n"
            "💡 ᴛɪᴘs:\n"
            "• ʜɪɢʜ-ʀᴇsᴏʟᴜᴛɪᴏɴ ɪᴍᴀɢᴇs\n"
            "• sqᴜᴀʀᴇ ꜰᴏʀᴍᴀᴛ 1:1\n"
            "• ᴍᴀx 5ᴍʙ ꜰɪʟᴇ\n\n"
            "📸 ʀᴇᴀᴅʏ? sᴇɴᴅ ʏᴏᴜʀ ᴘʜᴏᴛᴏ ɴᴏᴡ"
        )
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="submenu_thumbnails")]
        ])
        try:
            msg = query.message
            if getattr(msg, "photo", None):
                await msg.edit_caption(text, reply_markup=back_kb, parse_mode="HTML")
            else:
                await msg.edit_text(text, reply_markup=back_kb, parse_mode="HTML")
        except Exception:
            pass
        return
    
    if query.data == "thumb_show":
        await query.answer()
        photo_id = get_thumbnail(user_id)
        if photo_id:
            text = "👁️ ʏᴏᴜʀ ᴄᴜʀʀᴇɴᴛ ᴛʜᴜᴍʙɴᴀɪʟ\n\nᴛʜɪs ᴘʜᴏᴛᴏ ᴡɪʟʟ ʙᴇ ᴀᴘᴘʟɪᴇᴅ ᴛᴏ ʏᴏᴜʀ ᴠɪᴅᴇᴏs\nᴄʜᴀɴɢᴇ ɪᴛ ᴀɴʏᴛɪᴍᴇ ʙʏ ᴜᴘʟᴏᴀᴅɪɴɢ ᴀ ɴᴇᴡ ᴏɴᴇ"
            back_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back", callback_data="submenu_thumbnails")]
            ])
            try:
                await query.message.delete()
            except Exception:
                pass
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
        else:
            text = "❌ ɴᴏ ᴛʜᴜᴍʙɴᴀɪʟ sᴀᴠᴇᴅ ʏᴇᴛ\n\nꜱᴇɴᴅ ᴀ ᴘʜᴏᴛᴏ ᴛᴏ ᴄʀᴇᴀᴛᴇ ᴏɴᴇ ɴᴏᴡ"
            back_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back", callback_data="submenu_thumbnails")]
            ])
            try:
                msg = query.message
                if getattr(msg, "photo", None):
                    await msg.edit_caption(text, reply_markup=back_kb, parse_mode="HTML")
                else:
                    await msg.edit_text(text, reply_markup=back_kb, parse_mode="HTML")
            except Exception:
                pass
        return
    
    if query.data == "thumb_delete":
        await query.answer()
        if delete_thumbnail(user_id):
            text = "✅ ᴛʜᴜᴍʙɴᴀɪʟ ᴅᴇʟᴇᴛᴇᴅ\n\nʀᴇᴍᴏᴠᴇᴅ ꜰʀᴏᴍ sʏsᴛᴇᴍ. ᴜᴘʟᴏᴀᴅ ɴᴇᴡ ᴏɴᴇ ᴀɴʏᴛɪᴍᴇ"
        else:
            text = "⚠️ ɴᴏ ᴛʜᴜᴍʙɴᴀɪʟ ꜰᴏᴜɴᴅ\n\nꜱᴇɴᴅ ᴀ ᴘʜᴏᴛᴏ ᴛᴏ ᴄʀᴇᴀᴛᴇ ᴏɴᴇ"
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="submenu_thumbnails")]
        ])
        try:
            msg = query.message
            if getattr(msg, "photo", None):
                await msg.edit_caption(text, reply_markup=back_kb, parse_mode="HTML")
            else:
                await msg.edit_text(text, reply_markup=back_kb, parse_mode="HTML")
        except Exception:
            pass
        return
    
    logger.warning(f"⚠️ Unknown callback: {query.data}")
    try:
        await query.answer("Unknown action", show_alert=False)
    except Exception:
        pass


"""---------------------- Menus--------------------- """

async def open_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
    "<b>Welcome to Cover Changer Bot ✅</b>\n\n"
    "• Send/forward Image → Save cover\n"
    "• Send/forward video → Apply cover\n"
    "• /showthumbnail → View cover\n\n"
    "📊 The bot never offline unless maintenance or admin intervention."
)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❓ ʜᴇʟᴘ", callback_data="menu_help"),
         InlineKeyboardButton("ℹ️ ᴀʙᴏᴜᴛ", callback_data="menu_about")],
        [InlineKeyboardButton("⚙️ sᴇᴛᴛɪɴɢs", callback_data="menu_settings"),
         InlineKeyboardButton("👨‍💻 ᴅᴇᴠᴇʟᴏᴘᴇʀ", callback_data="menu_developer")],
    ])
    
    home_banner = HOME_MENU_BANNER_URL

    if update.callback_query:
        msg = update.callback_query.message
        try:
            try:
                await msg.delete()
            except Exception:
                pass
            
            if home_banner:
                try:
                    if isinstance(home_banner, str) and os.path.isfile(home_banner):
                        photo = InputFile(home_banner)
                    else:
                        photo = home_banner
                    
                    await context.bot.send_photo(
                        chat_id=msg.chat.id,
                        photo=photo,
                        caption=text,
                        reply_markup=kb,
                        parse_mode="HTML"
                    )
                except Exception as banner_err:
                    logger.warning(f"Could not send home banner: {banner_err}")
                    await context.bot.send_message(
                        chat_id=msg.chat.id,
                        text=text,
                        reply_markup=kb,
                        parse_mode="HTML"
                    )
            else:
                await context.bot.send_message(
                    chat_id=msg.chat.id,
                    text=text,
                    reply_markup=kb,
                    parse_mode="HTML"
                )
        except Exception as e:
            logger.warning(f"Error sending home menu: {e}")
            try:
                await context.bot.send_message(
                    chat_id=msg.chat.id,
                    text=text,
                    reply_markup=kb,
                    parse_mode="HTML"
                )
            except Exception:
                pass
    else:
        if home_banner:
            try:
                if isinstance(home_banner, str) and os.path.isfile(home_banner):
                    await update.message.reply_photo(photo=InputFile(home_banner), caption=text, reply_markup=kb, parse_mode="HTML")
                else:
                    await update.message.reply_photo(photo=home_banner, caption=text, reply_markup=kb, parse_mode="HTML")
                return
            except Exception as e:
                logger.warning(f"Could not send home banner: {e}")
        await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    first_name = update.effective_user.first_name or "User"
    
    # ✅ CHECK: KYA USER PEHLE SE EXISTS KARTA HAI?
    # Agar user ka thumbnail hai toh existing user hai
    user_check = get_thumbnail(user_id)
    is_new_user = user_check is None  # Agar None hai toh naya user hai
    
    if is_new_user:
        # ✅ SIRF NAYE USER KA LOG BHEJEIN
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
        
        # Database mein log karein
        log_data = log_new_user(user_id, username, first_name)
        log_msg = format_log_message(user_id, username, log_data["action"], log_data.get("details", ""))
        await send_log(context, log_msg)
    else:
        # ✅ EXISTING USER - KOI LOG NAHI BHEJNA
        logger.info(f"👋 Returning user: {user_id} (no log sent)")
    
    # Check if user is banned
    if is_user_banned(user_id):
        await update.message.reply_text("🚫 ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ\n\nʏᴏᴜʀ ᴀᴄᴄᴏᴜɴᴛ ʜᴀs ʙᴇᴇɴ ʀᴇsᴛʀɪᴄᴛᴇᴅ. ᴄᴏɴᴛᴀᴄᴛ sᴜᴘᴘᴏʀᴛ.", parse_mode="HTML")
        return
    
    # Check force-sub first
    if not await check_force_sub(update, context):
        logger.warning(f"❌ User {user_id} blocked by force-sub check")
        return
    
    # Welcome message
    text = (
        "<b>Welcome to Cover Changer Bot ✅</b>\n\n"
        "• Send/forward Image → Save cover\n"
        "• Send/forward video → Apply cover\n"
        "• /showthumbnail → View cover\n\n"
        "📊 The bot never offline unless maintenance or admin intervention."
    )
    
    # Build keyboard
    kb_rows = [
        [InlineKeyboardButton("❓ ʜᴇʟᴘ", callback_data="menu_help"),
         InlineKeyboardButton("ℹ️ ᴀʙᴏᴜᴛ", callback_data="menu_about")],
        [InlineKeyboardButton("⚙️ sᴇᴛᴛɪɴɢs", callback_data="menu_settings"),
         InlineKeyboardButton("👨‍💻 ᴅᴇᴠᴇʟᴏᴘᴇʀ", callback_data="menu_developer")],
    ]
    
    if is_admin(user_id):
        kb_rows.append([InlineKeyboardButton("🛡️ ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ", callback_data="admin_back")])
    
    kb = InlineKeyboardMarkup(kb_rows)
    banner = HOME_MENU_BANNER_URL
    
    # Send welcome message with banner
    if update.callback_query:
        msg = update.callback_query.message
        if banner:
            try:
                if isinstance(banner, str) and os.path.isfile(banner):
                    photo = InputFile(banner)
                else:
                    photo = banner
                if getattr(msg, "photo", None):
                    await msg.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
                else:
                    try:
                        await msg.delete()
                    except Exception:
                        pass
                    await msg.chat.send_photo(photo=photo, caption=text, reply_markup=kb, parse_mode="HTML")
            except Exception:
                await msg.edit_text(text, reply_markup=kb, parse_mode="HTML")
        else:
            await msg.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        if banner:
            try:
                if isinstance(banner, str) and os.path.isfile(banner):
                    await update.message.reply_photo(photo=InputFile(banner), caption=text, reply_markup=kb, parse_mode="HTML")
                else:
                    await update.message.reply_photo(photo=banner, caption=text, reply_markup=kb, parse_mode="HTML")
                return
            except Exception:
                pass
        await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")


async def show_thumbnail_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_sub(update, context):
        return
    
    user_id = update.message.from_user.id
    photo_id = get_thumbnail(user_id)
    
    if photo_id:
        text = (
            "🖼️ <b>ʏᴏᴜʀ sᴀᴠᴇᴅ ᴛʜᴜᴍʙɴᴀɪʟ</b>\n\n"
            "ᴛʜɪs ᴘʜᴏᴛᴏ ᴡɪʟʟ ʙᴇ ᴀᴘᴘʟɪᴇᴅ ᴛᴏ ʏᴏᴜʀ ᴠɪᴅᴇᴏs\n"
            "ᴄʜᴀɴɢᴇ ɪᴛ ᴀɴʏᴛɪᴍᴇ ʙʏ ᴜᴘʟᴏᴀᴅɪɴɢ ᴀ ɴᴇᴡ ᴏɴᴇ"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑️ ᴅᴇʟᴇᴛᴇ ᴛʜᴜᴍʙɴᴀɪʟ", callback_data="thumb_delete")],
            [InlineKeyboardButton("⬅️ ʙᴀᴄᴋ", callback_data="menu_back")]
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
                "❌ ꜰᴀɪʟᴇᴅ ᴛᴏ ᴅɪsᴘʟᴀʏ ᴛʜᴜᴍʙɴᴀɪʟ\n\n"
                "ᴛʜᴇ ᴘʜᴏᴛᴏ ᴍᴀʏ ʜᴀᴠᴇ ʙᴇᴇɴ ᴅᴇʟᴇᴛᴇᴅ ꜰʀᴏᴍ ᴛᴇʟᴇɢʀᴀᴍ's sᴇʀᴠᴇʀs.\n"
                "ᴘʟᴇᴀsᴇ ᴜᴘʟᴏᴀᴅ ᴀ ɴᴇᴡ ᴏɴᴇ.",
                parse_mode="HTML"
            )
    else:
        text = (
            "❌ ɴᴏ ᴛʜᴜᴍʙɴᴀɪʟ sᴀᴠᴇᴅ ʏᴇᴛ\n\n"
            "📸 sᴇɴᴅ ᴀ ᴘʜᴏᴛᴏ ᴛᴏ sᴀᴠᴇ ʏᴏᴜʀ ᴛʜᴜᴍʙɴᴀɪʟ"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ ʙᴀᴄᴋ", callback_data="menu_back")]
        ])
        await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_sub(update, context):
        return
    text = (
        "📖 ᴄᴏᴍᴘʟᴇᴛᴇ ɢᴜɪᴅᴇ\n\n"
        "<b>sᴛᴇᴘ-ʙʏ-sᴛᴇᴘ ɪɴsᴛʀᴜᴄᴛɪᴏɴs:</b>\n\n"
        "<b>1️⃣ ᴜᴘʟᴏᴀᴅ ʏᴏᴜʀ ᴛʜᴜᴍʙɴᴀɪʟ</b>\n"
        "   • sᴇɴᴅ ᴀ ʜɪɢʜ-qᴜᴀʟɪᴛʏ ᴘʜᴏᴛᴏ\n"
        "   • ɪᴛ sᴀᴠᴇs ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ ᴀs ʏᴏᴜʀ ᴄᴏᴠᴇʀ\n\n"
        "<b>2️⃣ ᴀᴘᴘʟʏ ᴛᴏ ᴠɪᴅᴇᴏs</b>\n"
        "   • sᴇɴᴅ ᴀɴʏ ᴠɪᴅᴇᴏ ꜰɪʟᴇ\n"
        "   • ᴄᴏᴠᴇʀ ᴀᴘᴘʟɪᴇs ɪɴsᴛᴀɴᴛʟʏ\n\n"
        "<b>3️⃣ ᴅᴏᴡɴʟᴏᴀᴅ & sʜᴀʀᴇ</b>\n"
        "   • ʏᴏᴜʀ ᴠɪᴅᴇᴏ ᴡɪᴛʜ ᴄᴏᴠᴇʀ ɪs ʀᴇᴀᴅʏ\n"
        "   • ᴅᴏᴡɴʟᴏᴀᴅ ᴀɴᴅ sʜᴀʀᴇ ᴀɴʏᴡʜᴇʀᴇ\n\n"
        "<b>💡 ᴘʀᴏ ᴛɪᴘs:</b>\n"
        "✓ ʜɪɢʜ-qᴜᴀʟɪᴛʏ ᴘʜᴏᴛᴏs ᴡᴏʀᴋ ʙᴇsᴛ\n"
        "✓ ᴜᴘᴅᴀᴛᴇ ᴛʜᴜᴍʙɴᴀɪʟ ᴀɴʏᴛɪᴍᴇ\n"
        "✓ ʀᴇᴍᴏᴠᴇ ᴏʟᴅ ᴄᴏᴠᴇʀs ꜰʀᴏᴍ sᴇᴛᴛɪɴɢs\n\n"
        "📞 ɴᴇᴇᴅ ʜᴇʟᴘ? ᴄᴏɴᴛᴀᴄᴛ: /about"
    )
    banner = HOME_MENU_BANNER_URL
    if banner:
        try:
            if isinstance(banner, str) and os.path.isfile(banner):
                await update.message.reply_photo(photo=InputFile(banner), caption=text, parse_mode="HTML")
            else:
                await update.message.reply_photo(photo=banner, caption=text, parse_mode="HTML")
            return
        except Exception:
            pass
    await update.message.reply_text(text, parse_mode="HTML")


async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_sub(update, context):
        return
    text = (
        "🤖 ᴀʙᴏᴜᴛ ᴛʜɪs ʙᴏᴛ\n\n"
        "<b>ᴘʀᴏꜰᴇssɪᴏɴᴀʟ ᴠɪᴅᴇᴏ ᴄᴏᴠᴇʀ ᴛᴏᴏʟ</b>\n\n"
        "<b>ᴅᴇsᴄʀɪᴘᴛɪᴏɴ:</b>\n"
        "ᴀᴘᴘʟʏ ᴄᴜsᴛᴏᴍ ᴛʜᴜᴍʙɴᴀɪʟs ᴛᴏ ʏᴏᴜʀ ᴠɪᴅᴇᴏs ɪɴsᴛᴀɴᴛʟʏ\n\n"
        "<b>ᴘʀᴇᴍɪᴜᴍ ꜰᴇᴀᴛᴜʀᴇs:</b>\n"
        "✅ ʟɪɢʜᴛɴɪɴɢ-ꜰᴀsᴛ ᴘʀᴏᴄᴇssɪɴɢ\n"
        "✅ ʜɪɢʜ-qᴜᴀʟɪᴛʏ ᴛʜᴜᴍʙɴᴀɪʟ sᴛᴏʀᴀɢᴇ\n"
        "✅ ᴘʀᴏꜰᴇssɪᴏɴᴀʟ ᴠɪᴅᴇᴏ ᴄᴏᴠᴇʀs\n"
        "✅ sɪᴍᴘʟᴇ ɪɴᴛᴇʀꜰᴀᴄᴇ\n"
        "✅ ɪɴsᴛᴀɴᴛ ʀᴇsᴜʟᴛs\n\n"
        "<b>ᴛᴇᴄʜɴᴏʟᴏɢʏ sᴛᴀᴄᴋ:</b>\n"
        "⚙️ ᴀᴅᴠᴀɴᴄᴇᴅ ᴘʏᴛʜᴏɴ ᴀᴘɪ\n"
        "<b>sᴜᴘᴘᴏʀᴛ & ᴄᴏɴᴛᴀᴄᴛ:</b>\n"
        f"👨‍💻 ᴅᴇᴠᴇʟᴏᴘᴇʀ: @{OWNER_USERNAME or 'sᴜᴘᴘᴏʀᴛ'}\n"
        "📧 ꜰᴏʀ ʜᴇʟᴘ: /about → ᴅᴇᴠᴇʟᴏᴘᴇʀ\n\n"
        "ᴛʜᴀɴᴋ ʏᴏᴜ ꜰᴏʀ ᴜsɪɴɢ ᴛʜɪs ʙᴏᴛ! 🎬"
    )
    banner = HOME_MENU_BANNER_URL
    if banner:
        try:
            if isinstance(banner, str) and os.path.isfile(banner):
                await update.message.reply_photo(photo=InputFile(banner), caption=text, parse_mode="HTML")
            else:
                await update.message.reply_photo(photo=banner, caption=text, parse_mode="HTML")
            return
        except Exception:
            pass
    await update.message.reply_text(text, parse_mode="HTML")


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_sub(update, context):
        return
    user_id = update.message.from_user.id
    thumb_status = "✅ sᴀᴠᴇᴅ & ʀᴇᴀᴅʏ" if has_thumbnail(user_id) else "❌ ɴᴏᴛ sᴀᴠᴇᴅ ʏᴇᴛ"
    
    text = (
        "⚙️ ʏᴏᴜʀ sᴇᴛᴛɪɴɢs\n\n"
        "<b>ᴀᴄᴄᴏᴜɴᴛ ɪɴꜰᴏʀᴍᴀᴛɪᴏɴ:</b>\n"
        f"👤 ᴜsᴇʀ ɪᴅ: <code>{user_id}</code>\n\n"
        "<b>ᴛʜᴜᴍʙɴᴀɪʟ sᴛᴀᴛᴜs:</b>\n"
        f"{thumb_status}\n\n"
        "<b>ᴍᴀɴᴀɢᴇᴍᴇɴᴛ ᴏᴘᴛɪᴏɴs:</b>\n"
        "🖼️ ᴠɪᴇᴡ ᴀɴᴅ ᴍᴀɴᴀɢᴇ ʏᴏᴜʀ ᴛʜᴜᴍʙɴᴀɪʟs"
    )
    settings_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🖼 ᴛʜᴜᴍʙɴᴀɪʟs", callback_data="submenu_thumbnails")],
        [InlineKeyboardButton("⬅️ ʙᴀᴄᴋ", callback_data="menu_back")]
    ])
    banner = HOME_MENU_BANNER_URL
    if banner:
        try:
            if isinstance(banner, str) and os.path.isfile(banner):
                await update.message.reply_photo(photo=InputFile(banner), caption=text, reply_markup=settings_kb, parse_mode="HTML")
            else:
                await update.message.reply_photo(photo=banner, caption=text, reply_markup=settings_kb, parse_mode="HTML")
            return
        except Exception:
            pass
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
        
        return await update.message.reply_text("✅ ᴛʜᴜᴍʙɴᴀɪʟ ʀᴇᴍᴏᴠᴇᴅ\n\nᴅᴇʟᴇᴛᴇᴅ sᴜᴄᴄᴇssꜰᴜʟʟʏ. ᴜᴘʟᴏᴀᴅ ᴀ ɴᴇᴡ ᴏɴᴇ ᴀɴʏᴛɪᴍᴇ!", reply_to_message_id=update.message.message_id, parse_mode="HTML")
    
    await update.message.reply_text("⚠️ ɴᴏ ᴛʜᴜᴍʙɴᴀɪʟ ᴛᴏ ʀᴇᴍᴏᴠᴇ\n\nꜱᴇɴᴅ ᴀ ᴘʜᴏᴛᴏ ꜰɪʀsᴛ!", reply_to_message_id=update.message.message_id, parse_mode="HTML")


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
    
    action_text = "ᴜᴘᴅᴀᴛᴇᴅ" if is_replace else "sᴀᴠᴇᴅ"
    await update.message.reply_text("✅ ᴛʜᴜᴍʙɴᴀɪʟ " + action_text + "\n\nʀᴇᴀᴅʏ! sᴇɴᴅ ᴀɴʏ ᴠɪᴅᴇᴏ ᴛᴏ ᴀᴘᴘʟʏ ᴄᴏᴠᴇʀ", reply_to_message_id=update.message.message_id, parse_mode="HTML")


async def video_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_sub(update, context):
        return
    
    user_id = update.message.from_user.id
    username = update.message.from_user.username or "No Username"
    cover = get_thumbnail(user_id)
    
    if not cover:
        return await update.message.reply_text(
            "❌ ɴᴏ ᴛʜᴜᴍʙɴᴀɪʟ ꜰᴏᴜɴᴅ\n\nꜱᴇɴᴅ ᴀ ᴘʜᴏᴛᴏ ꜰɪʀsᴛ ᴛᴏ sᴀᴠᴇ ᴛʜᴜᴍʙɴᴀɪʟ", 
            reply_to_message_id=update.message.message_id, 
            parse_mode="HTML"
        )
    
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
    
    msg = await update.message.reply_text(
        "⏳ ᴘʀᴏᴄᴇssɪɴɢ ᴠɪᴅᴇᴏ\n\nᴘʟᴇᴀsᴇ ᴡᴀɪᴛ ᴀ ꜰᴇᴡ sᴇᴄᴏɴᴅs", 
        reply_to_message_id=update.message.message_id, 
        parse_mode="HTML"
    )
    
    video = update.message.video.file_id
    original_caption = update.message.caption or ""
    
    # ✅ URL REMOVE
    url_pattern = r'https?://[^\s]+|t\.me/[^\s]+|telegram\.me/[^\s]+'
    clean_caption = re.sub(url_pattern, '', original_caption).strip()
    clean_caption = ' '.join(clean_caption.split())  # Extra spaces remove
    
    # ✅ Sirf clean caption
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
        
        if LOG_CHANNEL_ID:
            try:
                log_caption = (
                    f"🎥 <b>ᴠɪᴅᴇᴏ ᴘʀᴏᴄᴇssɪɴɢ ᴄᴏᴍᴘʟᴇᴛᴇᴅ</b>\n\n"
                    f"👤 ᴜsᴇʀ ɪᴅ: <code>{user_id}</code>\n"
                    f"📌 ᴜsᴇʀɴᴀᴍᴇ: @{username}\n"
                    f"📝 ᴄᴀᴘᴛɪᴏɴ: {clean_caption or 'ɴᴏ ᴄᴀᴘᴛɪᴏɴ'}\n"
                    f"⏰ ᴛɪᴍᴇsᴛᴀᴍᴘ: {update.message.date}"
                )
                await context.bot.send_video(
                    chat_id=LOG_CHANNEL_ID,
                    video=video,
                    caption=log_caption,
                    supports_streaming=True,
                    thumbnail=cover,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"❌ Error forwarding video: {e}")
                
    except Exception as e:
        logger.error(f"❌ Video error: {e}")
        await update.message.reply_text(
            f"❌ ᴘʀᴏᴄᴇssɪɴɢ ꜰᴀɪʟᴇᴅ\n\nᴇʀʀᴏʀ: {str(e)[:100]}", 
            parse_mode="HTML"
        )


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id != OWNER_ID:
        return await update.message.reply_text("❌ You are not authorized.")

    msg = await update.message.reply_text("🔄 Checking for updates from upstream...")

    try:
        success = update_from_upstream()

        if not success:
            await msg.edit_text(
                "❌ <b>ᴜᴘᴅᴀᴛᴇ ꜰᴀɪʟᴇᴅ</b>\n\n"
                "ᴄᴏᴜʟᴅ ɴᴏᴛ ꜰᴇᴛᴄʜ ᴜᴘᴅᴀᴛᴇs ꜰʀᴏᴍ ᴜᴘsᴛʀᴇᴀᴍ.\n"
                "ᴘʟᴇᴀsᴇ ᴄʜᴇᴄᴋ:\n"
                "• ᴜᴘsᴛʀᴇᴀᴍ_ʀᴇᴘᴏ ɪs ᴄᴏʀʀᴇᴄᴛ\n"
                "• ᴜᴘsᴛʀᴇᴀᴍ_ʙʀᴀɴᴄʜ ɪs ᴄᴏʀʀᴇᴄᴛ\n"
                "• ɪɴᴛᴇʀɴᴇᴛ ᴄᴏɴɴᴇᴄᴛɪᴏɴ ɪs ᴀᴄᴛɪᴠᴇ\n\n"
                "ᴄʜᴇᴄᴋ ʟᴏɢs ꜰᴏʀ ᴅᴇᴛᴀɪʟs.",
                parse_mode="HTML"
            )
            logger.error(f"Update failed - bot not restarting")
            return

        await msg.edit_text(
            "✅ <b>ᴜᴘᴅᴀᴛᴇ sᴜᴄᴄᴇssꜰᴜʟ!</b>\n\n"
            "🔄 ʀᴇsᴛᴀʀᴛɪɴɢ ʙᴏᴛ ᴡɪᴛʜ ɴᴇᴡ ᴄʜᴀɴɢᴇs...\n"
            "<i>ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ...</i>",
            parse_mode="HTML"
        )
        
        logger.info("✅ Update completed successfully. Restarting bot...")
        await asyncio.sleep(1)
        
        os.execv(sys.executable, [sys.executable] + sys.argv)
        
    except Exception as e:
        logger.error(f"❌ ᴇʀʀᴏʀ ᴅᴜʀɪɴɢ ʀᴇsᴛᴀʀᴛ/ᴜᴘᴅᴀᴛᴇ: {e}")
        await msg.edit_text(
            f"❌ <b>ᴇʀʀᴏʀ ᴅᴜʀɪɴɢ ᴜᴘᴅᴀᴛᴇ</b>\n\n"
            f"ᴀɴ ᴜɴᴇxᴘᴇᴄᴛᴇᴅ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ:\n"
            f"<code>{str(e)[:100]}</code>\n\n"
            f"ᴄʜᴇᴄᴋ ʟᴏɢs ꜰᴏʀ ꜰᴜʟʟ ᴅᴇᴛᴀɪʟs.",
            parse_mode="HTML"
        )


"""═══════════════════ ADMIN COMMANDS ═══════════════════"""

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    
    text = (
        "🛡️ ᴀᴅᴍɪɴ ᴄᴏɴᴛʀᴏʟ ᴘᴀɴᴇʟ\n\n"
        "👑 <b>ᴡᴇʟᴄᴏᴍᴇ ᴀᴅᴍɪɴ</b>\n\n"
        "<b>ᴍᴀɴᴀɢᴇᴍᴇɴᴛ ᴛᴏᴏʟs ᴀᴠᴀɪʟᴀʙʟᴇ:</b>\n\n"
        "📊 <b>sᴛᴀᴛɪsᴛɪᴄs</b> – ᴜsᴇʀ ᴀɴᴀʟʏᴛɪᴄs\n"
        "⏱️ <b>sᴛᴀᴛᴜs</b> – ʙᴏᴛ ᴘᴇʀꜰᴏʀᴍᴀɴᴄᴇ\n"
        "👥 <b>ᴜsᴇʀs</b> – ᴛᴏᴛᴀʟ ᴜsᴇʀs ᴄᴏᴜɴᴛ\n"
        "🚫 <b>ʙᴀɴ ᴜsᴇʀ</b> – ʙʟᴏᴄᴋ ᴜsᴇʀs\n"
        "✅ <b>ᴜɴʙᴀɴ ᴜsᴇʀ</b> – ʀᴇsᴛᴏʀᴇ ᴀᴄᴄᴇss\n"
        "📢 <b>ʙʀᴏᴀᴅᴄᴀsᴛ</b> – sᴇɴᴅ ᴀɴɴᴏᴜɴᴄᴇᴍᴇɴᴛs\n\n"
        "sᴇʟᴇᴄᴛ ᴀɴ ᴏᴘᴛɪᴏɴ:"
    )
    admin_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 sᴛᴀᴛɪsᴛɪᴄs", callback_data="admin_stats"),
         InlineKeyboardButton("⏱️ sᴛᴀᴛᴜs", callback_data="admin_status")],
        [InlineKeyboardButton("👥 ᴜsᴇʀs", callback_data="admin_users"),
         InlineKeyboardButton("🚫 ʙᴀɴ ᴜsᴇʀ", callback_data="admin_ban")],
        [InlineKeyboardButton("✅ ᴜɴʙᴀɴ ᴜsᴇʀ", callback_data="admin_unban"),
         InlineKeyboardButton("📢 ʙʀᴏᴀᴅᴄᴀsᴛ", callback_data="admin_broadcast")],
        [InlineKeyboardButton("⬅️ ʙᴀᴄᴋ", callback_data="menu_back")],
    ])
    
    banner = HOME_MENU_BANNER_URL
    
    if banner:
        try:
            if isinstance(banner, str) and os.path.isfile(banner):
                await update.message.reply_photo(
                    photo=InputFile(banner),
                    caption=text,
                    reply_markup=admin_kb,
                    parse_mode="HTML"
                )
            else:
                await update.message.reply_photo(
                    photo=banner,
                    caption=text,
                    reply_markup=admin_kb,
                    parse_mode="HTML"
                )
            return
        except Exception as e:
            logger.warning(f"Could not send admin menu banner: {e}")
    
    await update.message.reply_text(text, reply_markup=admin_kb, parse_mode="HTML")


async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    
    args = update.message.text.split(None, 2)
    if len(args) < 2:
        return await update.message.reply_text(
            "❌ ᴜsᴀɢᴇ: /ʙᴀɴ <ᴜsᴇʀ_ɪᴅ> [ʀᴇᴀsᴏɴ]\n"
            "📌 ᴇxᴀᴍᴘʟᴇ: /ʙᴀɴ 123456789 sᴘᴀᴍ"
        )
    
    try:
        user_id = int(args[1])
        reason = args[2] if len(args) > 2 else "No reason"
        
        if ban_user(user_id, reason):
            await update.message.reply_text(
                "✅ ᴜsᴇʀ " + str(user_id) + " ʙᴀɴɴᴇᴅ\n"
                f"📌 ʀᴇᴀsᴏɴ: {reason}",
                parse_mode="HTML"
            )
            
            log_data = log_user_banned(user_id, "User", reason)
            log_msg = format_log_message(user_id, "User", log_data["action"], log_data.get("details", ""))
            await send_log(context, log_msg)
        else:
            await update.message.reply_text("❌ ꜰᴀɪʟᴇᴅ ᴛᴏ ʙᴀɴ ᴜsᴇʀ")
    except ValueError:
        await update.message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ᴜsᴇʀ ɪᴅ")
    except Exception as e:
        await update.message.reply_text("❌ ᴇʀʀᴏʀ: " + str(e))


async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    
    args = update.message.text.split()
    if len(args) < 2:
        return await update.message.reply_text(
            "❌ ᴜsᴀɢᴇ: /ᴜɴʙᴀɴ <ᴜsᴇʀ_ɪᴅ>\n"
            "📌 ᴇxᴀᴍᴘʟᴇ: /ᴜɴʙᴀɴ 123456789"
        )
    
    try:
        user_id = int(args[1])
        if unban_user(user_id):
            await update.message.reply_text("✅ ᴜsᴇʀ " + str(user_id) + " ᴜɴʙᴀɴɴᴇᴅ")
            
            log_data = log_user_unbanned(user_id, "User")
            log_msg = format_log_message(user_id, "User", log_data["action"])
            await send_log(context, log_msg)
        else:
            await update.message.reply_text("❌ ꜰᴀɪʟᴇᴅ ᴛᴏ ᴜɴʙᴀɴ ᴜsᴇʀ")
    except ValueError:
        await update.message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ᴜsᴇʀ ɪᴅ")
    except Exception as e:
        await update.message.reply_text("❌ ᴇʀʀᴏʀ: " + str(e))


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    
    stats = get_stats()
    text = (
        "📊 ʙᴏᴛ sᴛᴀᴛɪsᴛɪᴄs\n\n"
        f"👥 ᴛᴏᴛᴀʟ ᴜsᴇʀs: {stats['total_users']}\n"
        f"🚫 ʙᴀɴɴᴇᴅ ᴜsᴇʀs: {stats['banned_users']}\n"
        f"🖼 ᴜsᴇʀs ᴡɪᴛʜ ᴛʜᴜᴍʙɴᴀɪʟ: {stats['users_with_thumbnail']}"
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
            "⏱️ ʙᴏᴛ sᴛᴀᴛᴜs\n\n"
            f"🟢 sᴛᴀᴛᴜs: ᴏɴʟɪɴᴇ\n"
            f"⏰ ᴜᴘᴛɪᴍᴇ: {uptime_hours}ʜ {uptime_mins}ᴍ\n\n"
            f"🖥 sʏsᴛᴇᴍ ʀᴇsᴏᴜʀᴄᴇs:\n"
            f"🔴 ᴄᴘᴜ: {cpu_percent}%\n"
            f"🟡 ʀᴀᴍ: {ram_percent}% ({ram.used // (1024**2)} ᴍʙ / {ram.total // (1024**2)} ᴍʙ)"
        )
        await update.message.reply_text(text, parse_mode="HTML")
    except ImportError:
        text = (
            "⏱️ ʙᴏᴛ sᴛᴀᴛᴜs\n\n"
            f"🟢 sᴛᴀᴛᴜs: ᴏɴʟɪɴᴇ\n\n"
            "⚠️ ɪɴsᴛᴀʟʟ ᴘsᴜᴛɪʟ ꜰᴏʀ sʏsᴛᴇᴍ sᴛᴀᴛs\n"
            "📦 ʀᴜɴ: ᴘɪᴘ ɪɴsᴛᴀʟʟ ᴘsᴜᴛɪʟ"
        )
        await update.message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text("❌ ᴇʀʀᴏʀ: " + str(e))


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    
    args = update.message.text.split(None, 1)
    if len(args) < 2:
        return await update.message.reply_text(
            "❌ ᴜsᴀɢᴇ: /ʙʀᴏᴀᴅᴄᴀsᴛ <ᴍᴇssᴀɢᴇ>\n\n"
            "📌 ᴇxᴀᴍᴘʟᴇ: /ʙʀᴏᴀᴅᴄᴀsᴛ ʜᴇʟʟᴏ ᴇᴠᴇʀʏᴏɴᴇ!\n\n"
            "💡 ᴛɪᴘs:\n"
            "• ᴍᴇssᴀɢᴇ sᴇɴᴛ ᴛᴏ ᴀʟʟ ᴜsᴇʀs\n"
            "• ʜᴛᴍʟ ꜰᴏʀᴍᴀᴛᴛɪɴɢ sᴜᴘᴘᴏʀᴛᴇᴅ\n"
            "• ᴇᴍᴏᴊɪs ᴡᴏʀᴋ ɢʀᴇᴀᴛ ᴛᴏᴏ",
            parse_mode="HTML"
        )
    
    message_text = args[1]
    
    confirm_text = (
        "📢 ʙʀᴏᴀᴅᴄᴀsᴛ ᴄᴏɴꜰɪʀᴍᴀᴛɪᴏɴ\n\n"
        f"📝 ᴍᴇssᴀɢᴇ:\n"
        f"{message_text}\n\n"
        f"👥 ᴛᴏᴛᴀʟ ᴜsᴇʀs: {get_total_users()}\n\n"
        "⚠️ ᴘʀᴏᴄᴇssɪɴɢ... sᴇɴᴅɪɴɢ ɴᴏᴡ"
    )
    msg = await update.message.reply_text(confirm_text, parse_mode="HTML")
    
    try:
        from database import db
        users_collection = db.get_collection("users")
        all_users = users_collection.find({}, {"user_id": 1})
        
        user_ids = [user["user_id"] for user in all_users if "user_id" in user]
        
        if not user_ids:
            await msg.edit_text(
                "❌ ɴᴏ ᴜsᴇʀs ꜰᴏᴜɴᴅ\n\n"
                "💭 ᴅᴀᴛᴀʙᴀsᴇ ɪs ᴇᴍᴘᴛʏ",
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
            "✅ ʙʀᴏᴀᴅᴄᴀsᴛ ᴄᴏᴍᴘʟᴇᴛᴇᴅ\n\n"
            f"📤 sᴇɴᴛ: {sent}\n"
            f"❌ ꜰᴀɪʟᴇᴅ: {failed}\n"
            f"👥 ᴛᴏᴛᴀʟ: {sent + failed}\n\n"
            f"📊 sᴜᴄᴄᴇss: {(sent/(sent+failed)*100):.1f}%"
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
            f"❌ ʙʀᴏᴀᴅᴄᴀsᴛ ꜰᴀɪʟᴇᴅ\n\n"
            f"ᴇʀʀᴏʀ: {str(e)[:100]}\n\n"
            "ᴄʜᴇᴄᴋ ʟᴏɢs ꜰᴏʀ ᴅᴇᴛᴀɪʟs.",
            parse_mode="HTML"
        )
        logger.error(f"Broadcast error: {e}", exc_info=True)


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_sub(update, context):
        return


"""-----------MAIN FUNCTION WITH DEPLOY LOG-----------"""

async def post_init(app: Application):
    """✅ Bot start/deploy hone par simple log bhejega"""
    logger.info("🚀 Bot is starting up...")
    
    if LOG_CHANNEL_ID:
        try:
            # ✅ SIMPLE DEPLOY LOG - Sirf ek baar bhejega
            deploy_message = (
                "🚀 <b>Bot is Live</b>\n\n"
                f"📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"👑 Owner: @{OWNER_USERNAME or 'Owner'}"
            )
            
            await app.bot.send_message(
                chat_id=LOG_CHANNEL_ID,
                text=deploy_message,
                parse_mode="HTML"
            )
            logger.info("✅ Deploy log sent")
            
        except Exception as e:
            logger.error(f"❌ Deploy log failed: {e}")
    
    # Setup bot commands
    try:
        from telegram import BotCommand
        commands = [
            BotCommand("start", "🏠 Start bot"),
            BotCommand("help", "ℹ️ How to use"),
            BotCommand("about", "🤖 About bot"),
            BotCommand("settings", "⚙️ Settings"),
            BotCommand("remove", "🗑️ Remove thumbnail"),
            BotCommand("showthumbnail", "🖼️ Show thumbnail"),
            BotCommand("admin", "🛡️ Admin panel"),
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
        logger.error(f"🔴 ERROR: {context.error}", exc_info=context.error)

    app.add_error_handler(error_handler)
    
    # ✅ POST_INIT - Deploy log ke liye
    app.post_init = post_init

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
