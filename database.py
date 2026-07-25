# database.py
import os
import logging
from datetime import datetime
from pymongo import MongoClient

# Setup logging
logger = logging.getLogger(__name__)

# MongoDB Connection Setup
MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DATABASE = os.environ.get("MONGODB_DATABASE", "video_cover_bot")

try:
    mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    db = mongo_client[MONGODB_DATABASE]
    users_collection = db["users"]
    mongo_client.server_info()
    logger.info("✅ MongoDB connected successfully")
    DB_AVAILABLE = True
except Exception as e:
    logger.warning(f"⚠️ MongoDB not available: {e}")
    DB_AVAILABLE = False
    users_collection = None


def save_thumbnail(user_id: int, photo_id: str) -> bool:
    if not DB_AVAILABLE:
        return False
    try:
        users_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "user_id": user_id,
                    "photo_id": photo_id,
                    "updated_at": datetime.now()
                }
            },
            upsert=True
        )
        logger.info(f"✅ Thumbnail saved for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Error saving thumbnail: {e}")
        return False


def get_thumbnail(user_id: int) -> str | None:
    if not DB_AVAILABLE:
        return None
    try:
        user_record = users_collection.find_one({"user_id": user_id})
        if user_record and "photo_id" in user_record:
            return user_record["photo_id"]
        return None
    except Exception as e:
        logger.error(f"❌ Error retrieving thumbnail: {e}")
        return None


def delete_thumbnail(user_id: int) -> bool:
    if not DB_AVAILABLE:
        return False
    try:
        result = users_collection.update_one(
            {"user_id": user_id},
            {"$unset": {"photo_id": ""}}
        )
        return result.modified_count > 0
    except Exception as e:
        logger.error(f"❌ Error deleting thumbnail: {e}")
        return False


def has_thumbnail(user_id: int) -> bool:
    if not DB_AVAILABLE:
        return False
    try:
        user_record = users_collection.find_one({"user_id": user_id})
        return user_record is not None and "photo_id" in user_record
    except Exception as e:
        logger.error(f"❌ Error checking thumbnail: {e}")
        return False


def ban_user(user_id: int, reason: str = "No reason") -> bool:
    if not DB_AVAILABLE:
        return False
    try:
        users_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "user_id": user_id,
                    "is_banned": True,
                    "ban_reason": reason,
                    "banned_at": datetime.now()
                }
            },
            upsert=True
        )
        logger.info(f"🚫 User {user_id} banned. Reason: {reason}")
        return True
    except Exception as e:
        logger.error(f"❌ Error banning user {user_id}: {e}")
        return False


def unban_user(user_id: int) -> bool:
    if not DB_AVAILABLE:
        return False
    try:
        result = users_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "is_banned": False,
                    "unbanned_at": datetime.now()
                }
            }
        )
        return result.modified_count > 0
    except Exception as e:
        logger.error(f"❌ Error unbanning user {user_id}: {e}")
        return False


def is_user_banned(user_id: int) -> bool:
    if not DB_AVAILABLE:
        return False
    try:
        user_record = users_collection.find_one({"user_id": user_id})
        return user_record and user_record.get("is_banned", False)
    except Exception as e:
        logger.error(f"❌ Error checking ban status: {e}")
        return False


def get_total_users() -> int:
    if not DB_AVAILABLE:
        return 0
    try:
        return users_collection.count_documents({})
    except Exception as e:
        logger.error(f"❌ Error counting users: {e}")
        return 0


def get_banned_users_count() -> int:
    if not DB_AVAILABLE:
        return 0
    try:
        return users_collection.count_documents({"is_banned": True})
    except Exception as e:
        logger.error(f"❌ Error counting banned users: {e}")
        return 0


def get_stats() -> dict:
    if not DB_AVAILABLE:
        return {"total_users": 0, "banned_users": 0, "users_with_thumbnail": 0}
    try:
        total = users_collection.count_documents({})
        banned = users_collection.count_documents({"is_banned": True})
        with_thumb = users_collection.count_documents({"photo_id": {"$exists": True}})
        return {"total_users": total, "banned_users": banned, "users_with_thumbnail": with_thumb}
    except Exception as e:
        logger.error(f"❌ Error getting stats: {e}")
        return {"total_users": 0, "banned_users": 0, "users_with_thumbnail": 0}


def is_user_exists(user_id: int) -> bool:
    if not DB_AVAILABLE:
        return False
    try:
        user_record = users_collection.find_one({"user_id": user_id})
        return user_record is not None
    except Exception as e:
        logger.error(f"❌ Error checking user existence: {e}")
        return False


# ═══════════════════════════════════════════════════════
# WATERMARK FUNCTIONS - NEW
# ═══════════════════════════════════════════════════════

def get_watermark_settings(user_id: int) -> dict:
    """Get watermark settings for user"""
    if not DB_AVAILABLE:
        return {"enabled": False, "text": "© Cover Bot", "position": "bottom-right", "opacity": 0.7, "font_size": 30}
    try:
        user_record = users_collection.find_one({"user_id": user_id})
        if user_record and "watermark" in user_record:
            return user_record["watermark"]
        return {"enabled": False, "text": "© {username} • Cover Bot", "position": "bottom-right", "opacity": 0.7, "font_size": 30}
    except Exception as e:
        logger.error(f"Error getting watermark settings: {e}")
        return {"enabled": False, "text": "© {username} • Cover Bot", "position": "bottom-right", "opacity": 0.7, "font_size": 30}


def save_watermark_settings(user_id: int, settings: dict) -> bool:
    """Save watermark settings for user"""
    if not DB_AVAILABLE:
        return False
    try:
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
# VERIFICATION FUNCTIONS
# ═══════════════════════════════════════════════════════

def is_user_verified(user_id: int) -> bool:
    if not DB_AVAILABLE:
        return False
    try:
        user_record = users_collection.find_one({"user_id": user_id})
        return user_record and user_record.get("is_verified", False)
    except Exception as e:
        logger.error(f"❌ Error checking verification: {e}")
        return False


def set_user_verified(user_id: int, verified: bool = True) -> bool:
    if not DB_AVAILABLE:
        return False
    try:
        users_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "user_id": user_id,
                    "is_verified": verified,
                    "verified_at": datetime.now() if verified else None
                }
            },
            upsert=True
        )
        logger.info(f"✅ User {user_id} verification set to {verified}")
        return True
    except Exception as e:
        logger.error(f"❌ Error setting verification: {e}")
        return False


# ═══════════════════════════════════════════════════════
# LOGGING FUNCTIONS
# ═══════════════════════════════════════════════════════

def create_log_entry(user_id: int, username: str, action: str, details: str = "") -> dict:
    return {
        "user_id": user_id,
        "username": f"@{username}" if username else "Unknown",
        "action": action,
        "details": details,
        "timestamp": datetime.now().isoformat()
    }


def format_log_message(user_id: int, username: str, action: str, details: str = "") -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    username_str = f"@{username}" if username else "Unknown"
    log_msg = (
        f"📝 <b>{action}</b>\n\n"
        f"👤 User ID: <code>{user_id}</code>\n"
        f"📌 Username: {username_str}\n"
        f"⏰ Time: {now}\n"
    )
    if details:
        log_msg += f"📋 Details: {details}\n"
    return log_msg


def log_new_user(user_id: int, username: str, first_name: str) -> dict:
    action = "🆕 New User Started Bot"
    details = f"Name: {first_name}"
    return create_log_entry(user_id, username, action, details)


def log_user_banned(user_id: int, username: str, reason: str) -> dict:
    action = "🚫 User Banned"
    details = f"Reason: {reason}"
    return create_log_entry(user_id, username, action, details)


def log_user_unbanned(user_id: int, username: str) -> dict:
    action = "✅ User Unbanned"
    return create_log_entry(user_id, username, action)


def log_thumbnail_set(user_id: int, username: str, is_replace: bool = False) -> dict:
    action = "🖼 Thumbnail Replaced" if is_replace else "🖼 Thumbnail Set"
    return create_log_entry(user_id, username, action)


def log_thumbnail_removed(user_id: int, username: str) -> dict:
    action = "🗑️ Thumbnail Removed"
    return create_log_entry(user_id, username, action)
