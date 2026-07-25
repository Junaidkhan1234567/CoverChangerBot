# video_editor.py - Lightweight version using only Pillow
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
        """
        Add watermark to video thumbnail/cover image using Pillow only
        """
        try:
            if not os.path.exists(thumbnail_path):
                logger.error(f"❌ Thumbnail not found: {thumbnail_path}")
                return thumbnail_path
            
            # Load thumbnail image
            img = Image.open(thumbnail_path).convert("RGBA")
            
            # Create watermark layer
            watermark = Image.new("RGBA", img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(watermark)
            
            # Process watermark text with variables
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
            
            # Calculate font size based on image size
            font_size = max(16, min(img.size[0] // 20, 60))
            
            # Try to load font
            try:
                font = ImageFont.truetype("arial.ttf", font_size)
            except:
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
                except:
                    font = ImageFont.load_default()
            
            # Get text size using textbbox
            bbox = draw.textbbox((0, 0), watermark_text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            
            # Margin from edges
            margin = 20
            
            img_width = img.size[0]
            img_height = img.size[1]
            
            # Position mapping - CLEAN IF-ELIF
            if position == "top-left":
                x = margin
                y = margin
            elif position == "top-right":
                x = img_width - text_width - margin
                y = margin
            elif position == "bottom-left":
                x = margin
                y = img_height - text_height - margin
            elif position == "bottom-right":
                x = img_width - text_width - margin
                y = img_height - text_height - margin
            elif position == "center":
                x = (img_width - text_width) // 2
                y = (img_height - text_height) // 2
            else:
                # Default: bottom-right
                x = img_width - text_width - margin
                y = img_height - text_height - margin
            
            logger.info(f"📍 Position: {position}, Text: {watermark_text[:20]}..., Image: {img_width}x{img_height}, Position: ({x}, {y})")
            
            # Opacity (0-255)
            alpha = int(opacity * 255)
            
            # Draw shadow for better visibility
            shadow_offset = 2
            draw.text(
                (x + shadow_offset, y + shadow_offset),
                watermark_text,
                font=font,
                fill=(0, 0, 0, alpha // 2)
            )
            
            # Draw main text
            draw.text(
                (x, y),
                watermark_text,
                font=font,
                fill=(255, 255, 255, alpha)
            )
            
            # Composite images
            combined = Image.alpha_composite(img, watermark)
            
            # Convert back to RGB
            combined = combined.convert("RGB")
            
            # Save with same quality
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

# Global instance
video_editor = VideoEditor()
