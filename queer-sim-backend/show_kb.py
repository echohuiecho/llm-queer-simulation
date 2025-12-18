# show_kb.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, List, Optional, Tuple
import os, re, json, hashlib
import numpy as np

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

@dataclass(frozen=True)
class ShowSeg:
    seg_id: str          # stable id like "LO-E1P1-000123"
    episode: str         # e.g. "E1"
    part: str            # e.g. "P1"
    idx: int             # sequential index within file
    start_tc: str
    end_tc: str
    start_s: float
    end_s: float
    text: str            # normalized
    raw: str             # raw joined text

class ShowIndex:
    """
    Tiny in-memory vector index for subtitle segments (N is small).
    Stores normalized embeddings for fast cosine search.
    """
    def __init__(self, embed_fn: Callable[[List[str]], Awaitable[List[np.ndarray]]]):
        self._embed_fn = embed_fn
        self.segs: List[ShowSeg] = []
        self._emb: Optional[np.ndarray] = None  # (N, D) normalized float32

    @staticmethod
    def _fingerprint(segs: List[ShowSeg]) -> str:
        h = hashlib.sha256()
        for s in segs:
            h.update(s.seg_id.encode("utf-8"))
            h.update(b"\n")
            h.update(s.raw.encode("utf-8"))
            h.update(b"\n")
        return h.hexdigest()

    @staticmethod
    def _parse_srt(path: str, episode: str, part: str, prefix: str) -> List[ShowSeg]:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read().replace("\r\n", "\n").replace("\r", "\n")

        blocks = [b.strip() for b in content.split("\n\n") if b.strip()]
        out: List[ShowSeg] = []

        for b in blocks:
            lines = [ln.strip() for ln in b.split("\n") if ln.strip()]
            if len(lines) < 2:
                continue

            # Some SRTs have numeric line then time; some may not
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

            start_tc, end_tc = [t.strip() for t in time_line.split("-->")]
            raw = " ".join(text_lines).strip()
            if not raw:
                continue

            text = _normalize_text(raw)
            seg_id = f"{prefix}-{episode}{part}-{idx:06d}"

            out.append(
                ShowSeg(
                    seg_id=seg_id,
                    episode=episode,
                    part=part,
                    idx=idx,
                    start_tc=start_tc,
                    end_tc=end_tc,
                    start_s=_tc_to_seconds(start_tc),
                    end_s=_tc_to_seconds(end_tc),
                    text=text,
                    raw=raw,
                )
            )

        return out

    async def build_from_srt(
        self,
        srt_files: List[Tuple[str, str, str]],  # (path, episode, part)
        cache_dir: str = "data/show_cache",
        prefix: str = "LO",
        batch_size: int = 64,
    ) -> None:
        os.makedirs(cache_dir, exist_ok=True)

        segs: List[ShowSeg] = []
        for path, ep, part in srt_files:
            segs.extend(self._parse_srt(path, ep, part, prefix))

        fp = self._fingerprint(segs)
        meta_path = os.path.join(cache_dir, "show_index.meta.json")
        emb_path = os.path.join(cache_dir, "show_index.emb.npy")
        seg_path = os.path.join(cache_dir, "show_index.segs.jsonl")

        # Cache hit?
        if os.path.exists(meta_path) and os.path.exists(emb_path) and os.path.exists(seg_path):
            try:
                meta = json.load(open(meta_path, "r", encoding="utf-8"))
                if meta.get("fingerprint") == fp:
                    self.segs = []
                    with open(seg_path, "r", encoding="utf-8") as f:
                        for line in f:
                            d = json.loads(line)
                            self.segs.append(ShowSeg(**d))
                    self._emb = np.load(emb_path).astype(np.float32)
                    print(f"Loaded show index from cache: {len(self.segs)} segments")
                    return
            except Exception as e:
                print(f"Cache load failed: {e}, rebuilding...")

        # Build embeddings
        print(f"Building show index from {len(segs)} segments...")
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
        json.dump({"fingerprint": fp, "count": len(self.segs)}, open(meta_path, "w", encoding="utf-8"), ensure_ascii=False)
        np.save(emb_path, self._emb)
        with open(seg_path, "w", encoding="utf-8") as f:
            for s in self.segs:
                f.write(json.dumps(s.__dict__, ensure_ascii=False) + "\n")
        print(f"Show index built and cached: {len(self.segs)} segments")

    async def search(self, query: str, k: int = 5, episode: Optional[str] = None) -> List[Tuple[float, ShowSeg]]:
        if self._emb is None or not self.segs:
            return []

        qv = (await self._embed_fn([_normalize_text(query)]))[0].astype(np.float32)
        qv = qv / (np.linalg.norm(qv) + 1e-9)

        scores = self._emb @ qv  # (N,)
        idxs = np.argsort(-scores)

        out: List[Tuple[float, ShowSeg]] = []
        for ix in idxs:
            s = self.segs[int(ix)]
            if episode and s.episode != episode:
                continue
            out.append((float(scores[int(ix)]), s))
            if len(out) >= k:
                break
        return out

    def window(self, seg_id: str, before: int = 2, after: int = 2) -> List[ShowSeg]:
        # Return neighbors in same episode+part for better "scene" feel
        pos = next((i for i, s in enumerate(self.segs) if s.seg_id == seg_id), None)
        if pos is None:
            return []
        center = self.segs[pos]
        same = [s for s in self.segs if (s.episode == center.episode and s.part == center.part)]
        # find center in same list
        j = next((i for i, s in enumerate(same) if s.seg_id == seg_id), None)
        if j is None:
            return [center]
        lo = max(0, j - before)
        hi = min(len(same), j + after + 1)
        return same[lo:hi]

    @staticmethod
    def render_for_prompt(hits: List[Tuple[float, ShowSeg]], max_snips: int = 4, max_chars: int = 200) -> str:
        """
        Return short, quoteable snippets with the actual text as the primary citation.
        Keep snippets short (copyright-safe + prompt-efficient).
        """
        lines = []
        for score, s in hits[:max_snips]:
            txt = s.raw.strip()
            if len(txt) > max_chars:
                txt = txt[:max_chars].rstrip() + "…"
            # Format: quote text first, then timecode in parentheses
            lines.append(f'- "{txt}" ({s.episode}{s.part} {s.start_tc}–{s.end_tc})')
        return "\n".join(lines) if lines else "(no relevant subtitle lines found)"
