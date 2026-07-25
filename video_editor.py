# video_editor.py - Lightweight version
import os
import logging
import tempfile
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

class VideoEditor:
    """Video Editor - Lightweight version using only Pillow"""
    
    def __init__(self):
        self.temp_dir = tempfile.mkdtemp(prefix="video_editor_")
        logger.info(f"✅ Video Editor initialized at {self.temp_dir}")
    
    def add_watermark_to_thumbnail(self, thumbnail_path: str, watermark_text: str = None, 
                                   position: str = "bottom-right", opacity: float = 0.7, 
                                   font_size: int = 30, user_info: dict = None) -> str:
        try:
            if not os.path.exists(thumbnail_path):
                logger.error(f"❌ Thumbnail not found: {thumbnail_path}")
                return thumbnail_path
            
            img = Image.open(thumbnail_path).convert("RGBA")
            watermark = Image.new("RGBA", img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(watermark)
            
            if watermark_text:
                if user_info:
                    username = user_info.get('username', 'User')
                    first_name = user_info.get('first_name', 'User')
                    watermark_text = watermark_text.replace('{username}', username)
                    watermark_text = watermark_text.replace('{first_name}', first_name)
                    watermark_text = watermark_text.replace('{bot_name}', 'Cover Bot')
                    watermark_text = watermark_text.replace('{date}', datetime.now().strftime('%Y-%m-%d'))
                    watermark_text = watermark_text.replace('{time}', datetime.now().strftime('%H:%M:%S'))
            else:
                watermark_text = "© Cover Bot"
            
            font_size = max(16, min(img.size[0] // 20, 60))
            
            try:
                font = ImageFont.truetype("arial.ttf", font_size)
            except:
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
                except:
                    font = ImageFont.load_default()
            
            bbox = draw.textbbox((0, 0), watermark_text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            
            margin = 20
            
            pos_map = {
                "top-left": (margin, margin),
                "top-right": (img.size[0] - text_width - margin, margin),
                "bottom-left": (margin, img.size[1] - text_height - margin),
                "bottom-right": (img.size[0] - text_width - margin, img.size[1] - text_height - margin),
                "center": ((img.size[0] - text_width) // 2, (img.size[1] - text_height) // 2)
            }
            
            x, y = pos_map.get(position, pos_map["bottom-right"])
            alpha = int(opacity * 255)
            
            draw.text((x + 2, y + 2), watermark_text, font=font, fill=(0, 0, 0, alpha // 2))
            draw.text((x, y), watermark_text, font=font, fill=(255, 255, 255, alpha))
            
            combined = Image.alpha_composite(img, watermark)
            combined = combined.convert("RGB")
            
            output_path = os.path.join(self.temp_dir, f"watermarked_thumb_{int(datetime.now().timestamp())}.jpg")
            combined.save(output_path, quality=95)
            
            logger.info(f"✅ Watermark added to thumbnail: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"❌ Watermark thumbnail error: {e}")
            return thumbnail_path
    
    def cleanup(self):
        try:
            import shutil
            shutil.rmtree(self.temp_dir)
            logger.info(f"✅ Cleaned temp directory: {self.temp_dir}")
        except Exception as e:
            logger.error(f"❌ Cleanup error: {e}")

video_editor = VideoEditor()
