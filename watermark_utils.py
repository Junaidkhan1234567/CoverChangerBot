# watermark_utils.py
import os
import logging
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

def apply_watermark_to_image(image_path: str, watermark_text: str, 
                             position: str = "bottom-right", 
                             opacity: float = 0.7,
                             font_size: int = 30,
                             user_info: dict = None) -> str:
    """
    Apply watermark to an image file
    Returns path to watermarked image
    """
    try:
        if not os.path.exists(image_path):
            logger.error(f"Image not found: {image_path}")
            return image_path
        
        # Open image
        img = Image.open(image_path).convert("RGBA")
        
        # Create watermark layer
        watermark = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(watermark)
        
        # Process text with variables
        if user_info:
            watermark_text = watermark_text.replace('{username}', user_info.get('username', 'User'))
            watermark_text = watermark_text.replace('{first_name}', user_info.get('first_name', 'User'))
            watermark_text = watermark_text.replace('{bot_name}', 'Cover Bot')
            watermark_text = watermark_text.replace('{date}', datetime.now().strftime('%Y-%m-%d'))
            watermark_text = watermark_text.replace('{time}', datetime.now().strftime('%H:%M:%S'))
        
        # Calculate font size
        font_size = max(16, min(img.size[0] // 20, 60))
        
        # Load font
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except:
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
            except:
                font = ImageFont.load_default()
        
        # Calculate text position
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
        
        # Shadow
        draw.text((x + 2, y + 2), watermark_text, font=font, fill=(0, 0, 0, alpha // 2))
        draw.text((x, y), watermark_text, font=font, fill=(255, 255, 255, alpha))
        
        # Composite
        combined = Image.alpha_composite(img, watermark)
        combined = combined.convert("RGB")
        
        output_path = image_path.replace('.', '_watermarked.')
        combined.save(output_path, quality=95)
        
        logger.info(f"✅ Watermark applied to image: {output_path}")
        return output_path
        
    except Exception as e:
        logger.error(f"❌ Watermark error: {e}")
        return image_path
