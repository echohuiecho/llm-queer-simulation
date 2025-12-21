import time
from typing import Any, Dict, List, Optional
from config import config

def get_initial_state() -> Dict[str, Any]:
    """Returns the initial state for a new ADK session."""
    profiles = config.get("agent_profiles")
    agents = []
    for aid, p in profiles.items():
        agents.append({
            "id": aid,
            "name": p["name"],
            "room": "group_chat",
            "pos": {"x": 0.5, "y": 0.5},
            "room_entered_ts": time.time()
        })

    rooms = list(config.get("room_desc").keys())
    history = {r: [] for r in rooms}

    # Note: Initial messages are NOT added here.
    # They are added via seed_initial_chat() in server.py to ensure
    # config changes are reflected on server restart.

    return {
        "rooms": rooms,
        "history": history,
        "agents": agents,
        "rag_directory": config.get("rag_directory", "default"),
        "outbox": [],  # Events to broadcast via WebSocket
        "turn_context": {},
        "proposed_actions": {},

        # --- Webtoon storyline planning (LoopAgent pipeline) ---
        "current_storyline": {},          # dict form (parsed JSON)
        "current_storyline_json": "",     # canonical JSON string for prompt injection
        "storyline_version": 0,
        "storyline_iteration": 0,
        "storyline_triggered": False,     # milestone-trigger latch
        "storyline_review_status": "",    # pass/fail
        "review_feedback": "",            # reviewer feedback for refiner
    }

def add_to_outbox(state: Dict[str, Any], event: Dict[str, Any]):
    """Add an event to the outbox for the current turn.

    Note: We reassign the entire list to ensure ADK detects the state change.
    ADK may not detect mutations to nested lists/dicts, so we create a new list.
    """
    if "outbox" not in state:
        state["outbox"] = []
    # Create a new list to ensure ADK detects the state change
    new_outbox = list(state["outbox"])
    new_outbox.append(event)
    state["outbox"] = new_outbox

def update_agent_pos(state: Dict[str, Any], agent_name: str, room: str, pos: Dict[str, float]):
    """Update agent position and room in state."""
    for a in state.get("agents", []):
        if a["name"] == agent_name:
            a["room"] = room
            a["pos"] = pos
            a["room_entered_ts"] = time.time()
            break

def add_message(state: Dict[str, Any], room: str, sender: str, text: str):
    """Add a message to the history and outbox."""
    msg = {
        "type": "message",
        "room": room,
        "from": sender,
        "text": text,
        "ts": time.time()
    }

    if room not in state["history"]:
        state["history"][room] = []
    state["history"][room].append(msg)

    # Limit history size
    if len(state["history"][room]) > 50:
        state["history"][room] = state["history"][room][-50:]

    add_to_outbox(state, msg)

def add_dm(state: Dict[str, Any], from_user: str, to_agent: str, text: str):
    """Add a DM to the history and outbox."""
    # Consistent key like in world.py
    agent_name = to_agent if from_user == "You" else from_user
    dm_room = f"dm:{agent_name}"

    msg = {
        "type": "message",
        "room": dm_room,
        "from": from_user,
        "text": text,
        "ts": time.time()
    }

    if dm_room not in state["history"]:
        state["history"][dm_room] = []
    state["history"][dm_room].append(msg)

    # Limit history size
    if len(state["history"][dm_room]) > 50:
        state["history"][dm_room] = state["history"][dm_room][-50:]

    add_to_outbox(state, msg)

