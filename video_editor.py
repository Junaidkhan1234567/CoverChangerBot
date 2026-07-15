# video_editor.py
import os
import logging
import tempfile
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import cv2
import numpy as np
from moviepy.editor import VideoFileClip, TextClip, CompositeVideoClip, ImageClip, AudioFileClip, concatenate_videoclips
from moviepy.video.fx import resize, fadein, fadeout
from moviepy.video.VideoClip import ColorClip

logger = logging.getLogger(__name__)

class VideoEditor:
    """Advanced video editing capabilities - Complete Class"""
    
    def __init__(self):
        """Initialize video editor with temp directory"""
        self.temp_dir = tempfile.mkdtemp(prefix="video_editor_")
        logger.info(f"✅ Video Editor initialized at {self.temp_dir}")
        
        # Default settings
        self.default_font = 'Arial'
        self.default_font_size = 30
        self.default_opacity = 0.7
        
    # ═══════════════════════════════════════════════════════
    # WATERMARK FUNCTIONS
    # ═══════════════════════════════════════════════════════
    
    def add_watermark_to_video(self, video_path: str, watermark_text: str = None, 
                               watermark_image_path: str = None, 
                               position: str = "bottom-right",
                               opacity: float = 0.7,
                               font_size: int = 30,
                               font_color: str = "white",
                               margin_x: int = 20,
                               margin_y: int = 20) -> str:
        """
        Add watermark to video
        Supports both text and image watermarks
        """
        try:
            # Load video
            video = VideoFileClip(video_path)
            
            # Get video dimensions
            video_width, video_height = video.size
            
            # Create watermark
            if watermark_image_path and os.path.exists(watermark_image_path):
                # Image watermark
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
                # Text watermark
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
            
            # Composite video with watermark
            if watermark:
                final_video = CompositeVideoClip([video, watermark])
                
                # Save output
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
                
                # Cleanup
                video.close()
                if watermark:
                    watermark.close()
                final_video.close()
                
                logger.info(f"✅ Watermark added to video: {output_path}")
                return output_path
            
            logger.warning("⚠️ No watermark created, returning original video")
            return video_path
            
        except Exception as e:
            logger.error(f"❌ Watermark error: {e}")
            return video_path
    
    def _create_text_watermark(self, text: str, video_width: int, video_height: int,
                               position: str, font_size: int, font_color: str,
                               opacity: float, margin_x: int, margin_y: int):
        """Create text watermark clip with custom margins"""
        try:
            # Create text clip
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
            
            # Set duration same as video
            txt_clip = txt_clip.set_duration(None)
            
            # Get text dimensions
            text_width, text_height = txt_clip.size
            
            # Calculate position with margins
            pos_map = {
                "top-left": (margin_x, margin_y),
                "top-right": (video_width - text_width - margin_x, margin_y),
                "bottom-left": (margin_x, video_height - text_height - margin_y),
                "bottom-right": (video_width - text_width - margin_x, video_height - text_height - margin_y),
                "center": ((video_width - text_width) // 2, (video_height - text_height) // 2)
            }
            
            position_tuple = pos_map.get(position, pos_map["bottom-right"])
            txt_clip = txt_clip.set_position(position_tuple)
            
            # Set opacity
            txt_clip = txt_clip.set_opacity(opacity)
            
            return txt_clip
            
        except Exception as e:
            logger.error(f"❌ Text watermark creation error: {e}")
            return None
    
    def _create_image_watermark(self, image_path: str, video_width: int, video_height: int,
                                position: str, opacity: float, margin_x: int, margin_y: int):
        """Create image watermark clip"""
        try:
            # Load and resize image
            watermark_img = ImageClip(image_path)
            
            # Resize watermark (max 200px width or 15% of video)
            max_width = min(200, video_width * 0.15)
            aspect_ratio = watermark_img.size[1] / watermark_img.size[0] if watermark_img.size[0] > 0 else 1
            new_width = max_width
            new_height = max_width * aspect_ratio
            
            watermark_img = watermark_img.resize((new_width, new_height))
            
            # Set opacity
            watermark_img = watermark_img.set_opacity(opacity)
            
            # Position with margins
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
    # CAPTION FUNCTIONS
    # ═══════════════════════════════════════════════════════
    
    def add_captions_to_video(self, video_path: str, caption_text: str,
                             font_size: int = 40,
                             position: str = "bottom",
                             bg_color: str = "rgba(0,0,0,0.6)",
                             text_color: str = "white",
                             duration: int = None,
                             font: str = 'Arial',
                             stroke_width: int = 2) -> str:
        """
        Add captions/subtitles to video
        """
        try:
            video = VideoFileClip(video_path)
            video_duration = video.duration
            
            # Create caption clip
            caption_clip = TextClip(
                caption_text,
                fontsize=font_size,
                color=text_color,
                font=font,
                stroke_color='black',
                stroke_width=stroke_width,
                bg_color=bg_color,
                size=(video.size[0] * 0.9, None),
                method='caption'
            )
            
            # Position
            margin = 50
            pos_map = {
                "top": (video.size[0] // 2 - caption_clip.size[0] // 2, margin),
                "bottom": (video.size[0] // 2 - caption_clip.size[0] // 2, video.size[1] - caption_clip.size[1] - margin),
                "center": (video.size[0] // 2 - caption_clip.size[0] // 2, video.size[1] // 2 - caption_clip.size[1] // 2)
            }
            
            position_tuple = pos_map.get(position, pos_map["bottom"])
            caption_clip = caption_clip.set_position(position_tuple)
            
            # Set duration
            caption_clip = caption_clip.set_duration(duration or video_duration)
            
            # Composite
            final_video = CompositeVideoClip([video, caption_clip])
            
            # Save
            output_path = os.path.join(self.temp_dir, f"captioned_{int(datetime.now().timestamp())}.mp4")
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
            caption_clip.close()
            final_video.close()
            
            logger.info(f"✅ Captions added to video: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"❌ Caption error: {e}")
            return video_path

    def add_multiple_captions(self, video_path: str, captions: list) -> str:
        """
        Add multiple captions with timing
        captions: [{"text": "Hello", "start": 0, "duration": 2}, ...]
        """
        try:
            video = VideoFileClip(video_path)
            caption_clips = []
            
            for caption in captions:
                clip = TextClip(
                    caption["text"],
                    fontsize=40,
                    color='white',
                    font='Arial',
                    stroke_color='black',
                    stroke_width=2,
                    bg_color='rgba(0,0,0,0.6)',
                    size=(video.size[0] * 0.9, None),
                    method='caption'
                )
                
                clip = clip.set_position(('center', video.size[1] * 0.8))
                clip = clip.set_start(caption.get("start", 0))
                clip = clip.set_duration(caption.get("duration", 3))
                caption_clips.append(clip)
            
            # Composite all clips
            final_video = CompositeVideoClip([video] + caption_clips)
            
            output_path = os.path.join(self.temp_dir, f"multi_caption_{int(datetime.now().timestamp())}.mp4")
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
            
            final_video.close()
            logger.info(f"✅ Multiple captions added: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"❌ Multi-caption error: {e}")
            return video_path
    
    # ═══════════════════════════════════════════════════════
    # VIDEO EFFECTS FUNCTIONS
    # ═══════════════════════════════════════════════════════
    
    def add_fade_effects(self, video_path: str, fade_in_duration: float = 1.0, 
                         fade_out_duration: float = 1.0) -> str:
        """Add fade in and fade out effects"""
        try:
            video = VideoFileClip(video_path)
            video = video.fx(fadein, fade_in_duration).fx(fadeout, fade_out_duration)
            
            output_path = os.path.join(self.temp_dir, f"fade_{int(datetime.now().timestamp())}.mp4")
            video.write_videofile(
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
            logger.info(f"✅ Fade effects added: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"❌ Fade effect error: {e}")
            return video_path
    
    def resize_video(self, video_path: str, target_width: int = None, 
                     target_height: int = None, aspect_ratio: str = "keep") -> str:
        """Resize video to target dimensions"""
        try:
            video = VideoFileClip(video_path)
            orig_width, orig_height = video.size
            
            if aspect_ratio == "keep":
                if target_width:
                    target_height = int(target_width * orig_height / orig_width)
                elif target_height:
                    target_width = int(target_height * orig_width / orig_height)
            
            video = video.resize((target_width, target_height))
            
            output_path = os.path.join(self.temp_dir, f"resized_{int(datetime.now().timestamp())}.mp4")
            video.write_videofile(
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
            logger.info(f"✅ Video resized: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"❌ Resize error: {e}")
            return video_path
    
    # ═══════════════════════════════════════════════════════
    # PREVIEW FUNCTIONS
    # ═══════════════════════════════════════════════════════
    
    def create_watermark_preview(self, video_path: str, watermark_text: str = "© Video Cover Bot") -> str:
        """Create a preview showing watermark at all positions"""
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
            
            # Shorten video to 10 seconds for preview
            if video.duration > 10:
                video = video.subclip(0, 10)
            
            watermark_clips = []
            
            # Create a separate watermark for each position
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
            
            # Composite all watermarks
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
    
    # ═══════════════════════════════════════════════════════
    # UTILITY FUNCTIONS
    # ═══════════════════════════════════════════════════════
    
    def get_video_info(self, video_path: str) -> dict:
        """Get video information"""
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
        """Clean temporary files"""
        try:
            import shutil
            shutil.rmtree(self.temp_dir)
            logger.info(f"✅ Cleaned temp directory: {self.temp_dir}")
        except Exception as e:
            logger.error(f"❌ Cleanup error: {e}")

# Global instance
video_editor = VideoEditor()
