"""
Video handler - async version for Reddit videos with quality selection.
"""

import asyncio
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from .base import BaseMediaHandler, MediaConfig, ProcessingResult


class VideoHandler(BaseMediaHandler):
    """Handle Reddit video downloads with quality selection (async)."""

    def __init__(self, subreddit: str):
        super().__init__(subreddit, "video")

    async def download_and_process(self, video_url: str, item_id: str) -> ProcessingResult:
        """Download and process Reddit video."""
        try:
            output_path = self.media_dir / f"video_{item_id}.webm"

            if await self.check_file_exists(output_path):
                return ProcessingResult(
                    url=video_url,
                    item_id=item_id,
                    success=True,
                    path=str(output_path),
                    skipped=True,
                )

            self.logger.debug(f"Processing video: {video_url}")

            # Get best quality streams
            video_stream_url, audio_stream_url = await self._get_best_streams(video_url)

            if not video_stream_url:
                return ProcessingResult(
                    url=video_url, item_id=item_id, success=False, error="No video stream found"
                )

            # Process based on available streams
            if audio_stream_url:
                self.logger.debug("Found video + audio streams, merging...")
                result_path = await self._merge_video_audio(
                    video_stream_url, audio_stream_url, output_path
                )
            else:
                self.logger.debug("Video-only stream, converting...")
                result_path = await self._convert_video_only(video_stream_url, output_path)

            if result_path:
                return ProcessingResult(
                    url=video_url, item_id=item_id, success=True, path=result_path
                )
            else:
                return ProcessingResult(
                    url=video_url, item_id=item_id, success=False, error="FFmpeg processing failed"
                )

        except Exception as e:
            self.logger.error(f"Video processing failed for {video_url}: {e}")
            return ProcessingResult(url=video_url, item_id=item_id, success=False, error=str(e))

    async def _get_best_streams(self, video_url: str) -> Tuple[Optional[str], Optional[str]]:
        """Extract best quality video and audio streams."""
        try:
            if "v.redd.it" in video_url and not video_url.endswith((".mp4", ".mpd")):
                base_url = video_url.rstrip("/")
                dash_url = f"{base_url}/DASHPlaylist.mpd"

                if await self._url_exists(dash_url):
                    self.logger.debug(f"Found DASH manifest: {dash_url}")
                    return await self._parse_dash_playlist(dash_url)

                # Try direct quality URLs
                for quality in ["DASH_1080.mp4", "DASH_720.mp4", "DASH_480.mp4"]:
                    test_url = f"{base_url}/{quality}"
                    if await self._url_exists(test_url):
                        audio_url = await self._find_audio_stream(test_url)
                        return test_url, audio_url

                return None, None

            elif video_url.endswith(".mpd") or "DASHPlaylist" in video_url:
                return await self._parse_dash_playlist(video_url)

            else:
                return video_url, None

        except Exception as e:
            self.logger.error(f"Stream extraction error: {e}")
            return video_url, None

    async def _parse_dash_playlist(self, dash_url: str) -> Tuple[Optional[str], Optional[str]]:
        """Parse DASH manifest for best streams."""
        try:
            response = await asyncio.to_thread(
                self.session.get, dash_url, timeout=MediaConfig.DASH_TIMEOUT
            )
            response.raise_for_status()
            content = response.content

            root = ET.fromstring(content)
            base_url = self._get_base_url(dash_url)

            video_streams = []
            audio_streams = []

            adaptation_sets = root.findall(".//{urn:mpeg:dash:schema:mpd:2011}AdaptationSet")

            for adaptation_set in adaptation_sets:
                content_type = adaptation_set.get("contentType", "").lower()
                representations = adaptation_set.findall(
                    ".//{urn:mpeg:dash:schema:mpd:2011}Representation"
                )

                for representation in representations:
                    media_url = self._extract_media_url(representation, base_url)

                    if media_url:
                        if "video" in content_type:
                            height = representation.get("height")
                            quality = int(height) if height else 480
                            video_streams.append((quality, media_url))
                        elif "audio" in content_type:
                            audio_streams.append(media_url)

            best_video = max(video_streams, key=lambda x: x[0])[1] if video_streams else None
            best_audio = audio_streams[0] if audio_streams else None

            self.logger.debug(f"Selected video: {best_video}, audio: {best_audio}")
            return best_video, best_audio

        except Exception as e:
            self.logger.error(f"DASH parsing failed: {e}")
            return None, None

    def _get_base_url(self, dash_url: str) -> str:
        """Get base URL for relative paths."""
        parsed = urlparse(dash_url)
        return f"{parsed.scheme}://{parsed.netloc}{'/'.join(parsed.path.split('/')[:-1])}/"

    def _extract_media_url(self, representation, base_url: str) -> Optional[str]:
        """Extract media URL from DASH representation."""
        try:
            base_url_elem = representation.find(".//{urn:mpeg:dash:schema:mpd:2011}BaseURL")
            if base_url_elem is not None and base_url_elem.text:
                return urljoin(base_url, base_url_elem.text.strip())

            representation_id = representation.get("id", "")
            height = representation.get("height")

            if "audio" in representation_id.lower():
                return urljoin(base_url, "DASH_audio.mp4")
            elif height:
                return urljoin(base_url, f"DASH_{height}.mp4")

            return None

        except Exception:
            return None

    async def _find_audio_stream(self, video_url: str) -> Optional[str]:
        """Find corresponding audio stream."""
        try:
            parsed = urlparse(video_url)

            if "DASH_" in parsed.path:
                base_path = parsed.path.split("DASH_")[0]
                base_url = f"{parsed.scheme}://{parsed.netloc}{base_path}"

                for audio_format in [
                    "DASH_audio.mp4",
                    "DASH_AUDIO_128.mp4",
                    "DASH_128.mp4",
                    "audio",
                ]:
                    audio_url = f"{base_url}{audio_format}"
                    if await self._url_exists(audio_url):
                        self.logger.debug(f"Found audio stream: {audio_url}")
                        return audio_url

            return None

        except Exception:
            return None

    async def _url_exists(self, url: str) -> bool:
        """Check if URL exists."""
        try:
            response = await asyncio.to_thread(
                self.session.head, url, timeout=MediaConfig.HEAD_REQUEST_TIMEOUT
            )
            return response.status_code == 200
        except Exception:
            return False

    async def _merge_video_audio(
        self, video_url: str, audio_url: str, output_path: Path
    ) -> Optional[str]:
        """Merge video and audio streams (runs in thread)."""
        return await asyncio.to_thread(self._merge_sync, video_url, audio_url, output_path)

    def _merge_sync(self, video_url: str, audio_url: str, output_path: Path) -> Optional[str]:
        """Synchronous FFmpeg merge."""
        try:
            cmd = [
                "ffmpeg",
                "-i",
                video_url,
                "-i",
                audio_url,
                "-c:v",
                "libvpx-vp9",
                "-crf",
                str(MediaConfig.VIDEO_CRF),
                "-b:v",
                "0",
                "-row-mt",
                "1",
                "-cpu-used",
                str(MediaConfig.VIDEO_CPU_USED),
                "-c:a",
                "libopus",
                "-b:a",
                MediaConfig.AUDIO_BITRATE,
                "-shortest",
                "-threads",
                "0",
                "-y",
                str(output_path),
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

            if result.returncode == 0 and output_path.exists():
                file_size = output_path.stat().st_size
                self.logger.info(
                    f"Video+Audio merge complete: {output_path.name} ({file_size:,} bytes)"
                )
                return str(output_path)
            else:
                self.logger.error(f"Merge failed: {result.stderr}")
                return None

        except subprocess.TimeoutExpired:
            self.logger.error(f"Video merge timeout for {output_path.name}")
            return None
        except Exception as e:
            self.logger.error(f"Merge error: {e}")
            return None

    async def _convert_video_only(self, video_url: str, output_path: Path) -> Optional[str]:
        """Convert video-only stream (runs in thread)."""
        return await asyncio.to_thread(self._convert_sync, video_url, output_path)

    def _convert_sync(self, video_url: str, output_path: Path) -> Optional[str]:
        """Synchronous FFmpeg conversion."""
        try:
            cmd = [
                "ffmpeg",
                "-i",
                video_url,
                "-c:v",
                "libvpx-vp9",
                "-crf",
                str(MediaConfig.VIDEO_CRF),
                "-b:v",
                "0",
                "-row-mt",
                "1",
                "-cpu-used",
                str(MediaConfig.VIDEO_CPU_USED),
                "-an",
                "-threads",
                "0",
                "-y",
                str(output_path),
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            if result.returncode == 0 and output_path.exists():
                file_size = output_path.stat().st_size
                self.logger.info(
                    f"Video conversion complete: {output_path.name} ({file_size:,} bytes)"
                )
                return str(output_path)
            else:
                self.logger.error(f"Conversion failed: {result.stderr}")
                return None

        except subprocess.TimeoutExpired:
            self.logger.error(f"Video conversion timeout for {output_path.name}")
            return None
        except Exception as e:
            self.logger.error(f"Conversion error: {e}")
            return None

    async def batch_process(
        self, url_id_pairs: List[tuple], max_concurrent: Optional[int] = None
    ) -> dict:
        """Process multiple videos concurrently."""
        if max_concurrent is None:
            max_concurrent = MediaConfig.MAX_CONCURRENT_VIDEOS

        result = await self.batch_process_with_progress(
            url_id_pairs, self.download_and_process, max_concurrent
        )

        return result.to_dict()
