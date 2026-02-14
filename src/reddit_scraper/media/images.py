"""
Image handler - converts all images to AVIF losslessly (async version).
"""

import asyncio
import logging
from io import BytesIO
from typing import Optional

from PIL import Image

from .base import BaseMediaHandler, MediaConfig, ProcessingResult

logger = logging.getLogger(__name__)

try:
    logger.info("AVIF plugin loaded successfully")
except Exception as e:
    logger.warning(f"AVIF plugin failed to load: {e}")


class ImageHandler(BaseMediaHandler):
    """Handle image downloads and AVIF conversion (async)."""

    def __init__(self, subreddit: str):
        super().__init__(subreddit, "image")

    async def download_and_convert(self, url: str, item_id: str) -> ProcessingResult:
        """Download image and convert to AVIF losslessly."""
        try:
            avif_path = self.media_dir / f"{item_id}.avif"

            if await self.check_file_exists(avif_path):
                return ProcessingResult(
                    url=url, item_id=item_id, success=True, path=str(avif_path), skipped=True
                )

            # Download with retry logic
            image_data = await self.download_with_retry(url, timeout=MediaConfig.DOWNLOAD_TIMEOUT)
            if not image_data:
                return ProcessingResult(
                    url=url, item_id=item_id, success=False, error="Download failed after retries"
                )

            # CPU-bound conversion in thread pool
            result_path = await asyncio.to_thread(self._convert_to_avif, image_data, item_id)

            if result_path:
                self.logger.debug(f"Successfully converted: {result_path}")
                return ProcessingResult(url=url, item_id=item_id, success=True, path=result_path)
            else:
                return ProcessingResult(
                    url=url, item_id=item_id, success=False, error="Conversion failed"
                )

        except Exception as e:
            self.logger.error(f"Image processing failed for {url}: {e}")
            return ProcessingResult(url=url, item_id=item_id, success=False, error=str(e))

    def _convert_to_avif(self, image_data: bytes, item_id: str) -> Optional[str]:
        """Convert image data to AVIF losslessly with fallbacks (runs in thread)."""
        try:
            image = Image.open(BytesIO(image_data))

            if image.mode not in ["RGB", "RGBA", "L"]:
                if image.mode == "P" and "transparency" in image.info:
                    image = image.convert("RGBA")
                else:
                    image = image.convert("RGB")

            formats_to_try = [
                ("AVIF", ".avif", {"lossless": True}),
                ("WebP", ".webp", {"lossless": True, "quality": 100}),
                ("PNG", ".png", {"optimize": True}),
            ]

            for format_name, ext, save_kwargs in formats_to_try:
                try:
                    output_path = self.media_dir / f"{item_id}{ext}"
                    image.save(output_path, format_name, **save_kwargs)

                    if output_path.exists() and output_path.stat().st_size > 0:
                        self.logger.info(f"Converted to {format_name}: {output_path.name}")
                        return str(output_path)

                except Exception as format_error:
                    self.logger.debug(f"{format_name} conversion failed: {format_error}")
                    continue

            self.logger.warning("All conversions failed, saving original")
            return self._save_original(image_data, item_id)

        except Exception as e:
            self.logger.error(f"Image conversion failed: {e}")
            return self._save_original(image_data, item_id)

    def _save_original(self, image_data: bytes, item_id: str) -> Optional[str]:
        """Save original image data as fallback (runs in thread)."""
        try:
            image = Image.open(BytesIO(image_data))
            format_name = image.format.lower() if image.format else "jpg"

            format_map = {
                "jpeg": ".jpg",
                "png": ".png",
                "webp": ".webp",
                "gif": ".gif",
                "bmp": ".bmp",
            }

            ext = format_map.get(format_name, ".jpg")
            output_path = self.media_dir / f"{item_id}_original{ext}"

            with open(output_path, "wb") as f:
                f.write(image_data)

            self.logger.info(f"Saved original format: {output_path.name}")
            return str(output_path)

        except Exception as e:
            self.logger.error(f"Original save failed: {e}")
            return None

    async def batch_convert(self, url_id_pairs: list, max_concurrent: Optional[int] = None) -> dict:
        """Convert multiple images concurrently."""
        if max_concurrent is None:
            max_concurrent = MediaConfig.MAX_CONCURRENT_IMAGES

        result = await self.batch_process_with_progress(
            url_id_pairs, self.download_and_convert, max_concurrent, "Converting images"
        )

        return result.to_dict()
