# =================== IMAGE PROCESSOR ===================
# Thumbnail generation and caching

from PIL import Image, ImageTk
import io
import win32clipboard
from functools import lru_cache
from typing import Optional
import config


class ImageProcessor:
    def __init__(self):
        self.thumbnail_cache = {}

    @lru_cache(maxsize=config.THUMBNAIL_CACHE_SIZE)
    def load_thumbnail(self, image_path: str, size: tuple = None) -> Optional[ImageTk.PhotoImage]:
        """Load and cache thumbnail image

        Args:
            image_path: Full path to image file
            size: Tuple of (width, height) for thumbnail size

        Returns:
            ImageTk.PhotoImage object or None if failed
        """
        if size is None:
            size = config.THUMBNAIL_SIZE

        try:
            # Load image
            img = Image.open(image_path)

            # Convert to RGB if necessary
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')

            # Create thumbnail (maintains aspect ratio)
            img.thumbnail(size, Image.Resampling.BILINEAR)

            # Convert to PhotoImage for Tkinter
            photo = ImageTk.PhotoImage(img)

            return photo

        except Exception as e:
            print(f"Error loading thumbnail for {image_path}: {e}")
            return None

    def load_full_image(self, image_path: str, max_size: tuple = (1200, 800)) -> Optional[ImageTk.PhotoImage]:
        """Load full-size image (scaled to fit display)

        Args:
            image_path: Full path to image file
            max_size: Maximum dimensions for display

        Returns:
            ImageTk.PhotoImage object or None if failed
        """
        try:
            # Load image
            img = Image.open(image_path)

            # Convert to RGB if necessary
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')

            # Calculate scaling to fit max_size while maintaining aspect ratio
            img_width, img_height = img.size
            max_width, max_height = max_size

            scale = min(max_width / img_width, max_height / img_height, 1.0)

            if scale < 1.0:
                new_size = (int(img_width * scale), int(img_height * scale))
                img = img.resize(new_size, Image.Resampling.BILINEAR)

            # Convert to PhotoImage for Tkinter
            photo = ImageTk.PhotoImage(img)

            return photo

        except Exception as e:
            print(f"Error loading full image {image_path}: {e}")
            return None

    def copy_image_to_clipboard(self, image_path: str) -> bool:
        """Copy image to Windows clipboard

        Args:
            image_path: Full path to image file

        Returns:
            True if successful, False otherwise
        """
        try:
            # Load image
            img = Image.open(image_path)

            # Convert to RGB (required for clipboard)
            if img.mode != 'RGB':
                img = img.convert('RGB')

            # Save to memory buffer as BMP (Windows clipboard format)
            output = io.BytesIO()
            img.save(output, 'BMP')
            data = output.getvalue()[14:]  # Remove BMP header (14 bytes)
            output.close()

            # Copy to clipboard
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
            win32clipboard.CloseClipboard()

            return True

        except Exception as e:
            print(f"Error copying image to clipboard: {e}")
            return False

    def copy_path_to_clipboard(self, path: str) -> bool:
        """Copy file path to clipboard

        Args:
            path: File path to copy

        Returns:
            True if successful, False otherwise
        """
        try:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(path, win32clipboard.CF_UNICODETEXT)
            win32clipboard.CloseClipboard()
            return True

        except Exception as e:
            print(f"Error copying path to clipboard: {e}")
            return False

    def clear_cache(self):
        """Clear thumbnail cache"""
        self.thumbnail_cache.clear()
        self.load_thumbnail.cache_clear()

    def get_image_info(self, image_path: str) -> dict:
        """Get image metadata

        Args:
            image_path: Full path to image file

        Returns:
            Dictionary with image info: {width, height, format, size_kb}
        """
        try:
            img = Image.open(image_path)
            width, height = img.size
            img_format = img.format

            import os
            size_kb = os.path.getsize(image_path) / 1024

            return {
                'width': width,
                'height': height,
                'format': img_format,
                'size_kb': round(size_kb, 2)
            }

        except Exception as e:
            print(f"Error getting image info: {e}")
            return {
                'width': 0,
                'height': 0,
                'format': 'Unknown',
                'size_kb': 0
            }
