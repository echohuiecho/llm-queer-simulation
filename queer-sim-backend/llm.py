from __future__ import annotations
from typing import Any, Dict, List, Optional
import numpy as np
import httpx

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
            payload["format"] = fmt  # can be "json" or a JSON schema on newer Ollama builds

        # Increased timeout to 300 seconds (5 minutes) for large models
        timeout = httpx.Timeout(300.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                r = await client.post(f"{self.base_url}/api/chat", json=payload)
                r.raise_for_status()
                return r.json()
            except httpx.TimeoutException as e:
                print(f"Ollama chat timeout: {e}")
                raise RuntimeError(f"Ollama chat request timed out after 300s. Is Ollama running? Model: {self.chat_model}") from e
            except httpx.ConnectError as e:
                print(f"Ollama connection error: {e}")
                raise RuntimeError(f"Cannot connect to Ollama at {self.base_url}. Is Ollama running?") from e
            except httpx.HTTPStatusError as e:
                print(f"Ollama HTTP error: {e.response.status_code} - {e.response.text}")
                raise RuntimeError(f"Ollama API error: {e.response.status_code}") from e

    async def embed(self, texts: List[str]) -> List[np.ndarray]:
        # Newer Ollama: /api/embed with {"input": [..]}
        timeout = httpx.Timeout(120.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                r = await client.post(f"{self.base_url}/api/embed", json={
                    "model": self.embed_model,
                    "input": texts,
                })
                if r.status_code == 404:
                    raise RuntimeError("embed endpoint not found")
                r.raise_for_status()
                data = r.json()
                return [np.asarray(v, dtype=np.float32) for v in data["embeddings"]]
            except httpx.TimeoutException as e:
                print(f"Ollama embed timeout: {e}")
                raise RuntimeError(f"Ollama embed request timed out. Is Ollama running? Model: {self.embed_model}") from e
            except httpx.ConnectError as e:
                print(f"Ollama connection error: {e}")
                raise RuntimeError(f"Cannot connect to Ollama at {self.base_url}. Is Ollama running?") from e
            except Exception as e:
                # Fallback: older /api/embeddings with {"prompt": "..."}
                try:
                    out: List[np.ndarray] = []
                    for t in texts:
                        rr = await client.post(f"{self.base_url}/api/embeddings", json={
                            "model": self.embed_model,
                            "prompt": t,
                        })
                        rr.raise_for_status()
                        out.append(np.asarray(rr.json()["embedding"], dtype=np.float32))
                    return out
                except Exception as fallback_error:
                    print(f"Ollama embed fallback also failed: {fallback_error}")
                    raise RuntimeError(f"Ollama embed failed: {e}") from e
