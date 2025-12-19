import os
import re
import json
import hashlib
import numpy as np
import asyncio
from typing import Awaitable, Callable, Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict

_TIME_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})")

def _tc_to_seconds(tc: str) -> float:
    m = _TIME_RE.match(tc.strip())
    if not m:
        raise ValueError(f"Bad timecode: {tc}")
    hh, mm, ss, ms = map(int, m.groups())
    return hh * 3600 + mm * 60 + ss + (ms / 1000.0)

def _normalize_text(s: str) -> str:
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    return s

@dataclass
class RAGSeg:
    seg_id: str
    file_path: str
    text: str
    raw: str
    metadata: Dict[str, Any]

class RAGIndex:
    """
    Generalized vector index for multiple file types (.md, .txt, .srt).
    """
    def __init__(self, embed_fn: Callable[[List[str]], Awaitable[List[np.ndarray]]]):
        self._embed_fn = embed_fn
        self.segs: List[RAGSeg] = []
        self._emb: Optional[np.ndarray] = None

    @staticmethod
    def _fingerprint(segs: List[RAGSeg]) -> str:
        h = hashlib.sha256()
        for s in segs:
            h.update(s.seg_id.encode("utf-8"))
            h.update(b"\n")
            h.update(s.raw.encode("utf-8"))
            h.update(b"\n")
        return h.hexdigest()

    def _parse_srt(self, path: str, prefix: str = "SRT") -> List[RAGSeg]:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read().replace("\r\n", "\n").replace("\r", "\n")

        blocks = [b.strip() for b in content.split("\n\n") if b.strip()]
        out: List[RAGSeg] = []

        for b in blocks:
            lines = [ln.strip() for ln in b.split("\n") if ln.strip()]
            if len(lines) < 2:
                continue

            if "-->" in lines[0]:
                time_line = lines[0]
                text_lines = lines[1:]
                idx = len(out) + 1
            else:
                if len(lines) < 3 or "-->" not in lines[1]:
                    continue
                idx = int(lines[0]) if lines[0].isdigit() else (len(out) + 1)
                time_line = lines[1]
                text_lines = lines[2:]

            try:
                start_tc, end_tc = [t.strip() for t in time_line.split("-->")]
                raw = " ".join(text_lines).strip()
                if not raw:
                    continue

                text = _normalize_text(raw)
                seg_id = f"{prefix}-{idx:06d}"

                out.append(RAGSeg(
                    seg_id=seg_id,
                    file_path=path,
                    text=text,
                    raw=raw,
                    metadata={
                        "type": "srt",
                        "start_tc": start_tc,
                        "end_tc": end_tc,
                        "start_s": _tc_to_seconds(start_tc),
                        "end_s": _tc_to_seconds(end_tc)
                    }
                ))
            except Exception:
                continue

        return out

    def _parse_txt(self, path: str, prefix: str = "TXT") -> List[RAGSeg]:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        # Simple paragraph-based chunking
        chunks = [c.strip() for c in content.split("\n\n") if c.strip()]
        out: List[RAGSeg] = []

        for i, c in enumerate(chunks):
            text = _normalize_text(c)
            if not text:
                continue

            seg_id = f"{prefix}-{i:06d}"
            out.append(RAGSeg(
                seg_id=seg_id,
                file_path=path,
                text=text,
                raw=c,
                metadata={"type": "txt"}
            ))
        return out

    def _parse_md(self, path: str, prefix: str = "MD") -> List[RAGSeg]:
        # For now, treat .md same as .txt but could be improved
        return self._parse_txt(path, prefix)

    async def load_directory(
        self,
        directory: str,
        cache_dir: str = "data/rag_cache",
        batch_size: int = 64,
        force_rebuild: bool = False
    ) -> None:
        if not os.path.exists(directory):
            print(f"Directory {directory} does not exist.")
            return

        os.makedirs(cache_dir, exist_ok=True)
        dir_name = os.path.basename(directory.rstrip("/\\"))
        if not dir_name:
            dir_name = "root"

        segs: List[RAGSeg] = []
        for root, _, files in os.walk(directory):
            for file in files:
                path = os.path.join(root, file)
                prefix = hashlib.md5(path.encode()).hexdigest()[:8].upper()
                if file.endswith(".srt"):
                    segs.extend(self._parse_srt(path, prefix))
                elif file.endswith(".txt"):
                    segs.extend(self._parse_txt(path, prefix))
                elif file.endswith(".md"):
                    segs.extend(self._parse_md(path, prefix))

        if not segs:
            print(f"No valid files found in {directory}")
            self.segs = []
            self._emb = None
            return

        fp = self._fingerprint(segs)
        meta_path = os.path.join(cache_dir, f"{dir_name}.meta.json")
        emb_path = os.path.join(cache_dir, f"{dir_name}.emb.npy")
        seg_path = os.path.join(cache_dir, f"{dir_name}.segs.jsonl")

        # Cache hit?
        if not force_rebuild and os.path.exists(meta_path) and os.path.exists(emb_path) and os.path.exists(seg_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                if meta.get("fingerprint") == fp:
                    self.segs = []
                    with open(seg_path, "r", encoding="utf-8") as f:
                        for line in f:
                            d = json.loads(line)
                            self.segs.append(RAGSeg(**d))
                    self._emb = np.load(emb_path).astype(np.float32)
                    print(f"Loaded RAG index '{dir_name}' from cache: {len(self.segs)} segments")
                    return
            except Exception as e:
                print(f"Cache load failed for '{dir_name}': {e}, rebuilding...")

        # Build embeddings
        print(f"Building RAG index '{dir_name}' from {len(segs)} segments...")
        self.segs = segs
        texts = [s.text for s in self.segs]

        vecs: List[np.ndarray] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            print(f"Embedding batch {i//batch_size + 1}/{(len(texts) + batch_size - 1)//batch_size}...")
            batch_vecs = await self._embed_fn(batch)
            vecs.extend(batch_vecs)

        emb = np.stack(vecs, axis=0).astype(np.float32)
        # normalize for cosine via dot
        norms = np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9
        emb = emb / norms
        self._emb = emb

        # Save cache
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"fingerprint": fp, "count": len(self.segs)}, f, ensure_ascii=False)
        np.save(emb_path, self._emb)
        with open(seg_path, "w", encoding="utf-8") as f:
            for s in self.segs:
                f.write(json.dumps(asdict(s), ensure_ascii=False) + "\n")
        print(f"RAG index '{dir_name}' built and cached: {len(self.segs)} segments")

    async def search(self, query: str, k: int = 5) -> List[Tuple[float, RAGSeg]]:
        if self._emb is None or not self.segs:
            return []

        qv = (await self._embed_fn([_normalize_text(query)]))[0].astype(np.float32)
        qv = qv / (np.linalg.norm(qv) + 1e-9)

        scores = self._emb @ qv
        idxs = np.argsort(-scores)

        out: List[Tuple[float, RAGSeg]] = []
        for ix in idxs:
            out.append((float(scores[int(ix)]), self.segs[int(ix)]))
            if len(out) >= k:
                break
        return out

    async def search_frames_by_timestamp(self, timestamp_str: str, tolerance_seconds: float = 10.0) -> List[Tuple[float, RAGSeg]]:
        """Search for frames near a specific timestamp (e.g., "00:11:06,919" or "00:11:06")."""
        try:
            target_seconds = _tc_to_seconds(timestamp_str)
        except:
            # Try parsing without milliseconds
            try:
                if "," not in timestamp_str and "." not in timestamp_str:
                    timestamp_str = timestamp_str + ",000"
                elif "." in timestamp_str:
                    # Convert dot to comma for milliseconds
                    timestamp_str = timestamp_str.replace(".", ",", 1)
                target_seconds = _tc_to_seconds(timestamp_str)
            except Exception as e:
                print(f"Failed to parse timestamp '{timestamp_str}': {e}")
                return []

        # Search through frame caption segments
        matching_frames = []
        for seg in self.segs:
            if "captions.zh.txt" in seg.file_path or "frames" in seg.file_path:
                # Try to extract timestamp from the segment
                raw_text = seg.raw
                # Match format: "时间: 00:01:23,420 (83.42秒)"
                time_match = re.search(r'时间:\s*([\d:,\s]+)\s*\(([\d.]+)秒\)', raw_text)
                if time_match:
                    try:
                        frame_seconds = float(time_match.group(2))
                        # Check if within tolerance
                        distance = abs(frame_seconds - target_seconds)
                        if distance <= tolerance_seconds:
                            # Score based on how close to target (closer = higher score)
                            score = 1.0 / (1.0 + distance)  # Higher score for closer frames
                            matching_frames.append((score, seg))
                    except (ValueError, IndexError):
                        continue

        # Sort by score (closest first) and return
        matching_frames.sort(key=lambda x: -x[0])
        return matching_frames

    async def search_transcript_by_timestamp(self, timestamp_seconds: float, tolerance_seconds: float = 15.0) -> List[Tuple[float, RAGSeg]]:
        """Search for transcript lines near a specific timestamp in seconds."""
        matching_transcripts = []

        for seg in self.segs:
            if seg.metadata.get("type") == "srt":
                # SRT segments have start_s and end_s in metadata
                start_s = seg.metadata.get("start_s")
                end_s = seg.metadata.get("end_s")

                if start_s is not None:
                    try:
                        # Check if the timestamp is within the segment or close to it
                        segment_start = float(start_s)
                        segment_end = float(end_s) if end_s is not None else segment_start + 5.0

                        # Calculate distance to segment
                        if segment_start <= timestamp_seconds <= segment_end:
                            # Timestamp is within this segment - highest priority
                            distance = 0.0
                            score = 2.0  # Higher score for segments containing the timestamp
                        elif timestamp_seconds < segment_start:
                            # Timestamp is before this segment
                            distance = segment_start - timestamp_seconds
                            if distance <= tolerance_seconds:
                                score = 1.0 / (1.0 + distance)
                            else:
                                continue
                        else:
                            # Timestamp is after this segment
                            distance = timestamp_seconds - segment_end
                            if distance <= tolerance_seconds:
                                score = 1.0 / (1.0 + distance)
                            else:
                                continue

                        matching_transcripts.append((score, seg))
                    except (ValueError, TypeError) as e:
                        # Skip segments with invalid timestamps
                        continue

        # Sort by score (closest first) and return
        matching_transcripts.sort(key=lambda x: -x[0])
        return matching_transcripts

    @staticmethod
    def render_for_prompt(hits: List[Tuple[float, RAGSeg]], max_snips: int = 4, max_chars: int = 500) -> str:
        lines = []
        for score, s in hits[:max_snips]:
            txt = s.raw.strip()
            if len(txt) > max_chars:
                txt = txt[:max_chars].rstrip() + "…"

            meta = s.metadata
            if meta.get("type") == "srt":
                start_tc = meta.get("start_tc", "")
                end_tc = meta.get("end_tc", "")
                # Format for easy quoting: show timestamp and quote
                lines.append(f'"{txt}" ({start_tc}–{end_tc})')
            else:
                lines.append(f'- "{txt}" (File: {os.path.basename(s.file_path)})')

        return "\n".join(lines) if lines else "(no relevant knowledge base lines found)"

    @staticmethod
    def render_transcript_for_scene(hits: List[Tuple[float, RAGSeg]], max_lines: int = 6) -> str:
        """Render transcript lines specifically for scene discussion - more focused format."""
        srt_segments = []
        for score, s in hits:
            if s.metadata.get("type") != "srt":
                continue
            srt_segments.append((score, s))

        # Sort by timestamp (chronological order) for better context flow
        srt_segments.sort(key=lambda x: x[1].metadata.get("start_s", 0))

        lines = []
        for score, s in srt_segments[:max_lines]:
            txt = s.raw.strip()
            start_tc = s.metadata.get("start_tc", "")
            end_tc = s.metadata.get("end_tc", "")
            # Format: timestamp first, then quote (easier to reference)
            lines.append(f'{start_tc}: "{txt}"')

        return "\n".join(lines) if lines else "(no transcript lines found)"

    @staticmethod
    def extract_frame_info(hits: List[Tuple[float, RAGSeg]]) -> List[Dict[str, Any]]:
        """Extract frame information from RAG hits that contain frame captions."""
        frames = []
        for score, s in hits:
            # Check if this is a frame caption (from captions.zh.txt)
            file_path = s.file_path
            if "captions.zh.txt" in file_path or "frames" in file_path:
                # Parse the caption format: "时间: 00:00:01,760 (1.76秒) 帧文件: frames/000001.jpg"
                raw_text = s.raw.strip()
                import re
                # Extract timestamp and frame file
                time_match = re.search(r'时间:\s*([\d:,\s]+)\s*\(([\d.]+)秒\)', raw_text)
                frame_match = re.search(r'帧文件:\s*(frames/[^\s\n]+)', raw_text)
                if time_match and frame_match:
                    tc = time_match.group(1).strip()
                    ts_s = float(time_match.group(2))
                    frame_file = frame_match.group(1)
                    # Extract caption description
                    caption_match = re.search(r'画面描述:\s*(.+?)(?=\n\n|\n时间:|$)', raw_text, re.DOTALL)
                    caption = caption_match.group(1).strip() if caption_match else ""

                    frames.append({
                        "score": float(score),
                        "timestamp": tc,
                        "timestamp_seconds": ts_s,
                        "frame_file": frame_file,
                        "caption": caption,
                        "full_path": file_path
                    })
        return frames
