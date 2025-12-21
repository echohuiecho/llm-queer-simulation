import time
import random
from typing import Any, Dict, List, Optional
from google.adk.tools.tool_context import ToolContext
from .state import add_message, add_dm, update_agent_pos, add_to_outbox
from config import config

# We'll need access to the RAG index.
# Since tools are just functions, we can set this from server.py during startup.
_rag_index = None

def set_rag_index(rag):
    global _rag_index
    _rag_index = rag

def send_message(
    text: str,
    room: str = "group_chat",
    sender: str = "",
    *,
    tool_context: ToolContext,
):
    """Send a message to a specific room. If sender is not provided, it will be inferred from the calling agent."""
    state = tool_context.state

    # If sender not provided, try to infer from agent_id in tool_context
    if not sender:
        # ADK ToolContext provides agent_name for the calling agent (see ref/9-callbacks)
        agent_name = getattr(tool_context, "agent_name", None)
        agent_id = agent_name or getattr(tool_context, "agent_id", None) or getattr(tool_context, "author", None)

        if agent_id:
            profiles = config.get("agent_profiles", {})
            if agent_id in profiles:
                sender = profiles[agent_id].get("name", agent_id)
            else:
                sender = str(agent_id)
        else:
            sender = "Unknown"

    add_message(state, room, sender, text)
    return {"status": "sent", "text": text}

def send_dm(
    text: str,
    to: str,
    from_user: str = "You",
    *,
    tool_context: ToolContext,
):
    """Send a direct message to a specific person."""
    state = tool_context.state
    add_dm(state, from_user, to, text)
    return {"status": "sent", "text": text}

def move_room(agent_id: str, agent_name: str, room: str, tool_context: ToolContext):
    """Move an agent to another room."""
    state = tool_context.state
    if room in state["rooms"]:
        new_pos = {"x": random.uniform(0.1, 0.9), "y": random.uniform(0.1, 0.9)}
        update_agent_pos(state, agent_name, room, new_pos)

        # Emit presence event
        presence_event = {
            "type": "presence",
            "agent": agent_id,
            "room": room,
            "pos": new_pos,
            "ts": time.time()
        }
        add_to_outbox(state, presence_event)
        return {"status": "moved", "room": room}
    return {"status": "error", "message": f"Room {room} not found"}

def wait(minutes: int, tool_context: ToolContext):
    """Do nothing for a while. Use this when you want to observe or wait before taking action."""
    # In a real-time simulation, we don't actually wait, but we can log this action
    return {"status": "waited", "minutes": minutes, "message": f"Waited {minutes} minutes"}

async def rag_search(query: str, k: int = 6):
    """Search the show subtitles and frames for relevant content."""
    if not _rag_index:
        return {"error": "RAG index not initialized"}

    hits = await _rag_index.search(query, k=k)
    from rag_index import RAGIndex
    show_snips = RAGIndex.render_for_prompt(hits)

    # Extract frame info for context
    frame_info = RAGIndex.extract_frame_info(hits)
    frame_context = ""
    if frame_info:
        frame_context = "\n\nAvailable video frames matching this context:\n"
        for i, frame in enumerate(frame_info[:3]):
            frame_context += f"- {frame['timestamp']}: {frame['caption'][:100]}...\n"

    return {
        "show_snips": show_snips,
        "frame_context": frame_context,
        "hits": hits # Keep raw hits for other tools if needed
    }

async def retrieve_scene(query: str, agent_name: str, room: str, tool_context: ToolContext):
    """Retrieve and discuss a specific scene from the video. Returns both frame image and transcript context."""
    state = tool_context.state
    if not _rag_index:
        return {"error": "RAG index not initialized"}

    import re
    from rag_index import RAGIndex

    # Parse timestamp from query if present
    timestamp_match = re.search(r'(\d{1,2}):(\d{2}):(\d{2})(?:[,.](\d{1,3}))?', query)
    timestamp_str = None
    timestamp_seconds = None

    if timestamp_match:
        hh, mm, ss = timestamp_match.groups()[:3]
        ms = timestamp_match.group(4) or "000"
        ms = ms.ljust(3, '0')[:3]
        timestamp_str = f"{hh.zfill(2)}:{mm}:{ss},{ms}"
        # Convert to seconds for transcript search
        timestamp_seconds = int(hh) * 3600 + int(mm) * 60 + int(ss) + (int(ms) / 1000.0)

    # Search for frames
    if timestamp_str:
        frame_hits = await _rag_index.search_frames_by_timestamp(timestamp_str, tolerance_seconds=10.0)
        if frame_hits:
            semantic_hits = await _rag_index.search(query, k=3)
            all_frame_hits = frame_hits + semantic_hits
        else:
            all_frame_hits = await _rag_index.search(query, k=8)
    else:
        all_frame_hits = await _rag_index.search(query, k=8)

    frame_info = RAGIndex.extract_frame_info(all_frame_hits)
    best_frame = frame_info[0] if frame_info else None

    # Search for transcript segments
    transcript_hits = []
    if timestamp_seconds is not None:
        # Search transcript by timestamp
        transcript_hits = await _rag_index.search_transcript_by_timestamp(timestamp_seconds, tolerance_seconds=15.0)
    else:
        # Semantic search for transcript
        transcript_hits = await _rag_index.search(query, k=6)
        # Filter to only SRT segments
        transcript_hits = [(score, seg) for score, seg in transcript_hits if seg.metadata.get("type") == "srt"]

    # Format transcript snippets
    transcript_text = RAGIndex.render_transcript_for_scene(transcript_hits, max_lines=6)
    transcript_snippets = [{"score": float(score), "text": seg.raw, "start_tc": seg.metadata.get("start_tc", ""),
                          "end_tc": seg.metadata.get("end_tc", "")}
                         for score, seg in transcript_hits[:6]]

    if best_frame:
        event = {
            "type": "frame_reference",
            "agent": agent_name,
            "frame_file": best_frame["frame_file"],
            "timestamp": best_frame["timestamp"],
            "timestamp_seconds": best_frame["timestamp_seconds"],
            "caption": best_frame["caption"],
            "room": room,
            "ts": time.time()
        }
        # Add transcript context to event if available
        if transcript_text and transcript_text != "(no transcript lines found)":
            event["transcript"] = transcript_text
        add_to_outbox(state, event)

        return {
            "status": "success",
            "frame": {
                "frame_file": best_frame["frame_file"],
                "timestamp": best_frame["timestamp"],
                "timestamp_seconds": best_frame["timestamp_seconds"],
                "caption": best_frame["caption"]
            },
            "transcript": transcript_text,
            "transcript_snippets": transcript_snippets
        }

    # Even if no frame found, return transcript if available
    if transcript_text and transcript_text != "(no transcript lines found)":
        return {
            "status": "partial_success",
            "message": "No frame found, but transcript available",
            "transcript": transcript_text,
            "transcript_snippets": transcript_snippets
        }

    return {"status": "not_found", "message": "No frames or transcript found for the query"}

def emit_event(event_type: str, payload: Dict[str, Any], tool_context: ToolContext):
    """Emit a custom event to the WebSocket outbox."""
    state = tool_context.state
    event = {
        "type": event_type,
        "ts": time.time(),
        **payload
    }
    add_to_outbox(state, event)
    return {"status": "emitted"}

async def prepare_turn_context(query: str, tool_context: ToolContext):
    """Search the show subtitles and frames for relevant content based on a query.

    Use this tool when the conversation mentions the show, characters, scenes, or episodes.
    The tool will search the knowledge base and return relevant subtitle snippets and frame information.

    Args:
        query: A search query describing what you're looking for (e.g., "emotional moment between characters", "kiss scene", "character name", "episode 2 ending")

    Returns:
        Dictionary with:
        - status: "context_prepared"
        - context: Dictionary containing:
          - show_snips: Relevant subtitle quotes with timestamps
          - frame_context: Available video frames matching the query
          - query: The search query used

    The context is also stored in state["turn_context"] for reference in your response.
    Use the show_snips to find accurate quotes to include in your message.
    """
    state = tool_context.state
    if not _rag_index:
        return {"error": "RAG index not initialized"}

    # Get agent ID and name from tool_context for frame_reference events
    agent_id = getattr(tool_context, "agent_id", None) or getattr(tool_context, "author", None)
    agent_name = getattr(tool_context, "agent_name", None)

    if not agent_name and agent_id:
        profiles = config.get("agent_profiles", {})
        if agent_id in profiles:
            agent_name = profiles[agent_id].get("name", agent_id)
        else:
            agent_name = str(agent_id)
    elif not agent_name:
        agent_name = "Unknown"

    # Use the existing rag_search tool logic
    results = await rag_search(query, k=8)  # Get more hits to find frames

    if "error" in results:
        return results

    # Extract frame info from the hits
    from rag_index import RAGIndex
    frame_info = RAGIndex.extract_frame_info(results.get("hits", []))

    # Check if query contains a timestamp (e.g., "00:12:34" or "E1P2 00:12:34–00:12:36")
    import re
    timestamp_match = None
    timestamp_str = None

    # Try to match timestamp patterns in the query
    # First try range pattern (e.g., "00:12:34–00:12:36")
    range_pattern = r'(\d{1,2}):(\d{2}):(\d{2})(?:[,.](\d{1,3}))?[–-](\d{1,2}):(\d{2}):(\d{2})(?:[,.](\d{1,3}))?'
    range_match = re.search(range_pattern, query)
    if range_match:
        # Use the start timestamp from the range
        hh, mm, ss = range_match.groups()[0], range_match.groups()[1], range_match.groups()[2]
        ms = range_match.groups()[3] if range_match.groups()[3] else "000"
        ms = ms.ljust(3, '0')[:3]
        timestamp_str = f"{hh.zfill(2)}:{mm}:{ss},{ms}"
        timestamp_match = range_match

    # If no range match, try single timestamp pattern
    if not timestamp_match:
        single_pattern = r'(\d{1,2}):(\d{2}):(\d{2})(?:[,.](\d{1,3}))?'
        timestamp_match = re.search(single_pattern, query)
        if timestamp_match:
            groups = timestamp_match.groups()
            hh, mm, ss = groups[0], groups[1], groups[2]
            ms = groups[3] if len(groups) > 3 and groups[3] else "000"
            ms = ms.ljust(3, '0')[:3]
            timestamp_str = f"{hh.zfill(2)}:{mm}:{ss},{ms}"

    # Also check show_snips for timestamps if not found in query
    if not timestamp_match:
        show_snips = results.get("show_snips", "")
        if show_snips:
            # Try range pattern first
            range_match = re.search(range_pattern, show_snips)
            if range_match:
                hh, mm, ss = range_match.groups()[0], range_match.groups()[1], range_match.groups()[2]
                ms = range_match.groups()[3] if range_match.groups()[3] else "000"
                ms = ms.ljust(3, '0')[:3]
                timestamp_str = f"{hh.zfill(2)}:{mm}:{ss},{ms}"
                timestamp_match = range_match
            else:
                # Try single timestamp
                single_match = re.search(single_pattern, show_snips)
                if single_match:
                    groups = single_match.groups()
                    hh, mm, ss = groups[0], groups[1], groups[2]
                    ms = groups[3] if len(groups) > 3 and groups[3] else "000"
                    ms = ms.ljust(3, '0')[:3]
                    timestamp_str = f"{hh.zfill(2)}:{mm}:{ss},{ms}"
                    timestamp_match = single_match

    # If we found a timestamp or have frame info, try to get the best matching frame
    best_frame = None
    if timestamp_match or frame_info:
        if timestamp_str:
            # Search for frames by timestamp
            timestamp_hits = await _rag_index.search_frames_by_timestamp(timestamp_str, tolerance_seconds=10.0)
            if timestamp_hits:
                frame_info_from_ts = RAGIndex.extract_frame_info(timestamp_hits)
                if frame_info_from_ts:
                    best_frame = frame_info_from_ts[0]

        # If no timestamp match or no frame from timestamp, use best frame from semantic search
        if not best_frame and frame_info:
            best_frame = frame_info[0]

    # Store frame reference in state for this agent so it can be attached to their message later
    if best_frame and agent_id:
        frame_ref_key = f"{agent_id}_frame_ref"
        state[frame_ref_key] = {
            "frame_file": best_frame["frame_file"],
            "timestamp": best_frame["timestamp"],
            "timestamp_seconds": best_frame["timestamp_seconds"],
            "caption": best_frame["caption"]
        }

    context_data = {
        "show_snips": results["show_snips"],
        "frame_context": results["frame_context"],
        "query": query,
        "ts": time.time()
    }
    state["turn_context"] = context_data
    return {
        "status": "context_prepared",
        "context": context_data,
        "show_snips": results["show_snips"],  # Make it easy to access
        "frame_context": results["frame_context"],
        "frame_found": best_frame is not None  # Indicate if a frame was found
    }


async def dispatch_persona_replies(tool_context: ToolContext, room: str = "group_chat"):
    """Publish persona replies written to state via output_key into chat/outbox.

    Pattern (from ADK refs): parallel sub-agents write results into state, then a downstream step dispatches.
    Also attaches any frame references that were prepared by prepare_turn_context.

    Filters out tool call patterns (e.g., "prepare_turn_context(...)") that shouldn't be displayed as messages.
    """
    import re
    state = tool_context.state
    profiles = config.get("agent_profiles", {})

    published: list[str] = []
    for aid in ["a1", "a2", "a3"]:
        key = f"{aid}_reply"
        text = state.get(key)
        if not isinstance(text, str) or not text.strip():
            # Check for pending timestamp even if no reply text
            pending_timestamp_key = f"{aid}_pending_timestamp"
            pending_timestamp = state.get(pending_timestamp_key)
            if pending_timestamp:
                print(f"[DISPATCH] Agent {aid} has pending timestamp {pending_timestamp} but no reply text yet")
            continue

        # Filter out tool call patterns - agents should call tools, not write them as text
        # Pattern matches: function_name(...) or function_name(...) with any arguments
        tool_call_pattern = r'^\s*(prepare_turn_context|retrieve_scene|send_message|send_dm|move_room|wait)\s*\([^)]*\)\s*$'
        if re.match(tool_call_pattern, text.strip(), re.IGNORECASE):
            # This looks like a tool call, skip it - the agent should have called the tool instead
            state[key] = ""  # Clear it so it doesn't accumulate
            continue

        # Also filter out JSON-like tool call structures
        if text.strip().startswith('{') and ('"function"' in text or '"tool"' in text or '"name"' in text):
            # Looks like a JSON tool call structure, skip it
            state[key] = ""
            continue

        sender = profiles.get(aid, {}).get("name") or aid

        # Check if there's a frame reference for this agent
        frame_ref_key = f"{aid}_frame_ref"
        frame_ref = state.get(frame_ref_key)
        print(f"[DISPATCH] Agent {aid} ({sender}): checking frame_ref = {frame_ref}")

        # Fallback: if there's a pending timestamp but no frame_ref, try to retrieve it now
        # Since dispatch_persona_replies is now async, we can await the frame retrieval
        if not frame_ref:
            pending_timestamp_key = f"{aid}_pending_timestamp"
            pending_timestamp = state.get(pending_timestamp_key)
            print(f"[DISPATCH] Agent {aid}: pending_timestamp = {pending_timestamp}, _rag_index = {_rag_index is not None}")
            if pending_timestamp and _rag_index:
                print(f"[DISPATCH] Processing pending timestamp {pending_timestamp} for agent {aid}")
                try:
                    timestamp_hits = await _rag_index.search_frames_by_timestamp(
                        pending_timestamp, tolerance_seconds=10.0
                    )
                    if timestamp_hits:
                        from rag_index import RAGIndex
                        frame_info_from_ts = RAGIndex.extract_frame_info(timestamp_hits)
                        if frame_info_from_ts:
                            best_frame = frame_info_from_ts[0]
                            frame_ref = {
                                "frame_file": best_frame["frame_file"],
                                "timestamp": best_frame["timestamp"],
                                "timestamp_seconds": best_frame["timestamp_seconds"],
                                "caption": best_frame["caption"]
                            }
                            state[frame_ref_key] = frame_ref
                            print(f"[DISPATCH] Retrieved frame for pending timestamp: {best_frame.get('frame_file')}")
                    # Clear the pending timestamp
                    state[pending_timestamp_key] = None
                except Exception as e:
                    print(f"[DISPATCH] Error processing pending timestamp: {e}")
                    import traceback
                    traceback.print_exc()

        print(f"[DISPATCH] Agent {aid} ({sender}): frame_ref = {frame_ref}")

        # Add message to history and outbox
        # Create message dict - if frame_ref exists, include it from the start
        # This ensures the dict is created with frameReference, not mutated later
        msg_dict = {
            "type": "message",
            "room": room,
            "from": sender,
            "text": text.strip(),
            "ts": time.time()
        }

        # Attach frame reference if available (create new dict with frameReference)
        if frame_ref:
            print(f"[DISPATCH] Attaching frame reference to message: {frame_ref.get('frame_file')}")
            msg_dict = {
                **msg_dict,
                "frameReference": {
                    "frame_file": frame_ref["frame_file"],
                    "timestamp": frame_ref["timestamp"],
                    "timestamp_seconds": frame_ref["timestamp_seconds"],
                    "caption": frame_ref["caption"]
                }
            }
            print(f"[DISPATCH] Message with frameReference: {msg_dict.get('frameReference')}")
            # Also emit a separate frame_reference event for the frontend
            frame_event = {
                "type": "frame_reference",
                "agent": sender,
                "frame_file": frame_ref["frame_file"],
                "timestamp": frame_ref["timestamp"],
                "timestamp_seconds": frame_ref["timestamp_seconds"],
                "caption": frame_ref["caption"],
                "room": room,
                "ts": time.time()
            }
            add_to_outbox(state, frame_event)
            print(f"[DISPATCH] Added frame_reference event to outbox: {frame_event}")
            # Clear the frame ref after using it
            state[frame_ref_key] = None
        else:
            print(f"[DISPATCH] No frame_ref to attach for agent {aid}")

        # Use msg_dict (which may have frameReference) for both history and outbox
        if room not in state["history"]:
            state["history"][room] = []
        # Create new list to ensure ADK detects the change
        new_history = list(state["history"][room])
        new_history.append(msg_dict)
        state["history"][room] = new_history

        # Limit history size
        if len(state["history"][room]) > 50:
            state["history"][room] = state["history"][room][-50:]

        print(f"[DISPATCH] About to add message to outbox. Message keys: {list(msg_dict.keys())}, has frameReference: {'frameReference' in msg_dict}")
        add_to_outbox(state, msg_dict)
        print(f"[DISPATCH] Message added to outbox. Outbox now has {len(state.get('outbox', []))} events")
        # Verify the message in outbox still has frameReference
        if state.get('outbox'):
            last_msg = state['outbox'][-1]
            if last_msg.get('type') == 'message' and last_msg.get('from') == sender:
                print(f"[DISPATCH] Last message in outbox has frameReference: {'frameReference' in last_msg}, keys: {list(last_msg.keys())}")
                if 'frameReference' in last_msg:
                    print(f"[DISPATCH] frameReference content: {last_msg['frameReference']}")
                else:
                    print(f"[DISPATCH] WARNING: frameReference missing from last message! Full message: {last_msg}")
        state[key] = ""  # clear after publishing
        published.append(aid)

    # ADK tools modify tool_context.state directly, and those changes should be persisted automatically.
    # However, to ensure the outbox with frameReference is persisted, we need to make sure
    # the state modifications are committed. The issue might be that get_session() returns
    # a deep copy, so we need to ensure the state is properly persisted.
    #
    # Actually, ADK should handle this automatically. The real issue might be timing -
    # we're reading the session state before the tool's state changes are committed.
    # Let's add a small delay or ensure we're reading from the right place.

    print(f"[DISPATCH] Returning. Final outbox has {len(state.get('outbox', []))} events")
    if state.get('outbox'):
        for i, evt in enumerate(state.get('outbox', [])):
            if evt.get('type') == 'message' and 'frameReference' in evt:
                print(f"[DISPATCH] Outbox event {i} has frameReference: {evt.get('frameReference')}")

    # Return the outbox in the tool result so we can access it directly
    # This ensures we have the latest state even if ADK hasn't persisted it yet
    return {
        "status": "ok",
        "published": published,
        "_outbox": state.get("outbox", [])  # Include outbox in return value for direct access
    }



