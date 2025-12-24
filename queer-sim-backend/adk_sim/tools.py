import time
import random
import json
from typing import Any, Dict, List, Optional
from google.adk.tools.tool_context import ToolContext
from .state import add_message, add_dm, update_agent_pos, add_to_outbox
from .persistence import get_storyline_persistence
from .validation import validate_storyline_state
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

def plan_storyline(
    storyline_json: str,
    room: str = "group_chat",
    *,
    tool_context: ToolContext,
) -> Dict[str, Any]:
    """Store an initial webtoon storyline draft into session state.

    The planner agent should generate a JSON string for the storyline and call this tool.
    We validate it's parseable JSON and store it under state['current_storyline'].
    """
    print(f"[PLAN_STORYLINE] Called with JSON length: {len(storyline_json)}")
    state = tool_context.state
    try:
        parsed = json.loads(storyline_json)
    except Exception as e:
        state["review_feedback"] = f"Invalid JSON: {e}"
        state["storyline_review_status"] = "fail"
        return {"result": "fail", "message": f"Invalid JSON: {e}"}

    if not isinstance(parsed, dict):
        state["review_feedback"] = "Storyline must be a JSON object at the top level."
        state["storyline_review_status"] = "fail"
        return {"result": "fail", "message": "Storyline must be a JSON object at the top level."}

    # Normalize all scenes to ensure they have episode numbers
    for scene in parsed.get("scenes", []):
        if isinstance(scene, dict):
            if "episode" not in scene or scene.get("episode") == 0:
                scene["episode"] = 1  # Default to episode 1

    version = int(state.get("storyline_version") or 0) + 1
    parsed.setdefault("meta", {})
    if isinstance(parsed.get("meta"), dict):
        parsed["meta"]["version"] = version
        parsed["meta"]["updated_ts"] = time.time()

    state["current_storyline"] = parsed
    state["current_storyline_json"] = json.dumps(parsed, ensure_ascii=False)
    state["storyline_version"] = version
    state["storyline_iteration"] = 0

    # Emit a machine-readable event with full storyline JSON for UI display
    add_to_outbox(state, {
        "type": "storyline_update",
        "version": version,
        "room": room,
        "storyline": parsed,  # Include full structured JSON
        "storyline_json": state["current_storyline_json"],  # Also include string version
        "ts": time.time()
    })
    # Minimal human-visible message (keeps UI contract unchanged)
    add_message(state, room, "System", f"Storyline draft created (v{version}).")

    # Validate state
    validation_errors = validate_storyline_state(state)
    if validation_errors:
        print(f"[PLAN_STORYLINE] Validation warnings: {validation_errors}")

    # Persist to disk
    storyline_dir = state.get("storyline_context_dir") or config.get("storyline_context_dir", "default")
    persistence = get_storyline_persistence()
    persistence.save_storyline(storyline_dir, parsed, version, update_type="plan")

    print(f"[PLAN_STORYLINE] Successfully created storyline v{version} with {len(parsed.get('scenes', []))} scenes")

    return {"result": "ok", "version": version}


def review_storyline(
    storyline_json: str,
    *,
    tool_context: ToolContext,
) -> Dict[str, Any]:
    """Deterministically review a storyline JSON draft for basic quality gates.

    This tool is intended to be called by a reviewer agent which decides whether to
    call exit_loop after reading the tool result.
    """
    print(f"[REVIEW_STORYLINE] Called with JSON length: {len(storyline_json)}")
    state = tool_context.state
    try:
        parsed = json.loads(storyline_json)
    except Exception as e:
        feedback = f"Invalid JSON: {e}"
        state["review_feedback"] = feedback
        state["storyline_review_status"] = "fail"
        return {"result": "fail", "feedback": feedback}

    issues: list[str] = []
    if not isinstance(parsed, dict):
        issues.append("Top-level must be an object.")
    else:
        chars = parsed.get("characters")
        if not isinstance(chars, list) or len(chars) != 2:
            issues.append("`characters` must be a list of exactly 2 characters (two masc lesbians).")
        else:
            for i, c in enumerate(chars):
                if not isinstance(c, dict):
                    issues.append(f"characters[{i}] must be an object.")
                    continue
                if not (c.get("name") and isinstance(c.get("name"), str)):
                    issues.append(f"characters[{i}].name must be a string.")
                if not (c.get("description") and isinstance(c.get("description"), str)):
                    issues.append(f"characters[{i}].description must be a string.")
                if not (c.get("visual_description") and isinstance(c.get("visual_description"), str)):
                    issues.append(f"characters[{i}].visual_description must be a string.")

        scenes = parsed.get("scenes")
        if not isinstance(scenes, list) or len(scenes) < 1:
            issues.append("`scenes` must be a non-empty list.")
        else:
            # Validate first few scenes/panels for webtoon-friendly vertical stack format
            for si, s in enumerate(scenes[:5]):
                if not isinstance(s, dict):
                    issues.append(f"scenes[{si}] must be an object.")
                    continue
                panels = s.get("panels")
                if not isinstance(panels, list) or len(panels) < 3:
                    issues.append(f"scenes[{si}].panels must have at least 3 panels (vertical scroll feel).")
                else:
                    empty_dialogue_count = 0
                    for pi, p in enumerate(panels[:5]):
                        if not isinstance(p, dict):
                            issues.append(f"scenes[{si}].panels[{pi}] must be an object.")
                            continue
                        if not (p.get("visual_description") and isinstance(p.get("visual_description"), str)):
                            issues.append(f"scenes[{si}].panels[{pi}].visual_description must be a string.")
                        dialogue = p.get("dialogue")
                        if not isinstance(dialogue, str):
                            issues.append(f"scenes[{si}].panels[{pi}].dialogue must be a string.")
                        elif not dialogue.strip():
                            empty_dialogue_count += 1
                    # Warn if too many panels have empty dialogue
                    if empty_dialogue_count > 2:
                        issues.append(f"scenes[{si}] has too many panels with empty dialogue ({empty_dialogue_count}). Add dialogue (spoken lines, internal monologue, or narration) to most panels. Only use empty string for truly silent moments (max 1-2 per scene).")

    if issues:
        feedback = "Needs work:\n- " + "\n- ".join(issues)
        state["review_feedback"] = feedback
        state["storyline_review_status"] = "fail"
        return {"result": "fail", "feedback": feedback, "issues": issues}

    feedback = "Passes basic structural quality checks."
    state["review_feedback"] = feedback
    state["storyline_review_status"] = "pass"
    return {"result": "pass", "feedback": feedback}


def refine_storyline(
    storyline_json: str,
    *,
    tool_context: ToolContext,
) -> Dict[str, Any]:
    """Store a refined storyline JSON draft into session state.

    IMPORTANT: This tool preserves all scenes from completed episodes and the current episode.
    It merges the refined JSON with existing scenes to prevent accidental deletion.
    """
    print(f"[REFINE_STORYLINE] Called with JSON length: {len(storyline_json)}")
    state = tool_context.state
    try:
        parsed = json.loads(storyline_json)
    except Exception as e:
        state["review_feedback"] = f"Invalid JSON: {e}"
        state["storyline_review_status"] = "fail"
        return {"result": "fail", "message": f"Invalid JSON: {e}"}

    if not isinstance(parsed, dict):
        state["review_feedback"] = "Storyline must be a JSON object at the top level."
        state["storyline_review_status"] = "fail"
        return {"result": "fail", "message": "Storyline must be a JSON object at the top level."}

    # Normalize all scenes to ensure they have episode numbers
    for scene in parsed.get("scenes", []):
        if isinstance(scene, dict):
            if "episode" not in scene or scene.get("episode") == 0:
                scene["episode"] = 1  # Default to episode 1

    # CRITICAL: Preserve ALL existing scenes to prevent deletion when LLM omits them
    existing = state.get("current_storyline")
    if isinstance(existing, dict):
        existing_scenes = existing.get("scenes")
        if isinstance(existing_scenes, list):
            # Identify completed episodes (these should NEVER be modified)
            meta = existing.get("meta", {})
            episodes_meta = meta.get("episodes", {}) if isinstance(meta, dict) else {}
            completed_episodes = set()
            if isinstance(episodes_meta, dict):
                for ep_key, ep_info in episodes_meta.items():
                    if isinstance(ep_info, dict) and ep_info.get("complete") is True:
                        try:
                            completed_episodes.add(int(ep_key))
                        except Exception:
                            pass

            # Get current episode number
            current_ep = int(state.get("current_episode_number") or 1)

            # CRITICAL: Preserve ALL existing scenes, not just completed/current
            # This ensures no scenes are lost if the LLM's refined JSON omits them
            existing_scene_map = {}
            for s in existing_scenes:
                if isinstance(s, dict):
                    ep = int(s.get("episode") or 0)
                    sn = int(s.get("scene_number") or 0)
                    key = (ep, sn)
                    existing_scene_map[key] = s

            # Merge: add new/refined scenes from parsed, but keep ALL existing scenes
            new_scenes = parsed.get("scenes", [])
            if isinstance(new_scenes, list):
                # Create a map of (episode, scene_number) -> scene for new scenes
                new_scene_map = {}
                for s in new_scenes:
                    if isinstance(s, dict):
                        ep = int(s.get("episode") or 0)
                        sn = int(s.get("scene_number") or 0)
                        key = (ep, sn)
                        # Only allow new scenes for non-completed episodes
                        if ep not in completed_episodes:
                            new_scene_map[key] = s

                # Build final scenes list: start with ALL existing scenes, then merge in new/refined
                final_scenes = []
                seen_keys = set()

                # First pass: Add all existing scenes (preserving everything)
                for key, existing_scene in existing_scene_map.items():
                    ep, sn = key
                    seen_keys.add(key)
                    # If there's a refined version for this scene (and it's not a completed episode), use it
                    if ep not in completed_episodes and key in new_scene_map:
                        final_scenes.append(new_scene_map[key])
                    else:
                        # Keep the existing scene (especially important for completed episodes)
                        final_scenes.append(existing_scene)

                # Second pass: Add any completely new scenes that weren't in existing list
                for s in new_scenes:
                    if isinstance(s, dict):
                        ep = int(s.get("episode") or 0)
                        sn = int(s.get("scene_number") or 0)
                        key = (ep, sn)
                        if key not in seen_keys and ep not in completed_episodes:
                            final_scenes.append(s)
                            seen_keys.add(key)

                # Sort by episode, then scene_number
                final_scenes.sort(key=lambda s: (int(s.get("episode") or 0), int(s.get("scene_number") or 0)))
                parsed["scenes"] = final_scenes
                print(f"[REFINE_STORYLINE] Preserved {len(existing_scene_map)} existing scenes (including {len(completed_episodes)} completed episodes), merged with {len(new_scenes)} new/refined scenes")

    version = int(state.get("storyline_version") or 0) + 1
    parsed.setdefault("meta", {})
    if isinstance(parsed.get("meta"), dict):
        parsed["meta"]["version"] = version
        parsed["meta"]["updated_ts"] = time.time()
        # Preserve existing episode completion metadata
        if isinstance(existing, dict):
            existing_meta = existing.get("meta", {})
            if isinstance(existing_meta, dict):
                existing_episodes = existing_meta.get("episodes", {})
                if isinstance(existing_episodes, dict):
                    parsed["meta"]["episodes"] = existing_episodes

    state["current_storyline"] = parsed
    state["current_storyline_json"] = json.dumps(parsed, ensure_ascii=False)
    state["storyline_version"] = version
    state["storyline_iteration"] = int(state.get("storyline_iteration") or 0) + 1

    # Emit storyline update with full JSON
    add_to_outbox(state, {
        "type": "storyline_update",
        "version": version,
        "storyline": state.get("current_storyline", {}),
        "storyline_json": state.get("current_storyline_json", "{}"),
        "ts": time.time()
    })

    # Validate state
    validation_errors = validate_storyline_state(state)
    if validation_errors:
        print(f"[REFINE_STORYLINE] Validation warnings: {validation_errors}")

    # Persist to disk
    storyline_dir = state.get("storyline_context_dir") or config.get("storyline_context_dir", "default")
    persistence = get_storyline_persistence()
    persistence.save_storyline(storyline_dir, parsed, version, update_type="refine")

    return {"result": "ok", "version": version, "iteration": state["storyline_iteration"]}


def exit_loop(*, tool_context: ToolContext) -> Dict[str, Any]:
    """Signal to a LoopAgent that it should stop iterating."""
    state = tool_context.state
    # Guardrail: do NOT allow "complete" when no storyline exists yet.
    # We saw repeated "Storyline refinement complete (v0)" messages when the reviewer
    # incorrectly called exit_loop before plan_storyline/refine_storyline ever ran.
    try:
        version = int(state.get("storyline_version") or 0)
    except Exception:
        version = 0
    cur = state.get("current_storyline")
    cur_json = state.get("current_storyline_json") or ""

    if version <= 0 or not isinstance(cur, dict) or not cur or not str(cur_json).strip():
        state["storyline_review_status"] = "fail"
        state["review_feedback"] = "No storyline exists yet. Create one first (plan_storyline) before exiting the loop."
        add_message(
            state,
            "group_chat",
            "System",
            "Storyline not created yet (v0). Creating a draft must happen before the refinement loop can exit.",
        )
        return {"result": "blocked", "reason": "no_storyline"}

    tool_context.actions.escalate = True

    # Emit a visible event that the storyline has reached a stopping point.
    add_message(state, "group_chat", "System", f"Storyline refinement complete (v{version}).")
    return {"result": "ok", "version": version}

def _get_agent_id_from_tool_context(tool_context: ToolContext) -> str:
    agent_name = getattr(tool_context, "agent_name", None)
    agent_id = agent_name or getattr(tool_context, "agent_id", None) or getattr(tool_context, "author", None)
    return str(agent_id) if agent_id else "unknown"

def get_episode_progress_summary(state: Dict[str, Any]) -> str:
    """Return human-readable episode progress for agent prompts.

    Args:
        state: Current state dictionary

    Returns:
        Formatted string describing episode progress
    """
    storyline = state.get("current_storyline", {})
    if not isinstance(storyline, dict):
        return "No storyline created yet."

    scenes = storyline.get("scenes", [])
    if not scenes:
        return "Storyline exists but has no scenes yet."

    # Count scenes per episode
    episode_counts: Dict[int, int] = {}
    for scene in scenes:
        if isinstance(scene, dict):
            ep = int(scene.get("episode") or 0)
            if ep > 0:
                episode_counts[ep] = episode_counts.get(ep, 0) + 1

    # Get completion status from meta
    meta = storyline.get("meta", {})
    episodes_meta = meta.get("episodes", {}) if isinstance(meta, dict) else {}
    completed_episodes = set()
    if isinstance(episodes_meta, dict):
        for ep_key, ep_info in episodes_meta.items():
            if isinstance(ep_info, dict) and ep_info.get("complete") is True:
                try:
                    completed_episodes.add(int(ep_key))
                except Exception:
                    pass

    current_ep = int(state.get("current_episode_number") or 1)

    # Build summary
    current_ep = int(state.get("current_episode_number") or 1)
    parts = []

    if current_ep == 1:
        ep1_scenes = episode_counts.get(1, 0)
        parts.append(f"Episode 1: {ep1_scenes}/12 scenes complete.")
        if ep1_scenes >= 12:
            parts.append("STATUS: Episode 1 Complete!")
        elif ep1_scenes == 0:
            parts.append("ACTION REQUIRED: Call plan_storyline() to create initial storyline with at least 3 scenes.")
        else:
            remaining = 12 - ep1_scenes
            parts.append(f"ACTION REQUIRED: Add {remaining} more scene(s) using add_scene_to_episode().")
            parts.append(f"Each scene must have 3-6 panels with dialogue.")
    else:
        parts.append(f"Current episode: {current_ep}")
        for ep_num in sorted(episode_counts.keys()):
            count = episode_counts[ep_num]
            status = "✓ COMPLETE" if ep_num in completed_episodes else "in progress"
            parts.append(f"  Episode {ep_num}: {count} scene(s) - {status}")

    return "\n".join(parts)

def bump_storyline_version(state: Dict[str, Any]) -> int:
    """Increment storyline_version and keep current_storyline_json/meta updated."""
    version = int(state.get("storyline_version") or 0) + 1
    state["storyline_version"] = version
    state["storyline_iteration"] = int(state.get("storyline_iteration") or 0) + 1
    state["last_storyline_update_ts"] = time.time()

    cur = state.get("current_storyline")
    if isinstance(cur, dict):
        cur.setdefault("meta", {})
        if isinstance(cur.get("meta"), dict):
            cur["meta"]["version"] = version
            cur["meta"]["updated_ts"] = time.time()
        try:
            state["current_storyline_json"] = json.dumps(cur, ensure_ascii=False)
        except Exception:
            pass
    return version

def emit_storyline_update(state: Dict[str, Any], *, room: str = "group_chat"):
    cur = state.get("current_storyline")
    payload = cur if isinstance(cur, dict) else {}
    add_to_outbox(
        state,
        {
            "type": "storyline_update",
            "version": int(state.get("storyline_version") or 0),
            "room": room,
            "storyline": payload,
            "storyline_json": state.get("current_storyline_json") or "{}",
            "ts": time.time(),
        },
    )

def add_scene_to_episode(
    scene_summary: str,
    panels: List[Dict[str, Any]],
    episode_number: Optional[int] = None,
    room: str = "group_chat",
    *,
    tool_context: ToolContext,
) -> Dict[str, Any]:
    """Add a new scene to the current episode (or a specified episode if provided)."""
    state = tool_context.state
    cur = state.get("current_storyline")
    if not isinstance(cur, dict) or not cur:
        return {"result": "fail", "message": "No current_storyline exists yet."}

    if episode_number is None:
        try:
            episode_number = int(state.get("current_episode_number") or 1)
        except Exception:
            episode_number = 1

    # Prevent adding scenes to completed episodes
    meta = cur.get("meta") if isinstance(cur.get("meta"), dict) else {}
    episodes_meta = meta.get("episodes") if isinstance(meta, dict) else {}
    if isinstance(episodes_meta, dict):
        ep_info = episodes_meta.get(str(int(episode_number)))
        if isinstance(ep_info, dict) and ep_info.get("complete") is True:
            try:
                current_ep = int(state.get("current_episode_number") or (int(episode_number) + 1))
            except Exception:
                current_ep = int(episode_number) + 1
            add_message(state, room, "System", f"Episode {episode_number} is complete. Please add scenes to episode {current_ep}.")
            return {
                "result": "fail",
                "message": f"Episode {episode_number} is already complete. Work on episode {current_ep} instead.",
            }

    scenes = cur.get("scenes")
    if not isinstance(scenes, list):
        scenes = []
        cur["scenes"] = scenes

    if not isinstance(panels, list) or not (3 <= len(panels) <= 6):
        return {"result": "fail", "message": "Each scene must contain between 3 and 6 panels."}

    normalized_panels: list[dict[str, Any]] = []
    next_panel_num = 1
    for p in panels:
        if not isinstance(p, dict):
            continue
        normalized_panels.append(
            {
                "panel_number": int(p.get("panel_number") or next_panel_num),
                "visual_description": str(p.get("visual_description") or ""),
                "dialogue": str(p.get("dialogue") or ""),
                "mood": str(p.get("mood") or ""),
            }
        )
        next_panel_num += 1
    if not normalized_panels:
        return {"result": "fail", "message": "No valid panel objects provided."}

    max_scene_num = 0
    for s in scenes:
        if isinstance(s, dict) and int(s.get("episode") or 0) == int(episode_number):
            try:
                max_scene_num = max(max_scene_num, int(s.get("scene_number") or 0))
            except Exception:
                pass
    new_scene_number = max_scene_num + 1

    scenes.append(
        {
            "episode": int(episode_number),
            "scene_number": int(new_scene_number),
            "summary": str(scene_summary or ""),
            "panels": normalized_panels,
        }
    )

    version = bump_storyline_version(state)
    emit_storyline_update(state, room=room)

    # Progress check for fixed 12 scenes
    progress_msg = f"Added scene {episode_number}.{new_scene_number} (v{version})."
    if int(episode_number) == 1:
        progress_msg += f" Progress: {new_scene_number}/12."
        if new_scene_number >= 12:
            progress_msg += " Episode 1 is now complete!"
            add_message(state, room, "System", progress_msg)
            process_episode_completion(state, 1, room=room)
            return {"result": "ok", "version": version, "episode": 1, "scene_number": 12, "completed": True}

    add_message(state, room, "System", progress_msg)

    # Update progress tracking
    ep_key = str(int(episode_number))
    if "episode_scene_counts" not in state:
        state["episode_scene_counts"] = {}
    state["episode_scene_counts"][ep_key] = state["episode_scene_counts"].get(ep_key, 0) + 1
    if "update_types_log" not in state:
        state["update_types_log"] = []
    state["update_types_log"].append("add_scene")
    state["last_major_update_ts"] = time.time()

    # Persist to disk
    storyline_dir = state.get("storyline_context_dir") or config.get("storyline_context_dir", "default")
    persistence = get_storyline_persistence()
    persistence.save_storyline(storyline_dir, cur, version, update_type="add_scene")

    return {"result": "ok", "version": version, "episode": int(episode_number), "scene_number": int(new_scene_number)}

def refine_scene(
    scene_number: int,
    refinements: Dict[str, Any],
    episode_number: Optional[int] = None,
    room: str = "group_chat",
    *,
    tool_context: ToolContext,
) -> Dict[str, Any]:
    """Refine an existing scene by adding panels or updating panel fields."""
    state = tool_context.state
    cur = state.get("current_storyline")
    if not isinstance(cur, dict) or not cur:
        return {"result": "fail", "message": "No current_storyline exists yet."}

    # Default to current episode if not specified
    if episode_number is None:
        try:
            episode_number = int(state.get("current_episode_number") or 1)
        except Exception:
            episode_number = 1

    # Prevent refining completed episodes
    meta = cur.get("meta") if isinstance(cur.get("meta"), dict) else {}
    episodes_meta = meta.get("episodes") if isinstance(meta, dict) else {}
    if isinstance(episodes_meta, dict):
        ep_info = episodes_meta.get(str(int(episode_number)))
        if isinstance(ep_info, dict) and ep_info.get("complete") is True:
            try:
                current_ep = int(state.get("current_episode_number") or (int(episode_number) + 1))
            except Exception:
                current_ep = int(episode_number) + 1
            add_message(state, room, "System", f"Episode {episode_number} is complete. Please refine episode {current_ep} instead.")
            return {
                "result": "fail",
                "message": f"Episode {episode_number} is already complete. Refine episode {current_ep} instead.",
            }

    scenes = cur.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return {"result": "fail", "message": "current_storyline.scenes is empty."}

    target: Optional[dict[str, Any]] = None
    for s in scenes:
        if not isinstance(s, dict):
            continue
        if int(s.get("episode") or 0) == int(episode_number) and int(s.get("scene_number") or 0) == int(scene_number):
            target = s
            break
    if not target:
        return {"result": "fail", "message": f"Scene not found: episode={episode_number}, scene_number={scene_number}."}

    if not isinstance(refinements, dict):
        refinements = {}

    if "summary" in refinements and isinstance(refinements.get("summary"), str):
        target["summary"] = refinements["summary"]

    panels = target.get("panels")
    if not isinstance(panels, list):
        panels = []
        target["panels"] = panels

    max_panel_num = 0
    for p in panels:
        if isinstance(p, dict):
            try:
                max_panel_num = max(max_panel_num, int(p.get("panel_number") or 0))
            except Exception:
                pass

    panels_to_add = refinements.get("panels_to_add")
    if isinstance(panels_to_add, list) and panels_to_add:
        for raw in panels_to_add:
            if not isinstance(raw, dict):
                continue
            max_panel_num += 1
            panels.append(
                {
                    "panel_number": int(raw.get("panel_number") or max_panel_num),
                    "visual_description": str(raw.get("visual_description") or ""),
                    "dialogue": str(raw.get("dialogue") or ""),
                    "mood": str(raw.get("mood") or ""),
                }
            )

    def _apply_map(update_map: Any, field: str):
        if not isinstance(update_map, dict):
            return
        for p in panels:
            if not isinstance(p, dict):
                continue
            pn = p.get("panel_number")
            try:
                key = str(int(pn))
            except Exception:
                key = str(pn)
            if key in update_map and isinstance(update_map[key], str):
                p[field] = update_map[key]

    _apply_map(refinements.get("dialogue_updates"), "dialogue")
    _apply_map(refinements.get("visual_updates"), "visual_description")
    _apply_map(refinements.get("mood_updates"), "mood")

    # Enforce panel count constraint: 3-6 panels
    if not (3 <= len(panels) <= 6):
        # We don't fail here to avoid blocking reasonable refinements,
        # but we warn and might want to restrict it later.
        # For now, let's just log a warning.
        print(f"[REFINE_SCENE] Warning: Scene {episode_number}.{scene_number} has {len(panels)} panels (target 3-6).")

    version = bump_storyline_version(state)
    emit_storyline_update(state, room=room)
    add_message(state, room, "System", f"Refined scene {episode_number}.{scene_number} (v{version}).")

    # Persist to disk
    storyline_dir = state.get("storyline_context_dir") or config.get("storyline_context_dir", "default")
    persistence = get_storyline_persistence()
    persistence.save_storyline(storyline_dir, cur, version, update_type="refine_scene")

    return {"result": "ok", "version": version, "episode": int(episode_number), "scene_number": int(scene_number)}

def propose_episode_complete(
    episode_number: int,
    completion_reason: str,
    room: str = "group_chat",
    *,
    tool_context: ToolContext,
) -> Dict[str, Any]:
    """Store an episode completion proposal from the calling agent."""
    state = tool_context.state
    agent_id = _get_agent_id_from_tool_context(tool_context)
    proposals = state.get("episode_completion_proposals")
    if not isinstance(proposals, dict):
        proposals = {}
        state["episode_completion_proposals"] = proposals
    proposals[agent_id] = {
        "episode_number": int(episode_number),
        "reason": str(completion_reason or ""),
        "ts": time.time(),
    }
    add_message(state, room, "System", f"{agent_id} proposed completing episode {episode_number}.")
    return {"result": "ok", "episode_number": int(episode_number), "agent_id": agent_id}

def check_episode_completion_votes(state: Dict[str, Any], *, episode_number: int) -> bool:
    votes = state.get("episode_completion_votes")
    if not isinstance(votes, dict):
        return False
    yes = 0
    for aid in ["a1", "a2", "a3"]:
        v = votes.get(aid)
        if not isinstance(v, dict):
            continue
        if int(v.get("episode_number") or 0) != int(episode_number):
            continue
        if bool(v.get("vote")):
            yes += 1
    return yes >= 2

def detect_votes_in_text(text: str, lang: str = "en") -> tuple[bool, int | None]:
    """
    Detect if text contains a vote to complete an episode.
    Returns (has_vote, episode_number) where episode_number is None if not specified.
    """
    if not text or not isinstance(text, str):
        return (False, None)

    text_lower = text.lower()

    # NOTE: Keep detection reasonably strict to avoid false positives.
    # We require an explicit "vote"/"投票"/"贊成票"/"完成第X集" intent, not just generic "yes"/"agree"/"好".
    import re

    vote_intent_patterns = {
        "en": [
            r"\b(i\s+)?vote\s+yes\b",
            r"\b(i\s+)?vote\s+to\s+(complete|finish)\b",
            r"\bcomplete\s+episode\b",
            r"\bfinish\s+episode\b",
        ],
        "zh_Hans": [
            r"投(票)?(赞成票|贊成票)",
            r"我投(票)?(赞成票|贊成票)",
            r"(完成|结束)第?\s*\d+\s*集",
            r"(完成|结束)剧集",
            r"剧集完成",
        ],
        "zh_Hant": [
            r"投(票)?贊成票",
            r"我投(票)?贊成票",
            r"(完成|結束)第?\s*\d+\s*集",
            r"(完成|結束)劇集",
            r"劇集完成",
        ],
    }

    patterns = vote_intent_patterns.get(lang, vote_intent_patterns["en"])
    has_vote = any(re.search(p, text, flags=re.IGNORECASE) for p in patterns)
    if not has_vote:
        return (False, None)

    # Try to extract episode number
    # Look for patterns like "episode 1", "episode 2", "第1集", "第2集", etc.
    ep_patterns = {
        "en": [r"episode\s+(\d+)", r"ep\s+(\d+)"],
        "zh_Hans": [r"第(\d+)集", r"剧集\s*(\d+)"],
        "zh_Hant": [r"第(\d+)集", r"劇集\s*(\d+)"],
    }

    patterns = ep_patterns.get(lang, ep_patterns["en"])
    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            try:
                ep_num = int(match.group(1))
                return (True, ep_num)
            except (ValueError, IndexError):
                pass

    # If vote detected but no episode number, return True with None
    return (True, None)

def process_episode_completion(state: Dict[str, Any], episode_number: int, room: str = "group_chat") -> Dict[str, Any]:
    """
    Shared helper to process episode completion: mark complete, bump version, move to next episode, persist.
    Returns dict with completion status and version.
    """
    cur = state.get("current_storyline")
    if isinstance(cur, dict):
        cur.setdefault("meta", {})
        if isinstance(cur.get("meta"), dict):
            cur["meta"].setdefault("episodes", {})
            if isinstance(cur["meta"].get("episodes"), dict):
                ep_key = str(int(episode_number))
                cur["meta"]["episodes"].setdefault(ep_key, {})
                if isinstance(cur["meta"]["episodes"][ep_key], dict):
                    cur["meta"]["episodes"][ep_key]["complete"] = True
                    cur["meta"]["episodes"][ep_key]["completed_ts"] = time.time()

    version = bump_storyline_version(state)
    emit_storyline_update(state, room=room)
    add_to_outbox(
        state,
        {
            "type": "episode_complete",
            "episode_number": int(episode_number),
            "version": version,
            "room": room,
            "ts": time.time(),
            "title": (state.get("current_storyline") or {}).get("title", "")
            if isinstance(state.get("current_storyline"), dict)
            else "",
        },
    )
    add_message(state, room, "System", f"Episode {episode_number} marked complete (v{version}).")

    # Clear votes and proposals
    state["episode_completion_proposals"] = {}
    state["episode_completion_votes"] = {}

    # Move to next episode
    try:
        next_ep = int(episode_number) + 1
        state["current_episode_number"] = next_ep
    except Exception:
        next_ep = 1
        state["current_episode_number"] = 1

    add_message(state, room, "System", f"Episode {episode_number} complete. Starting work on Episode {next_ep}.")

    # Update progress tracking
    if "update_types_log" not in state:
        state["update_types_log"] = []
    state["update_types_log"].append("complete_episode")
    state["last_major_update_ts"] = time.time()

    # Persist to disk
    storyline_dir = state.get("storyline_context_dir") or config.get("storyline_context_dir", "default")
    persistence = get_storyline_persistence()
    persistence.save_storyline(storyline_dir, cur, version, update_type="complete_episode")

    return {"completed": True, "episode_number": int(episode_number), "version": version, "next_episode": next_ep}

def vote_episode_complete(
    episode_number: int,
    vote: bool,
    room: str = "group_chat",
    *,
    tool_context: ToolContext,
) -> Dict[str, Any]:
    """Vote on episode completion. If 2/3 vote yes, mark episode complete and emit episode_complete."""
    state = tool_context.state
    agent_id = _get_agent_id_from_tool_context(tool_context)
    votes = state.get("episode_completion_votes")
    if not isinstance(votes, dict):
        votes = {}
        state["episode_completion_votes"] = votes
    votes[agent_id] = {"episode_number": int(episode_number), "vote": bool(vote), "ts": time.time()}

    if check_episode_completion_votes(state, episode_number=int(episode_number)):
        result = process_episode_completion(state, int(episode_number), room=room)
        return {"result": "ok", "completed": True, "episode_number": int(episode_number), "version": result["version"]}

    return {"result": "ok", "completed": False, "episode_number": int(episode_number), "agent_id": agent_id}

def propose_story_complete(
    completion_reason: str,
    room: str = "group_chat",
    *,
    tool_context: ToolContext,
) -> Dict[str, Any]:
    """Store a proposal that the overall story is complete (does not complete it)."""
    state = tool_context.state
    agent_id = _get_agent_id_from_tool_context(tool_context)
    proposals = state.get("story_completion_proposals")
    if not isinstance(proposals, dict):
        proposals = {}
        state["story_completion_proposals"] = proposals
    proposals[agent_id] = {"reason": str(completion_reason or ""), "ts": time.time()}
    add_message(state, room, "System", f"{agent_id} proposed that the story is complete.")
    return {"result": "ok", "agent_id": agent_id}

def _check_story_completion_votes(state: Dict[str, Any]) -> bool:
    votes = state.get("story_completion_votes")
    if not isinstance(votes, dict):
        return False
    yes = 0
    for aid in ["a1", "a2", "a3"]:
        v = votes.get(aid)
        if not isinstance(v, dict):
            continue
        if bool(v.get("vote")):
            yes += 1
    return yes >= 2

def vote_story_complete(
    vote: bool,
    room: str = "group_chat",
    *,
    tool_context: ToolContext,
) -> Dict[str, Any]:
    """Vote on whether the overall story is complete. If 2/3 vote yes, mark story_complete and emit story_complete."""
    state = tool_context.state
    agent_id = _get_agent_id_from_tool_context(tool_context)
    votes = state.get("story_completion_votes")
    if not isinstance(votes, dict):
        votes = {}
        state["story_completion_votes"] = votes
    votes[agent_id] = {"vote": bool(vote), "ts": time.time()}

    if _check_story_completion_votes(state):
        cur = state.get("current_storyline")
        if isinstance(cur, dict):
            cur.setdefault("meta", {})
            if isinstance(cur.get("meta"), dict):
                cur["meta"]["story_complete"] = True
                cur["meta"]["story_completed_ts"] = time.time()

        version = _bump_storyline_version(state)
        _emit_storyline_update(state, room=room)
        add_to_outbox(
            state,
            {
                "type": "story_complete",
                "version": version,
                "room": room,
                "ts": time.time(),
                "title": (state.get("current_storyline") or {}).get("title", "")
                if isinstance(state.get("current_storyline"), dict)
                else "",
            },
        )
        add_message(state, room, "System", f"Story marked complete (v{version}).")
        state["story_completion_proposals"] = {}
        state["story_completion_votes"] = {}
        return {"result": "ok", "completed": True, "version": version}

    return {"result": "ok", "completed": False, "agent_id": agent_id}


def compute_storyline_milestone(
    state: Dict[str, Any],
    *,
    room: str = "group_chat",
    min_messages: int = 12,
) -> bool:
    """Pure helper: decide whether to auto-trigger storyline planning.

    Heuristics:
    - Only trigger once per session (state['storyline_triggered']).
    - Trigger if enough chat messages have accumulated OR explicit keywords show up.
    """
    already_triggered = state.get("storyline_triggered", False)
    current_storyline = state.get("current_storyline", {})
    storyline_version = state.get("storyline_version", 0)

    # Allow re-triggering if storyline was triggered but never actually created
    if already_triggered:
        if not current_storyline or storyline_version == 0:
            print(f"[MILESTONE] Storyline was triggered but never created, allowing re-trigger")
            # Reset the flag to allow re-triggering
            state["storyline_triggered"] = False
        else:
            print(f"[MILESTONE] Storyline already triggered and exists (v{storyline_version}), skipping")
            return False

    history = (state.get("history") or {}).get(room) or []
    history_count = len(history)
    print(f"[MILESTONE] Checking milestone: history_count={history_count}, min_messages={min_messages}, room={room}")

    if history_count >= min_messages:
        print(f"[MILESTONE] Milestone reached: {history_count} messages >= {min_messages}")
        return True

    keywords = [
        "webtoon",
        "웹툰",
        "comic",
        "manhwa",
        "스토리",
        "storyline",
        "two masc lesbian",
        "masc lesbian",
    ]

    # Check the latest user message if present, otherwise scan last few messages.
    latest = state.get("new_message") or ""
    text_blob = str(latest)
    if not text_blob and history:
        tail = history[-6:]
        text_blob = " ".join(str(m.get("text", "")) for m in tail if isinstance(m, dict))

    text_lower = text_blob.lower()
    keyword_match = any(k.lower() in text_lower for k in keywords)
    if keyword_match:
        matched_keywords = [k for k in keywords if k.lower() in text_lower]
        print(f"[MILESTONE] Keyword match found: {matched_keywords}")
        return True

    print(f"[MILESTONE] No milestone reached: history_count={history_count}, keyword_match={keyword_match}")
    return False

def compute_storyline_expansion_milestone(
    state: Dict[str, Any],
    *,
    room: str = "group_chat",
    min_messages_since_update: int = 6,
) -> bool:
    """Steer personas to continue/refine the existing storyline (without rerunning planning loop)."""
    cur = state.get("current_storyline")
    if not isinstance(cur, dict) or not cur:
        return False

    # Don't push expansion if current episode already complete
    try:
        current_ep = int(state.get("current_episode_number") or 1)
    except Exception:
        current_ep = 1
    meta = cur.get("meta") if isinstance(cur.get("meta"), dict) else {}
    episodes_meta = meta.get("episodes") if isinstance(meta, dict) else {}
    if isinstance(episodes_meta, dict):
        ep_info = episodes_meta.get(str(current_ep))
        if isinstance(ep_info, dict) and ep_info.get("complete") is True:
            return False

    history = (state.get("history") or {}).get(room) or []
    if not isinstance(history, list) or not history:
        return False

    last_update_ts = float(state.get("last_storyline_update_ts") or 0.0)
    msgs_since_update = 0
    for m in reversed(history):
        if not isinstance(m, dict):
            continue
        ts = float(m.get("ts") or 0.0)
        if ts <= last_update_ts:
            break
        msgs_since_update += 1

    keywords = ["webtoon", "웹툰", "comic", "manhwa", "panel", "panels", "scene", "scenes", "episode", "storyline", "plot"]
    latest = state.get("new_message") or ""
    text_blob = str(latest)
    if not text_blob and history:
        tail = history[-8:]
        text_blob = " ".join(str(m.get("text", "")) for m in tail if isinstance(m, dict))
    text_lower = text_blob.lower()
    keyword_match = any(k in text_lower for k in keywords)

    if keyword_match:
        return True
    if msgs_since_update >= int(min_messages_since_update):
        return True
    return False

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



