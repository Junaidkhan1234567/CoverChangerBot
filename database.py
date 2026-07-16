import logging
from datetime import datetime
from pymongo import MongoClient
import os

logger = logging.getLogger(__name__)

# MongoDB Connection
MONGO_URI = os.environ.get("MONGO_URI")
if not MONGO_URI:
    logger.error("MONGO_URI not set in environment variables")
    raise SystemExit("MONGO_URI not set")

try:
    client = MongoClient(MONGO_URI)
    db = client.get_database()
    logger.info("✅ MongoDB connected successfully")
except Exception as e:
    logger.error(f"❌ MongoDB connection failed: {e}")
    raise

# ═══════════════════ USER FUNCTIONS ═══════════════════

def is_user_exists(user_id: int) -> bool:
    """Check if user exists in database"""
    try:
        users_collection = db.get_collection("users")
        user = users_collection.find_one({"user_id": user_id})
        return user is not None
    except Exception as e:
        logger.error(f"Error checking user existence: {e}")
        return False

def log_new_user(user_id: int, username: str, first_name: str) -> dict:
    """Log new user in database"""
    try:
        users_collection = db.get_collection("users")
        users_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "username": username,
                    "first_name": first_name,
                    "joined_at": datetime.now(),
                    "last_active": datetime.now()
                }
            },
            upsert=True
        )
        logger.info(f"✅ New user logged: {user_id}")
        return {"action": "🆕 New User Started Bot", "details": f"Name: {first_name}"}
    except Exception as e:
        logger.error(f"Error logging new user: {e}")
        return {"action": "🆕 New User Started Bot", "details": "Error logging"}

def get_total_users() -> int:
    """Get total number of users"""
    try:
        users_collection = db.get_collection("users")
        return users_collection.count_documents({})
    except Exception as e:
        logger.error(f"Error getting total users: {e}")
        return 0

def get_banned_users_count() -> int:
    """Get number of banned users"""
    try:
        users_collection = db.get_collection("users")
        return users_collection.count_documents({"banned": True})
    except Exception as e:
        logger.error(f"Error getting banned users count: {e}")
        return 0

def get_stats() -> dict:
    """Get bot statistics"""
    try:
        total_users = get_total_users()
        banned_users = get_banned_users_count()
        users_collection = db.get_collection("users")
        users_with_thumbnail = users_collection.count_documents({"thumbnail": {"$exists": True}})
        
        return {
            "total_users": total_users,
            "banned_users": banned_users,
            "users_with_thumbnail": users_with_thumbnail
        }
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return {"total_users": 0, "banned_users": 0, "users_with_thumbnail": 0}

# ═══════════════════ THUMBNAIL FUNCTIONS ═══════════════════

def save_thumbnail(user_id: int, photo_id: str) -> None:
    """Save or update user's thumbnail"""
    try:
        users_collection = db.get_collection("users")
        users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"thumbnail": photo_id, "updated_at": datetime.now()}},
            upsert=True
        )
        logger.info(f"✅ Thumbnail saved for user {user_id}")
    except Exception as e:
        logger.error(f"Error saving thumbnail: {e}")

def get_thumbnail(user_id: int) -> str:
    """Get user's thumbnail photo ID"""
    try:
        users_collection = db.get_collection("users")
        user = users_collection.find_one({"user_id": user_id})
        if user and "thumbnail" in user:
            return user["thumbnail"]
        return None
    except Exception as e:
        logger.error(f"Error getting thumbnail: {e}")
        return None

def delete_thumbnail(user_id: int) -> bool:
    """Delete user's thumbnail"""
    try:
        users_collection = db.get_collection("users")
        result = users_collection.update_one(
            {"user_id": user_id},
            {"$unset": {"thumbnail": ""}}
        )
        if result.modified_count > 0:
            logger.info(f"✅ Thumbnail deleted for user {user_id}")
            return True
        return False
    except Exception as e:
        logger.error(f"Error deleting thumbnail: {e}")
        return False

def has_thumbnail(user_id: int) -> bool:
    """Check if user has a thumbnail"""
    try:
        users_collection = db.get_collection("users")
        user = users_collection.find_one({"user_id": user_id})
        return user is not None and "thumbnail" in user
    except Exception as e:
        logger.error(f"Error checking thumbnail: {e}")
        return False

# ═══════════════════ BAN FUNCTIONS ═══════════════════

def ban_user(user_id: int, reason: str = "No reason") -> bool:
    """Ban a user"""
    try:
        users_collection = db.get_collection("users")
        result = users_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "banned": True,
                    "ban_reason": reason,
                    "banned_at": datetime.now()
                }
            },
            upsert=True
        )
        if result.modified_count > 0 or result.upserted_id:
            logger.info(f"✅ User {user_id} banned: {reason}")
            return True
        return False
    except Exception as e:
        logger.error(f"Error banning user: {e}")
        return False

def unban_user(user_id: int) -> bool:
    """Unban a user"""
    try:
        users_collection = db.get_collection("users")
        result = users_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {"banned": False},
                "$unset": {"ban_reason": "", "banned_at": ""}
            }
        )
        if result.modified_count > 0:
            logger.info(f"✅ User {user_id} unbanned")
            return True
        return False
    except Exception as e:
        logger.error(f"Error unbanning user: {e}")
        return False

def is_user_banned(user_id: int) -> bool:
    """Check if user is banned"""
    try:
        users_collection = db.get_collection("users")
        user = users_collection.find_one({"user_id": user_id})
        if user and "banned" in user:
            return user["banned"]
        return False
    except Exception as e:
        logger.error(f"Error checking ban status: {e}")
        return False

# ═══════════════════ LOG FORMATTING ═══════════════════

def format_log_message(user_id: int, username: str, action: str, details: str = "") -> str:
    """Format log message for channel"""
    log_text = (
        f"📝 {action}\n\n"
        f"👤 User ID: <code>{user_id}</code>\n"
        f"📌 Username: @{username}\n"
        f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    if details:
        log_text += f"\n📋 Details: {details}"
    return log_text

def log_user_banned(user_id: int, username: str, reason: str) -> dict:
    """Log user banned"""
    return {"action": "🚫 User Banned", "details": f"Reason: {reason}"}

def log_user_unbanned(user_id: int, username: str) -> dict:
    """Log user unbanned"""
    return {"action": "✅ User Unbanned"}

def log_thumbnail_set(user_id: int, username: str, is_replace: bool = False) -> dict:
    """Log thumbnail set"""
    action = "🖼️ Thumbnail Updated" if is_replace else "🖼️ Thumbnail Saved"
    return {"action": action}

def log_thumbnail_removed(user_id: int, username: str) -> dict:
    """Log thumbnail removed"""
    return {"action": "🗑️ Thumbnail Removed"}

def log_video_processed(user_id: int, username: str) -> dict:
    """Log video processed"""
    return {"action": "🎬 Video Processed"}
