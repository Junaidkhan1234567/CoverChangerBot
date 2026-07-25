# video_editor.py
import os
import logging
import tempfile
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import cv2
import numpy as np
from moviepy.editor import VideoFileClip, TextClip, CompositeVideoClip, ImageClip
from moviepy.video.fx import fadein, fadeout

logger = logging.getLogger(__name__)

class VideoEditor:
    """Advanced video editing capabilities - Complete Class"""
    
    def __init__(self):
        """Initialize video editor with temp directory"""
        self.temp_dir = tempfile.mkdtemp(prefix="video_editor_")
        logger.info(f"✅ Video Editor initialized at {self.temp_dir}")
        
        self.default_font = 'Arial'
        self.default_font_size = 30
        self.default_opacity = 0.7
    
    # ═══════════════════════════════════════════════════════
    # WATERMARK ON THUMBNAIL - MAIN FUNCTION
    # ═══════════════════════════════════════════════════════
    
    def add_watermark_to_thumbnail(self, thumbnail_path: str, watermark_text: str = None, 
                                   position: str = "bottom-right", opacity: float = 0.7, 
                                   font_size: int = 30, user_info: dict = None) -> str:
        """
        Add watermark to video thumbnail/cover image
        Watermark ko thumbnail image par overlay karega
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
                # Replace variables
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
            
            # Calculate text position
            bbox = draw.textbbox((0, 0), watermark_text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            
            margin = 20
            
            # Position mapping
            pos_map = {
                "top-left": (margin, margin),
                "top-right": (img.size[0] - text_width - margin, margin),
                "bottom-left": (margin, img.size[1] - text_height - margin),
                "bottom-right": (img.size[0] - text_width - margin, img.size[1] - text_height - margin),
                "center": ((img.size[0] - text_width) // 2, (img.size[1] - text_height) // 2)
            }
            
            x, y = pos_map.get(position, pos_map["bottom-right"])
            
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
    
    # ═══════════════════════════════════════════════════════
    # VIDEO WATERMARK FUNCTIONS
    # ═══════════════════════════════════════════════════════
    
    def add_watermark_to_video(self, video_path: str, watermark_text: str = None, 
                               watermark_image_path: str = None, 
                               position: str = "bottom-right",
                               opacity: float = 0.7,
                               font_size: int = 30,
                               font_color: str = "white",
                               margin_x: int = 20,
                               margin_y: int = 20) -> str:
        """Add watermark to video"""
        try:
            video = VideoFileClip(video_path)
            video_width, video_height = video.size
            
            if watermark_image_path and os.path.exists(watermark_image_path):
                watermark = self._create_image_watermark(
                    watermark_image_path, 
                    video_width, 
                    video_height,
                    position,
                    opacity,
                    margin_x,
                    margin_y
                )
            else:
                watermark = self._create_text_watermark(
                    watermark_text or "© Video Cover Bot",
                    video_width,
                    video_height,
                    position,
                    font_size,
                    font_color,
                    opacity,
                    margin_x,
                    margin_y
                )
            
            if watermark:
                final_video = CompositeVideoClip([video, watermark])
                output_path = os.path.join(self.temp_dir, f"watermarked_{int(datetime.now().timestamp())}.mp4")
                final_video.write_videofile(
                    output_path,
                    codec='libx264',
                    audio_codec='aac',
                    temp_audiofile='temp-audio.m4a',
                    remove_temp=True,
                    fps=video.fps,
                    threads=4,
                    verbose=False,
                    logger=None
                )
                video.close()
                watermark.close()
                final_video.close()
                logger.info(f"✅ Watermark added to video: {output_path}")
                return output_path
            
            return video_path
            
        except Exception as e:
            logger.error(f"❌ Watermark error: {e}")
            return video_path
    
    def _create_text_watermark(self, text: str, video_width: int, video_height: int,
                               position: str, font_size: int, font_color: str,
                               opacity: float, margin_x: int, margin_y: int):
        try:
            txt_clip = TextClip(
                text,
                fontsize=font_size,
                color=font_color,
                font=self.default_font,
                stroke_color='black',
                stroke_width=2,
                bg_color=None,
                size=(video_width * 0.8, None),
                method='caption'
            )
            txt_clip = txt_clip.set_duration(None)
            text_width, text_height = txt_clip.size
            
            pos_map = {
                "top-left": (margin_x, margin_y),
                "top-right": (video_width - text_width - margin_x, margin_y),
                "bottom-left": (margin_x, video_height - text_height - margin_y),
                "bottom-right": (video_width - text_width - margin_x, video_height - text_height - margin_y),
                "center": ((video_width - text_width) // 2, (video_height - text_height) // 2)
            }
            
            position_tuple = pos_map.get(position, pos_map["bottom-right"])
            txt_clip = txt_clip.set_position(position_tuple)
            txt_clip = txt_clip.set_opacity(opacity)
            return txt_clip
            
        except Exception as e:
            logger.error(f"❌ Text watermark creation error: {e}")
            return None
    
    def _create_image_watermark(self, image_path: str, video_width: int, video_height: int,
                                position: str, opacity: float, margin_x: int, margin_y: int):
        try:
            watermark_img = ImageClip(image_path)
            max_width = min(200, video_width * 0.15)
            aspect_ratio = watermark_img.size[1] / watermark_img.size[0] if watermark_img.size[0] > 0 else 1
            new_width = max_width
            new_height = max_width * aspect_ratio
            watermark_img = watermark_img.resize((new_width, new_height))
            watermark_img = watermark_img.set_opacity(opacity)
            
            pos_map = {
                "top-left": (margin_x, margin_y),
                "top-right": (video_width - new_width - margin_x, margin_y),
                "bottom-left": (margin_x, video_height - new_height - margin_y),
                "bottom-right": (video_width - new_width - margin_x, video_height - new_height - margin_y),
                "center": ((video_width - new_width) // 2, (video_height - new_height) // 2)
            }
            
            position_tuple = pos_map.get(position, pos_map["bottom-right"])
            watermark_img = watermark_img.set_position(position_tuple)
            return watermark_img
            
        except Exception as e:
            logger.error(f"❌ Image watermark creation error: {e}")
            return None
    
    # ═══════════════════════════════════════════════════════
    # PREVIEW FUNCTIONS
    # ═══════════════════════════════════════════════════════
    
    def create_watermark_preview(self, video_path: str, watermark_text: str = "© Video Cover Bot") -> str:
        try:
            positions = ["top-left", "top-right", "bottom-left", "bottom-right", "center"]
            position_labels = {
                "top-left": "↖️ Top Left",
                "top-right": "↗️ Top Right", 
                "bottom-left": "↙️ Bottom Left",
                "bottom-right": "↘️ Bottom Right",
                "center": "🎯 Center"
            }
            
            video = VideoFileClip(video_path)
            if video.duration > 10:
                video = video.subclip(0, 10)
            
            watermark_clips = []
            for pos in positions:
                watermark = self._create_text_watermark(
                    text=f"{position_labels[pos]}\n{watermark_text}",
                    video_width=video.size[0],
                    video_height=video.size[1],
                    position=pos,
                    font_size=24,
                    font_color="white",
                    opacity=0.8,
                    margin_x=20,
                    margin_y=20
                )
                if watermark:
                    watermark_clips.append(watermark)
            
            final_video = CompositeVideoClip([video] + watermark_clips)
            output_path = os.path.join(self.temp_dir, f"preview_{int(datetime.now().timestamp())}.mp4")
            final_video.write_videofile(
                output_path,
                codec='libx264',
                audio_codec='aac',
                temp_audiofile='temp-audio.m4a',
                remove_temp=True,
                fps=video.fps,
                threads=4,
                verbose=False,
                logger=None
            )
            
            video.close()
            final_video.close()
            for clip in watermark_clips:
                if clip:
                    clip.close()
                
            logger.info(f"✅ Watermark preview created: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"❌ Preview creation error: {e}")
            return video_path
    
    def get_video_info(self, video_path: str) -> dict:
        try:
            video = VideoFileClip(video_path)
            info = {
                "duration": video.duration,
                "size": video.size,
                "fps": video.fps,
                "audio": video.audio is not None
            }
            video.close()
            return info
        except Exception as e:
            logger.error(f"❌ Video info error: {e}")
            return {}
    
    def cleanup(self):
        try:
            import shutil
            shutil.rmtree(self.temp_dir)
            logger.info(f"✅ Cleaned temp directory: {self.temp_dir}")
        except Exception as e:
            logger.error(f"❌ Cleanup error: {e}")

# Global instance
video_editor = VideoEditor()
