from __future__ import annotations
from dataclasses import dataclass
from typing import Awaitable, Callable, List, Optional
import time
import numpy as np

@dataclass
class MemoryItem:
    ts: float
    text: str
    emb: np.ndarray

def cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9)
    return float(np.dot(a, b) / denom)

class MemoryStore:
    def __init__(self, embed_fn: Callable[[List[str]], Awaitable[List[np.ndarray]]], max_items: int = 2000):
        self._embed_fn = embed_fn
        self._items: List[MemoryItem] = []
        self._max_items = max_items

    async def add(self, text: str, ts: Optional[float] = None) -> None:
        ts = time.time() if ts is None else ts
        emb = (await self._embed_fn([text]))[0]
        self._items.append(MemoryItem(ts=ts, text=text, emb=emb))
        if len(self._items) > self._max_items:
            self._items = self._items[-self._max_items:]

    async def retrieve(self, query: str, k: int = 6) -> List[str]:
        if not self._items:
            return []
        qemb = (await self._embed_fn([query]))[0]
        now = time.time()

        scored = []
        for m in self._items[-300:]:
            sim = cosine(qemb, m.emb)
            # tiny recency bias so old stuff fades naturally
            age = max(0.0, now - m.ts)
            rec = np.exp(-age / (60 * 60 * 24 * 3))  # ~3-day half-ish
            scored.append((sim * (0.85 + 0.15 * rec), m.text))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in scored[:k]]
