"""
ADK callbacks for the queer simulation.

This module provides callbacks that enhance agent behavior, such as detecting
timestamps in agent output and automatically retrieving frame images.
"""

import asyncio
import re
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmResponse

# Import the tools module to access _rag_index dynamically
from . import tools as tools_module
from config import config


def detect_timestamps_in_output(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """
    After Model Callback: Detects timestamps in the LLM response text and retrieves
    matching frame images from RAG.

    This ensures that when agents mention timestamps in their final message text
    (e.g., "I'm serious" (00:12:34–00:12:36)), the corresponding frame is retrieved
    and attached to the message.

    Args:
        callback_context: Contains state and agent information
        llm_response: The LLM response containing the agent's output text

    Returns:
        None to keep the original response unchanged, or a modified LlmResponse
    """
    print(f"[CALLBACK] detect_timestamps_in_output called")

    # Get RAG index dynamically (it's set by set_rag_index() in server.py)
    _rag_index = getattr(tools_module, '_rag_index', None)

    # Skip if no RAG index available
    if not _rag_index:
        print(f"[CALLBACK] No RAG index available, skipping")
        return None

    # Skip if response is empty or has no text content
    if not llm_response or not llm_response.content or not llm_response.content.parts:
        print(f"[CALLBACK] No response content, skipping")
        return None

    # Extract text from the response
    response_text = ""
    for part in llm_response.content.parts:
        if hasattr(part, "text") and part.text:
            response_text += part.text

    if not response_text:
        print(f"[CALLBACK] No text in response, skipping")
        return None

    print(f"[CALLBACK] Response text (first 200 chars): {response_text[:200]}")

    # Get agent_id from callback context
    agent_id = callback_context.agent_name  # This should be "a1", "a2", or "a3"
    print(f"[CALLBACK] Agent name from context: {agent_id}")
    if not agent_id or agent_id not in ["a1", "a2", "a3"]:
        print(f"[CALLBACK] Agent {agent_id} not a persona agent, skipping")
        return None  # Only process persona agents

    # Search for timestamps in the response text
    timestamp_str = None

    # Try to match timestamp patterns (same logic as prepare_turn_context)
    # First try range pattern (e.g., "00:12:34–00:12:36")
    range_pattern = r'(\d{1,2}):(\d{2}):(\d{2})(?:[,.](\d{1,3}))?[–-](\d{1,2}):(\d{2}):(\d{2})(?:[,.](\d{1,3}))?'
    range_match = re.search(range_pattern, response_text)
    if range_match:
        # Use the start timestamp from the range
        hh, mm, ss = range_match.groups()[0], range_match.groups()[1], range_match.groups()[2]
        ms = range_match.groups()[3] if range_match.groups()[3] else "000"
        ms = ms.ljust(3, '0')[:3]
        timestamp_str = f"{hh.zfill(2)}:{mm}:{ss},{ms}"

    # If no range match, try single timestamp pattern
    if not timestamp_str:
        single_pattern = r'(\d{1,2}):(\d{2}):(\d{2})(?:[,.](\d{1,3}))?'
        single_match = re.search(single_pattern, response_text)
        if single_match:
            groups = single_match.groups()
            hh, mm, ss = groups[0], groups[1], groups[2]
            ms = groups[3] if len(groups) > 3 and groups[3] else "000"
            ms = ms.ljust(3, '0')[:3]
            timestamp_str = f"{hh.zfill(2)}:{mm}:{ss},{ms}"

    # If we found a timestamp, retrieve the frame
    if timestamp_str:
        print(f"[CALLBACK] Detected timestamp '{timestamp_str}' in agent {agent_id} output")
        try:
            # Search for frames by timestamp (run async code synchronously)
            async def _retrieve_frame():
                print(f"[CALLBACK] Searching for frames with timestamp: {timestamp_str}")
                timestamp_hits = await _rag_index.search_frames_by_timestamp(
                    timestamp_str, tolerance_seconds=10.0
                )
                print(f"[CALLBACK] Found {len(timestamp_hits)} frame hits")

                if timestamp_hits:
                    from rag_index import RAGIndex
                    frame_info_from_ts = RAGIndex.extract_frame_info(timestamp_hits)
                    print(f"[CALLBACK] Extracted {len(frame_info_from_ts)} frame info entries")

                    if frame_info_from_ts:
                        best_frame = frame_info_from_ts[0]
                        print(f"[CALLBACK] Best frame: {best_frame.get('frame_file')} at {best_frame.get('timestamp')}")

                        # Store frame reference in state for dispatch_persona_replies to use
                        state = callback_context.state
                        frame_ref_key = f"{agent_id}_frame_ref"
                        state[frame_ref_key] = {
                            "frame_file": best_frame["frame_file"],
                            "timestamp": best_frame["timestamp"],
                            "timestamp_seconds": best_frame["timestamp_seconds"],
                            "caption": best_frame["caption"]
                        }
                        print(f"[CALLBACK] Stored frame ref in state[{frame_ref_key}]")
                    else:
                        print(f"[CALLBACK] No frame info extracted from hits")
                else:
                    print(f"[CALLBACK] No frame hits found for timestamp {timestamp_str}")

            # Since we're in a synchronous callback and can't easily run async code
            # (nest_asyncio doesn't work with uvloop), we'll store the timestamp
            # and let dispatch_persona_replies retrieve the frame asynchronously
            state = callback_context.state
            state[f"{agent_id}_pending_timestamp"] = timestamp_str
            print(f"[CALLBACK] Stored pending timestamp {timestamp_str} for agent {agent_id} - will be processed by dispatch_persona_replies")
        except Exception as e:
            # Don't fail the callback if frame retrieval fails
            print(f"[CALLBACK] Error retrieving frame in callback: {e}")
            import traceback
            traceback.print_exc()
            pass
    else:
        print(f"[CALLBACK] No timestamp found in agent {agent_id} output")

    # Return None to keep the original response unchanged
    return None

