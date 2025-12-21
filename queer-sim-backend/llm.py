from __future__ import annotations
from typing import Any, Dict, List, Optional
import numpy as np
import httpx
import os
from google import genai
from google.genai import types

class OllamaClient:
    def __init__(self, base_url: str, chat_model: str, embed_model: str):
        self.base_url = base_url.rstrip("/")
        self.chat_model = chat_model
        self.embed_model = embed_model

    async def chat(self, messages: List[Dict[str, str]], tools: Optional[List[Dict[str, Any]]] = None,
                   fmt: Optional[Any] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.chat_model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        if fmt is not None:
            payload["format"] = fmt

        timeout = httpx.Timeout(300.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                r = await client.post(f"{self.base_url}/api/chat", json=payload)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                print(f"Ollama chat error: {e}")
                raise e

    async def embed(self, texts: List[str]) -> List[np.ndarray]:
        timeout = httpx.Timeout(120.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                r = await client.post(f"{self.base_url}/api/embed", json={
                    "model": self.embed_model,
                    "input": texts,
                })
                r.raise_for_status()
                data = r.json()
                return [np.asarray(v, dtype=np.float32) for v in data["embeddings"]]
            except Exception as e:
                print(f"Ollama embed error: {e}")
                raise e

class GeminiClient:
    def __init__(self, api_key: str, model_name: str = "gemini-2.0-flash", embed_model: str = "text-embedding-004"):
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        self.embed_model = embed_model

    async def chat(self, messages: List[Dict[str, str]], tools: Optional[List[Any]] = None) -> Dict[str, Any]:
        # Convert to google-genai format if needed, but ADK handles this.
        # This is for manual use if needed.
        pass

    async def embed(self, texts: List[str]) -> List[np.ndarray]:
        # Google GenAI embed_content supports batching
        response = self.client.models.embed_content(
            model=self.embed_model,
            contents=texts
        )
        return [np.asarray(e.values, dtype=np.float32) for e in response.embeddings]
