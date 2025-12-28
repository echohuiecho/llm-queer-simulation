"""
RoleArena-specific tools for plot-driven narrative control.

These tools integrate with the RoleArena state structure and workflow:
- update_env_turn_plan: Store EnvAgent's turn plan
- emit_narration: Emit scene narration (separate from character dialogue)
- emit_character_response: Emit character dialogue/action/thought
- advance_plot: Advance to next plot node with bridge narration
"""

import json
import time
import logging
from typing import Any, Dict, Optional
from google.adk.tools.tool_context import ToolContext
from .state import add_to_outbox, add_message
from .rolearena_state import (
    advance_plot_node,
    increment_turn,
    get_current_node,
    update_quality_flags as state_update_quality_flags
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def update_env_turn_plan(
    turn_plan: Dict[str, Any],
    *,
    tool_context: ToolContext
) -> Dict[str, str]:
    """
    Store EnvAgent's turn plan in state.

    Args:
        turn_plan: TurnPlan JSON from EnvAgent
        tool_context: ADK tool context

    Returns:
        Status dict
    """
    logger.info("[ROLEARENA_TOOLS] Updating env_turn_plan")

    state = tool_context.state
    state["env_turn_plan"] = turn_plan

    # Extract advance candidate flag
    state["advance_candidate"] = turn_plan.get("advance_candidate", False)
    state["advance_reason"] = turn_plan.get("advance_reason", "")

    logger.info(f"[ROLEARENA_TOOLS]   Narration: {turn_plan.get('narration', '')[:80]}...")
    logger.info(f"[ROLEARENA_TOOLS]   Next speaker: {turn_plan.get('next_speaker')}")
    logger.info(f"[ROLEARENA_TOOLS]   Advance candidate: {state['advance_candidate']}")

    return {"status": "ok", "advance_candidate": state["advance_candidate"]}


def emit_narration(
    narration: str,
    narration_type: str = "scene",
    room: str = "group_chat",
    *,
    tool_context: ToolContext
) -> Dict[str, str]:
    """
    Emit narration (system voice, scene-keeping text).

    This is separate from character dialogue and appears in the scene log.

    Args:
        narration: Narration text (1-3 sentences)
        narration_type: "scene" | "bridge" | "hint"
        room: Target room
        tool_context: ADK tool context

    Returns:
        Status dict
    """
    logger.info(f"[ROLEARENA_TOOLS] Emitting narration (type: {narration_type})")
    logger.info(f"[ROLEARENA_TOOLS]   Text: {narration[:80]}...")

    state = tool_context.state

    # Store in narrations list
    state.setdefault("narrations", []).append({
        "type": narration_type,
        "text": narration,
        "timestamp": time.time()
    })

    # Emit as system message
    event = {
        "type": "narration",
        "narration_type": narration_type,
        "text": narration,
        "room": room,
        "ts": time.time()
    }
    add_to_outbox(state, event)

    # Also add to history as system message for continuity
    add_message(state, room, "Narrator", narration)

    return {"status": "ok", "type": narration_type}


def emit_character_response(
    speaker: str,
    utterance: str,
    action: str = "",
    thought: str = "",
    room: str = "group_chat",
    *,
    tool_context: ToolContext
) -> Dict[str, str]:
    """
    Emit a character's response (dialogue + action + optional thought).

    This keeps narration and dialogue in separate channels.

    Args:
        speaker: Character ID (a1/a2/a3)
        utterance: What the character says
        action: Physical action (short)
        thought: Internal thought (optional)
        room: Target room
        tool_context: ADK tool context

    Returns:
        Status dict
    """
    logger.info(f"[ROLEARENA_TOOLS] Emitting character response for {speaker}")
    logger.info(f"[ROLEARENA_TOOLS]   Utterance: {utterance[:80]}...")
    if action:
        logger.info(f"[ROLEARENA_TOOLS]   Action: {action[:80]}...")
    if thought:
        logger.info(f"[ROLEARENA_TOOLS]   Thought: {thought[:80]}...")

    state = tool_context.state

    # Store in character_responses list
    state.setdefault("character_responses", []).append({
        "speaker": speaker,
        "utterance": utterance,
        "action": action,
        "thought": thought,
        "timestamp": time.time()
    })

    # Format full message
    parts = []
    if action:
        parts.append(f"*{action}*")
    if utterance:
        parts.append(utterance)
    if thought:
        parts.append(f"_(thinking: {thought})_")

    full_text = " ".join(parts)

    # Get character name from config
    from config import config
    profiles = config.get("agent_profiles", {})
    char_name = profiles.get(speaker, {}).get("name", speaker)

    # Emit as character message
    event = {
        "type": "character_response",
        "speaker": speaker,
        "speaker_name": char_name,
        "utterance": utterance,
        "action": action,
        "thought": thought,
        "room": room,
        "ts": time.time()
    }
    add_to_outbox(state, event)

    # Also add to history
    add_message(state, room, char_name, full_text)

    return {"status": "ok", "speaker": speaker}


def advance_plot(
    approve: bool,
    bridge_narration: str = "",
    room: str = "group_chat",
    *,
    tool_context: ToolContext
) -> Dict[str, Any]:
    """
    Advance to next plot node (only if approved).

    Args:
        approve: Whether critic approved the advance
        bridge_narration: Short bridge narration (1-3 sentences)
        room: Target room
        tool_context: ADK tool context

    Returns:
        Status dict with new node info
    """
    logger.info(f"[ROLEARENA_TOOLS] Advance plot called (approve={approve})")

    state = tool_context.state

    if not approve:
        logger.info("[ROLEARENA_TOOLS]   Advance rejected by critic, continuing current node")
        state["advance_candidate"] = False
        state["critic_approved"] = False
        return {"status": "rejected", "continue_current_node": True}

    # Get current and next nodes
    plot = state.get("plot", {})
    current_idx = plot.get("node_idx", 0)
    nodes = plot.get("nodes", [])

    if current_idx >= len(nodes) - 1:
        logger.warning("[ROLEARENA_TOOLS]   Already at final node, cannot advance")
        return {"status": "at_final_node", "node_idx": current_idx}

    current_node = nodes[current_idx]
    next_node = nodes[current_idx + 1]

    logger.info(f"[ROLEARENA_TOOLS]   Advancing from node {current_idx} ({current_node['beat']}) to {current_idx + 1} ({next_node['beat']})")

    # Advance the plot
    advance_plot_node(state, bridge_narration)

    # Emit bridge narration
    if bridge_narration:
        emit_narration(bridge_narration, narration_type="bridge", room=room, tool_context=tool_context)

    # Reset flags
    state["advance_candidate"] = False
    state["critic_approved"] = False

    # Emit plot advancement event
    event = {
        "type": "plot_advance",
        "from_node": current_idx,
        "to_node": current_idx + 1,
        "from_beat": current_node["beat"],
        "to_beat": next_node["beat"],
        "bridge_narration": bridge_narration,
        "room": room,
        "ts": time.time()
    }
    add_to_outbox(state, event)

    logger.info(f"[ROLEARENA_TOOLS]   ✓ Plot advanced successfully")

    return {
        "status": "advanced",
        "from_node": current_idx,
        "to_node": current_idx + 1,
        "new_beat": next_node["beat"]
    }


def update_quality_flags(
    flags: Dict[str, float],
    *,
    tool_context: ToolContext
) -> Dict[str, str]:
    """
    Update quality monitoring flags.

    Args:
        flags: Quality flags dict (repetition_risk, character_drift_risk, plot_stall_risk)
        tool_context: ADK tool context

    Returns:
        Status dict
    """
    logger.info(f"[ROLEARENA_TOOLS] Updating quality flags: {flags}")

    state = tool_context.state
    state_update_quality_flags(state, flags)

    # Emit warnings if any flags are high
    warnings = []
    for key, value in flags.items():
        if value > 0.7:
            warnings.append(f"{key}: {value:.2f}")

    if warnings:
        logger.warning(f"[ROLEARENA_TOOLS]   ⚠️  High risk flags: {', '.join(warnings)}")

    return {"status": "ok", "warnings": warnings}


def increment_story_turn(
    *,
    tool_context: ToolContext
) -> Dict[str, Any]:
    """
    Increment turn counters (node_turns and total_turns).

    Args:
        tool_context: ADK tool context

    Returns:
        Status dict with current turn counts
    """
    state = tool_context.state
    increment_turn(state)

    plot = state.get("plot", {})
    node_turns = plot.get("node_turns", 0)
    total_turns = plot.get("total_turns", 0)

    logger.info(f"[ROLEARENA_TOOLS] Turn incremented: node_turns={node_turns}, total_turns={total_turns}")

    return {
        "status": "ok",
        "node_turns": node_turns,
        "total_turns": total_turns
    }


# Export all tools
__all__ = [
    "update_env_turn_plan",
    "emit_narration",
    "emit_character_response",
    "advance_plot",
    "update_quality_flags",
    "increment_story_turn",
]

