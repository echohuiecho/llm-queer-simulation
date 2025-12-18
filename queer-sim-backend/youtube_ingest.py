import os
import asyncio
import json
import re
import hashlib
import uuid
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
import yt_dlp
from faster_whisper import WhisperModel
from openai import AsyncOpenAI
from langdetect import detect
import subprocess

@dataclass
class YouTubeJob:
    job_id: str
    dir_name: str
    urls: List[str]
    status: str  # "pending", "running", "completed", "failed"
    progress: float  # 0 to 100
    current_url: Optional[str] = None
    errors: List[str] = None
    results: List[Dict[str, Any]] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.results is None:
            self.results = []

class YouTubeIngestManager:
    def __init__(self, config: Any, rag_index: Any):
        self.config = config
        self.rag_index = rag_index
        self.jobs: Dict[str, YouTubeJob] = {}
        self.openai_client = None

        # Check for OpenAI API key
        api_key = self.config.get("openai_api_key", "").strip()
        if api_key:
            base_url = self.config.get("openai_base_url", "https://api.openai.com/v1")
            self.openai_client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url
            )
            print(f"YouTube ingest: OpenAI API configured (base_url: {base_url})")
        else:
            print("YouTube ingest: OpenAI API key not found. Frame captioning will be skipped.")
            print("  Set OPENAI_API_KEY in .env file or config.json to enable frame captioning.")

    def _get_video_id(self, url: str) -> str:
        # Simple extraction for youtube.com/watch?v=, youtu.be/, youtube.com/shorts/
        patterns = [
            r"v=([a-zA-Z0-9_-]{11})",
            r"youtu\.be/([a-zA-Z0-9_-]{11})",
            r"shorts/([a-zA-Z0-9_-]{11})"
        ]
        for p in patterns:
            m = re.search(p, url)
            if m:
                return m.group(1)
        # Fallback to a hash if not found
        return hashlib.md5(url.encode()).hexdigest()[:11]

    async def create_job(self, dir_name: str, urls: List[str]) -> str:
        job_id = str(uuid.uuid4())
        job = YouTubeJob(
            job_id=job_id,
            dir_name=dir_name,
            urls=urls,
            status="pending",
            progress=0
        )
        self.jobs[job_id] = job
        asyncio.create_task(self.run_job(job_id))
        return job_id

    async def run_job(self, job_id: str):
        job = self.jobs.get(job_id)
        if not job:
            return

        job.status = "running"
        total_urls = len(job.urls)

        target_kb_dir = os.path.join("data/rag", job.dir_name)
        if not os.path.exists(target_kb_dir):
            job.status = "failed"
            job.errors.append(f"Directory {job.dir_name} not found")
            return

        # Each URL has 5 steps: download, transcribe, translate, extract frames, caption
        steps_per_url = 5

        for i, url in enumerate(job.urls):
            job.current_url = url
            base_progress = (i / total_urls) * 100
            step_progress = 100 / total_urls / steps_per_url

            try:
                video_id = self._get_video_id(url)
                video_dir = os.path.join(target_kb_dir, "youtube", video_id)
                os.makedirs(video_dir, exist_ok=True)

                # 1. Download (0-20% of this URL)
                print(f"[{i+1}/{total_urls}] Downloading video: {url}")
                job.progress = base_progress + step_progress * 0
                mp4_path, srt_path = await self._download_video(url, video_dir)
                job.progress = base_progress + step_progress * 1

                # 2. Transcribe if needed (20-40% of this URL)
                if not srt_path or not os.path.exists(srt_path):
                    print(f"[{i+1}/{total_urls}] Transcribing with Whisper large-v3 (this may take several minutes for long videos)...")
                    job.progress = base_progress + step_progress * 1
                    srt_path = await self._transcribe_video(mp4_path, video_dir)
                    print(f"[{i+1}/{total_urls}] Transcription complete")
                else:
                    print(f"[{i+1}/{total_urls}] Using existing subtitles")
                job.progress = base_progress + step_progress * 2

                # 3. Translate if needed (40-60% of this URL)
                print(f"[{i+1}/{total_urls}] Translating transcript to Chinese...")
                job.progress = base_progress + step_progress * 2
                srt_zh_path = await self._translate_srt(srt_path, video_dir)
                job.progress = base_progress + step_progress * 3

                # 4. Extract frames (60-80% of this URL)
                print(f"[{i+1}/{total_urls}] Extracting scene frames...")
                job.progress = base_progress + step_progress * 3
                frames_dir = os.path.join(video_dir, "frames")
                os.makedirs(frames_dir, exist_ok=True)
                frame_index_path = await self._extract_frames(mp4_path, frames_dir)
                job.progress = base_progress + step_progress * 4

                # 5. Caption frames (80-100% of this URL)
                print(f"[{i+1}/{total_urls}] Captioning frames with GPT vision...")
                job.progress = base_progress + step_progress * 4
                captions_path = await self._caption_frames(frames_dir, frame_index_path, video_dir)
                job.progress = base_progress + step_progress * 5

                print(f"Completed processing video {i+1}/{total_urls}: {url}")
                job.results.append({
                    "url": url,
                    "video_id": video_id,
                    "srt_zh": srt_zh_path,
                    "captions": captions_path
                })

            except Exception as e:
                job.errors.append(f"Error processing {url}: {str(e)}")
                print(f"YouTube ingest error for {url}: {e}")

        job.progress = 100
        job.status = "completed"
        job.current_url = None

        # Trigger RAG rebuild
        await self.rag_index.load_directory(target_kb_dir, force_rebuild=True)

    async def _download_video(self, url: str, video_dir: str) -> tuple[str, Optional[str]]:
        def _run_download():
            mp4_path = None
            srt_path = None

            # Step 1: Download video first (without subtitles to avoid errors blocking video download)
            ydl_opts_video = {
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'outtmpl': os.path.join(video_dir, 'video.%(ext)s'),
                'writesubtitles': False,
                'writeautomaticsub': False,
                'skip_download': False,
                'quiet': True,
            }

            try:
                with yt_dlp.YoutubeDL(ydl_opts_video) as ydl:
                    info = ydl.extract_info(url, download=True)

                    # Find the video file
                    mp4_path = os.path.join(video_dir, 'video.mp4')
                    if not os.path.exists(mp4_path):
                        for f in os.listdir(video_dir):
                            if f.startswith('video.') and f.endswith(('.mp4', '.mkv', '.webm')):
                                mp4_path = os.path.join(video_dir, f)
                                break
            except Exception as e:
                raise Exception(f"Failed to download video: {e}")

            if not mp4_path or not os.path.exists(mp4_path):
                raise Exception(f"Video file not found after download for {url}")

            # Step 2: Try to download subtitles separately (this is optional, failures are OK)
            ydl_opts_subs = {
                'format': 'best',  # We already have video, just need subtitles
                'outtmpl': os.path.join(video_dir, 'video.%(ext)s'),
                'writesubtitles': True,
                'writeautomaticsub': True,
                'subtitleslangs': ['zh-Hans', 'zh-Hant', 'zh', 'en'],
                'subtitlesformat': 'srt',
                'skip_download': True,  # Don't re-download video
                'quiet': True,
            }

            try:
                with yt_dlp.YoutubeDL(ydl_opts_subs) as ydl:
                    # This will only download subtitles, not the video
                    ydl.extract_info(url, download=True)
            except Exception as sub_error:
                # Subtitle download failure is OK - we'll use Whisper
                error_str = str(sub_error)
                if '429' in error_str or 'Too Many Requests' in error_str:
                    print(f"Subtitle download rate-limited for {url}. Will use Whisper transcription.")
                else:
                    print(f"Subtitle download failed for {url}: {error_str}. Will use Whisper transcription.")

            # Check if subtitle files were downloaded
            for f in os.listdir(video_dir):
                if f.endswith('.srt'):
                    potential_srt = os.path.join(video_dir, f)
                    # Verify it's a valid subtitle file
                    try:
                        with open(potential_srt, 'r', encoding='utf-8') as sf:
                            content = sf.read().strip()
                            if len(content) > 50:  # Reasonable minimum size
                                srt_path = potential_srt
                                break
                    except Exception:
                        continue
                elif f.endswith('.vtt') and srt_path is None:
                    # Convert VTT to SRT
                    vtt_path = os.path.join(video_dir, f)
                    try:
                        with open(vtt_path, 'r', encoding='utf-8') as vf:
                            vtt_content = vf.read()
                        if len(vtt_content.strip()) > 50:
                            srt_path = vtt_path.replace('.vtt', '.srt')
                            # Simple VTT to SRT conversion
                            srt_content = re.sub(r'(\d{2}):(\d{2}):(\d{2})\.(\d{3})', r'\1:\2:\3,\4', vtt_content)
                            srt_content = re.sub(r'<[^>]+>', '', srt_content)
                            with open(srt_path, 'w', encoding='utf-8') as sf:
                                sf.write(srt_content)
                            break
                    except Exception:
                        continue

            return mp4_path, srt_path

        return await asyncio.to_thread(_run_download)

    async def _transcribe_video(self, mp4_path: str, video_dir: str) -> str:
        # Check if transcript already exists
        existing_transcript = os.path.join(video_dir, "transcript.srt")
        if os.path.exists(existing_transcript) and os.path.getsize(existing_transcript) > 100:
            print(f"Found existing transcript, using it: {existing_transcript}")
            return existing_transcript

        # Use faster-whisper
        model_size = "large-v3"
        print(f"Loading Whisper model '{model_size}' (first time may download ~3GB, subsequent loads take ~10-30s)...")

        # Run in a thread pool as it's blocking
        def _run():
            try:
                model = WhisperModel(model_size, device="cpu", compute_type="int8") # Use CPU/int8 for safety in dev env
                print(f"Model loaded. Starting transcription of {mp4_path}...")
                print("Note: Transcription can take 5-30+ minutes depending on video length and CPU speed.")
                segments, info = model.transcribe(mp4_path, beam_size=5)

                print("Transcription complete. Writing segments to SRT file...")
                srt_path = os.path.join(video_dir, "transcript.srt")
                with open(srt_path, "w", encoding="utf-8") as f:
                    segment_count = 0
                    for i, segment in enumerate(segments):
                        start = self._format_timestamp(segment.start)
                        end = self._format_timestamp(segment.end)
                        f.write(f"{i+1}\n{start} --> {end}\n{segment.text.strip()}\n\n")
                        segment_count += 1
                        if segment_count % 100 == 0:
                            print(f"  Written {segment_count} segments so far...")

                print(f"SRT file written with {segment_count} segments: {srt_path}")
                return srt_path
            except Exception as e:
                print(f"Error during Whisper transcription: {e}")
                raise

        return await asyncio.to_thread(_run)

    def _format_timestamp(self, seconds: float) -> str:
        td = time.gmtime(seconds)
        ms = int((seconds % 1) * 1000)
        return f"{time.strftime('%H:%M:%S', td)},{ms:03d}"

    async def _translate_srt(self, srt_path: str, video_dir: str) -> str:
        # Read SRT, detect language
        if not srt_path or not os.path.exists(srt_path):
            raise ValueError("No SRT to translate")

        with open(srt_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Simple detection (might be biased by timecodes, so let's strip them for detection)
        text_only = re.sub(r'\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}', '', content)
        text_only = re.sub(r'^\d+$', '', text_only, flags=re.MULTILINE)

        try:
            lang = detect(text_only)
        except:
            lang = "unknown"

        if lang == "zh-cn" or lang == "zh-tw":
            # Already Chinese, just copy to transcript.zh.srt
            zh_path = os.path.join(video_dir, "transcript.zh.srt")
            with open(zh_path, "w", encoding="utf-8") as f:
                f.write(content)
            return zh_path

        if not self.openai_client:
            # Fallback: if no OpenAI, just use original
            zh_path = os.path.join(video_dir, "transcript.zh.srt")
            with open(zh_path, "w", encoding="utf-8") as f:
                f.write(content)
            return zh_path

        # Translate using GPT-5.2
        zh_path = os.path.join(video_dir, "transcript.zh.srt")

        # Parse SRT blocks
        blocks = content.split("\n\n")
        translated_blocks = []

        # Batch blocks to save requests
        batch_size = 20
        for i in range(0, len(blocks), batch_size):
            batch = blocks[i:i+batch_size]
            prompt = "Translate the following SRT subtitles to Simplified Chinese. Keep the timestamps and indices exactly as they are. Return only the translated SRT content.\n\n"
            prompt += "\n\n".join(batch)

            response = await self.openai_client.chat.completions.create(
                model=self.config.get("openai_translate_model", "gpt-4o"),
                messages=[{"role": "user", "content": prompt}]
            )
            translated_blocks.append(response.choices[0].message.content.strip())

        with open(zh_path, "w", encoding="utf-8") as f:
            f.write("\n\n".join(translated_blocks))

        return zh_path

    async def _extract_frames(self, mp4_path: str, frames_dir: str) -> str:
        threshold = self.config.get("youtube_frame_scene_threshold", 0.3)
        # ffmpeg -i video.mp4 -filter:v "select='gt(scene,0.3)',showinfo" -vsync vfr frames/%06d.jpg
        # We need to capture showinfo to get timestamps
        cmd = [
            'ffmpeg', '-i', mp4_path,
            '-filter:v', f"select='gt(scene,{threshold})',showinfo",
            '-vsync', 'vfr',
            os.path.join(frames_dir, '%06d.jpg'),
            '-y'
        ]

        process = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True)
        _, stderr = process.communicate()

        # Parse stderr for timestamps and frame numbers
        # Example line: [Parsed_showinfo_1 @ 0x...] n:   0 pts: 2127127 pts_time:83.0909 pos:  8458774 fmt:yuv420p sar:1/1 s:1920x1080 i:P iskey:1 type:I checksum:0A1B2C3D plane_checksum:[...]
        # Extract both frame number (n:) and timestamp (pts_time:)
        frame_data = []
        for line in stderr.split('\n'):
            # Match lines with both frame number and timestamp
            match = re.search(r'n:\s*(\d+).*?pts_time:([\d.]+)', line)
            if match:
                frame_num = int(match.group(1))
                timestamp = float(match.group(2))
                frame_data.append((frame_num, timestamp))

        # Sort by frame number to match with actual files
        frame_data.sort(key=lambda x: x[0])

        # Get list of actual frame files
        actual_frames = sorted([f for f in os.listdir(frames_dir) if f.endswith('.jpg')])

        index_path = os.path.join(frames_dir, "index.jsonl")
        with open(index_path, "w", encoding="utf-8") as f:
            # Match frame data with actual files
            for idx, frame_file in enumerate(actual_frames):
                if idx < len(frame_data):
                    _, ts_f = frame_data[idx]
                    tc = self._format_timestamp(ts_f)
                    f.write(json.dumps({
                        "file": f"frames/{frame_file}",
                        "ts_s": ts_f,
                        "tc": tc
                    }, ensure_ascii=False) + "\n")
                else:
                    # If we have more files than timestamps, try to estimate from filename
                    # Frame files are numbered sequentially, so we can estimate timestamp
                    # But this is less accurate - better to have matching count
                    print(f"Warning: More frame files than timestamps. Frame {frame_file} may have incorrect timestamp.")

        print(f"Created frame index with {len(actual_frames)} frames: {index_path}")
        return index_path

    async def _caption_frames(self, frames_dir: str, index_path: str, video_dir: str) -> str:
        captions_path = os.path.join(frames_dir, "captions.zh.txt")

        if not self.openai_client:
            # Create empty file with note if OpenAI is not configured
            with open(captions_path, "w", encoding="utf-8") as f_out:
                f_out.write("# Frame captions require OpenAI API key to be configured.\n")
                f_out.write("# Set OPENAI_API_KEY in config.json to enable frame captioning.\n\n")
            print(f"OpenAI API not configured. Skipping frame captioning. Created placeholder: {captions_path}")
            return captions_path

        if not os.path.exists(index_path):
            print(f"Frame index not found: {index_path}. Skipping captioning.")
            with open(captions_path, "w", encoding="utf-8") as f_out:
                f_out.write("# Frame index not found. No captions available.\n")
            return captions_path

        frame_count = 0
        with open(index_path, "r", encoding="utf-8") as f_idx, open(captions_path, "w", encoding="utf-8") as f_out:
            for line_num, line in enumerate(f_idx, 1):
                try:
                    data = json.loads(line.strip())
                    # Extract just the filename from "frames/000001.jpg"
                    frame_filename = os.path.basename(data["file"])
                    frame_path = os.path.join(frames_dir, frame_filename)

                    if not os.path.exists(frame_path):
                        print(f"Warning: Frame file not found: {frame_path}. Skipping.")
                        continue

                    # Call GPT Vision
                    import base64
                    with open(frame_path, "rb") as image_file:
                        base64_image = base64.b64encode(image_file.read()).decode('utf-8')

                    response = await self.openai_client.chat.completions.create(
                        model=self.config.get("openai_vision_model", "gpt-4o"),
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": "用简体中文简短描述这张视频帧的内容。"},
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/jpeg;base64,{base64_image}"
                                        }
                                    }
                                ]
                            }
                        ]
                    )
                    caption = response.choices[0].message.content.strip()

                    # Write caption with timestamp and frame reference for RAG
                    f_out.write(f"时间: {data['tc']} ({data['ts_s']:.2f}秒) 帧文件: {data['file']}\n")
                    f_out.write(f"画面描述: {caption}\n\n")
                    frame_count += 1

                    if frame_count % 10 == 0:
                        print(f"  Captioned {frame_count} frames so far...")

                except json.JSONDecodeError as e:
                    print(f"Error parsing JSON on line {line_num} of {index_path}: {e}")
                    continue
                except Exception as e:
                    print(f"Error captioning frame {line_num}: {e}")
                    continue

        print(f"Frame captioning complete. Created {captions_path} with {frame_count} frame captions.")
        return captions_path
