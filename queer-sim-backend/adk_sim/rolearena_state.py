"""
RoleArena-style state initialization and management.

Based on the RoleArena research paper, this module provides:
- Discrete plot node structure for Girls' Love stories
- Director controls (pace, spice, angst, comedy)
- Turn-by-turn tracking (node_idx, node_turns, total_turns)
- Quality flags for monitoring story health
"""

import time
from typing import Any, Dict, List, Optional
import logging

# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

def init_rolearena_story_state(
    director_first_message: str,
    controls: Optional[Dict[str, Any]] = None,
    seed: Optional[int] = None,
    num_nodes: int = 9,
) -> Dict[str, Any]:
    """
    Initialize a RoleArena-style story state with discrete plot nodes.

    Args:
        director_first_message: Initial message from director (user)
        controls: Director controls (pace, spice, angst, comedy)
        seed: Random seed for reproducibility
        num_nodes: Number of plot nodes to generate (default 9 for GL arc)

    Returns:
        Dictionary containing RoleArena state structure
    """
    logger.info("[ROLEARENA_STATE] Initializing RoleArena story state")
    logger.info(f"[ROLEARENA_STATE] Director message: {director_first_message[:100]}...")

    if seed is not None:
        import random
        random.seed(seed)

    controls = controls or {"pace": "slow", "spice": 1, "angst": 2, "comedy": 1}
    logger.info(f"[ROLEARENA_STATE] Controls: {controls}")

    budgets = _pace_to_budgets(controls.get("pace", "slow"))
    logger.info(f"[ROLEARENA_STATE] Budgets: {budgets}")

    # Default 3-character GL dynamic
    characters = {
        "a1": {
            "name": "A1",
            "role": "competent, guarded protagonist",
            "traits": ["controlled", "reliable", "secretly soft", "observant", "protective"],
            "wants": "to stay in control and not be vulnerable, but craves real intimacy",
            "limits": {"soft": ["explicit sex on-screen"], "hard": ["sexual violence", "non-consent", "incest"]}
        },
        "a2": {
            "name": "A2",
            "role": "warm, perceptive counterpart",
            "traits": ["gentle", "bold honesty", "empathetic", "playful", "persistent"],
            "wants": "to be chosen openly, not kept as a secret",
            "limits": {"soft": ["explicit sex on-screen"], "hard": ["sexual violence", "non-consent", "incest"]}
        },
        "a3": {
            "name": "A3",
            "role": "pressure engine (friend/coworker/rival) with believable motives",
            "traits": ["socially savvy", "well-meaning but messy", "competitive", "sharp", "noticing"],
            "wants": "to protect their own place/status, even if it complicates others",
            "limits": {"soft": ["explicit sex on-screen"], "hard": ["sexual violence", "non-consent", "incest"]}
        }
    }

    # Generate discrete plot nodes for GL arc
    nodes = _generate_gl_plot_nodes(num_nodes)
    logger.info(f"[ROLEARENA_STATE] Generated {len(nodes)} plot nodes")
    for i, node in enumerate(nodes):
        logger.info(f"[ROLEARENA_STATE]   Node {i}: {node['beat']}")

    state = {
        "series": {
            "genre": "girlslove",
            "tone": "slow-burn" if controls["pace"] == "slow" else "romance",
            "rating": "PG-13"
        },
        "characters": characters,
        "plot": {
            "nodes": nodes,
            "node_idx": 0,
            "node_turns": 0,
            "total_turns": 0,
            "turn_budget": budgets["turn_budget"],
            "node_budget": budgets["node_budget"]
        },
        "director": {
            "latest_goal": director_first_message.strip(),
            "constraints": [],
            "controls": controls
        },
        "dialogue": [
            {"turn_id": 0, "speaker": "director", "content": director_first_message, "timestamp": _now_iso()}
        ],
        "quality_flags": {
            "repetition_risk": 0.0,
            "character_drift_risk": 0.0,
            "plot_stall_risk": 0.0
        },
        # Environment agent turn plan (updated every turn)
        "env_turn_plan": {},
        # Advance detection
        "advance_candidate": False,
        "advance_reason": "",
        # Critic approval
        "critic_approved": False,
        "critic_verdict": {},
        # Narration tracking
        "narrations": [],
        "character_responses": []
    }

    logger.info("[ROLEARENA_STATE] RoleArena state initialized successfully")
    logger.info(f"[ROLEARENA_STATE] Starting at node {state['plot']['node_idx']}: {nodes[0]['beat']}")

    return state


def _pace_to_budgets(pace: str) -> Dict[str, Dict[str, int]]:
    """Convert pace setting to turn/node budgets."""
    logger.info(f"[ROLEARENA_STATE] Converting pace '{pace}' to budgets")

    if pace == "slow":
        return {
            "turn_budget": {"min": 50, "max": 90},
            "node_budget": {"min": 3, "target": 5, "hard_cap": 7}
        }
    if pace == "fast":
        return {
            "turn_budget": {"min": 28, "max": 55},
            "node_budget": {"min": 2, "target": 3, "hard_cap": 5}
        }
    # med
    return {
        "turn_budget": {"min": 40, "max": 75},
        "node_budget": {"min": 3, "target": 4, "hard_cap": 6}
    }


def _generate_gl_plot_nodes(num_nodes: int = 9) -> List[Dict[str, Any]]:
    """
    Generate discrete plot nodes for a Girls' Love arc.

    Each node represents a story beat with:
    - id: node index
    - beat: short descriptive name
    - goal: what should be achieved in this node
    - stakes: emotional/dramatic weight
    - exit_conditions: list of conditions that signal node completion
    """
    logger.info(f"[ROLEARENA_STATE] Generating {num_nodes} GL plot nodes")

    # Standard 9-node GL arc
    nodes: List[Dict[str, Any]] = [
        {
            "id": 0,
            "beat": "Setup + Spark",
            "goal": "Establish setting, dynamic, and the first undeniable spark between a1 and a2.",
            "stakes": "Low but intimate: a glance, a small rescue, a subtle kindness that lingers.",
            "exit_conditions": [
                "a1 notices a2 in a way she can't dismiss",
                "a2 gets a private moment that shows she sees through a1"
            ]
        },
        {
            "id": 1,
            "beat": "Proximity Lock-in",
            "goal": "Force repeated interaction (shared task, roommate, project, travel, etc.).",
            "stakes": "They can't avoid each other; tension becomes routine.",
            "exit_conditions": [
                "a1 and a2 must coordinate on something important",
                "a3 becomes aware of their closeness"
            ]
        },
        {
            "id": 2,
            "beat": "Misread / Misunderstanding Seeded by a3",
            "goal": "Introduce a believable misunderstanding without making anyone evil.",
            "stakes": "Trust wobbles; subtext thickens.",
            "exit_conditions": [
                "a2 interprets a1's action as distance or rejection",
                "a3 unintentionally amplifies the misread"
            ]
        },
        {
            "id": 3,
            "beat": "Almost-Date Scenario",
            "goal": "Create a scene that feels like a date but can be denied out loud.",
            "stakes": "A tender memory forms; denial hurts more.",
            "exit_conditions": [
                "they share a soft moment (laughter, shared music, helping hands)",
                "a1 almost says something real but stops"
            ]
        },
        {
            "id": 4,
            "beat": "Small Vulnerability Reveal",
            "goal": "One character reveals a fear/need indirectly.",
            "stakes": "Emotional intimacy increases; stakes become personal.",
            "exit_conditions": [
                "a1 reveals a fear (control, abandonment, reputation) through action/subtext",
                "a2 responds with care, not pressure"
            ]
        },
        {
            "id": 5,
            "beat": "External Pressure Event",
            "goal": "Add outside stakes (rumor, deadline, family expectation, public scene).",
            "stakes": "They must choose how to show up in public.",
            "exit_conditions": [
                "a3 triggers or embodies the external pressure (not necessarily malicious)",
                "a1 makes a protective choice that has a cost"
            ]
        },
        {
            "id": 6,
            "beat": "Choice Point",
            "goal": "Force a decision: hide vs risk, retreat vs reach.",
            "stakes": "A turning point that can't be undone.",
            "exit_conditions": [
                "a2 asks for clarity (directly or indirectly)",
                "a1 takes a measurable step (not necessarily confession)"
            ]
        },
        {
            "id": 7,
            "beat": "Near-Confession / Confession",
            "goal": "Deliver a confession or near-confession aligned with pace.",
            "stakes": "If slow pace: imperfect confession; if fast pace: more direct.",
            "exit_conditions": [
                "a1 states desire or chooses a2 in unmistakable terms",
                "a2 accepts with boundaries"
            ]
        },
        {
            "id": 8,
            "beat": "Aftermath Calibration + Hook",
            "goal": "Process consequences, restore safety, set next arc hook.",
            "stakes": "Hope + fear. A new problem is teased.",
            "exit_conditions": [
                "they define what 'us' means for now",
                "a new complication is introduced (gentle cliffhanger)"
            ]
        }
    ]

    # If fewer nodes requested, take first N; if more, we could extend but for now just warn
    if num_nodes < len(nodes):
        logger.warning(f"[ROLEARENA_STATE] Requested {num_nodes} nodes but have {len(nodes)}, truncating")
        nodes = nodes[:num_nodes]
    elif num_nodes > len(nodes):
        logger.warning(f"[ROLEARENA_STATE] Requested {num_nodes} nodes but only have {len(nodes)}, using all")

    return nodes


def _now_iso() -> str:
    """Return current timestamp in ISO format."""
    from datetime import datetime
    return datetime.utcnow().isoformat() + "Z"


def advance_plot_node(state: Dict[str, Any], bridge_narration: str = "") -> None:
    """
    Advance to the next plot node.

    Args:
        state: Current RoleArena state
        bridge_narration: Optional narration to bridge the transition
    """
    plot = state.get("plot", {})
    current_idx = plot.get("node_idx", 0)
    nodes = plot.get("nodes", [])

    if current_idx >= len(nodes) - 1:
        logger.warning(f"[ROLEARENA_STATE] Already at final node {current_idx}, cannot advance")
        return

    new_idx = current_idx + 1
    plot["node_idx"] = new_idx
    plot["node_turns"] = 0  # Reset turn counter for new node

    logger.info(f"[ROLEARENA_STATE] ✓ Plot advanced from node {current_idx} to {new_idx}")
    logger.info(f"[ROLEARENA_STATE]   Previous: {nodes[current_idx]['beat']}")
    logger.info(f"[ROLEARENA_STATE]   Current:  {nodes[new_idx]['beat']}")

    if bridge_narration:
        state.setdefault("narrations", []).append({
            "type": "bridge",
            "from_node": current_idx,
            "to_node": new_idx,
            "narration": bridge_narration,
            "timestamp": _now_iso()
        })
        logger.info(f"[ROLEARENA_STATE]   Bridge narration added: {bridge_narration[:80]}...")


def increment_turn(state: Dict[str, Any]) -> None:
    """Increment turn counters."""
    plot = state.get("plot", {})
    plot["node_turns"] = plot.get("node_turns", 0) + 1
    plot["total_turns"] = plot.get("total_turns", 0) + 1

    logger.info(f"[ROLEARENA_STATE] Turn incremented: node_turns={plot['node_turns']}, total_turns={plot['total_turns']}")


def get_current_node(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Get the current plot node."""
    plot = state.get("plot", {})
    node_idx = plot.get("node_idx", 0)
    nodes = plot.get("nodes", [])

    if 0 <= node_idx < len(nodes):
        return nodes[node_idx]
    return None


def get_next_node(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Get the next plot node (for critic preview)."""
    plot = state.get("plot", {})
    node_idx = plot.get("node_idx", 0)
    nodes = plot.get("nodes", [])

    next_idx = node_idx + 1
    if 0 <= next_idx < len(nodes):
        return nodes[next_idx]
    return None


def update_director_intent(state: Dict[str, Any], goal: str, constraints: List[str], controls: Dict[str, Any]) -> None:
    """Update director intent from DirectorIntentParser output."""
    director = state.setdefault("director", {})
    director["latest_goal"] = goal
    director["constraints"] = constraints
    director["controls"] = controls

    logger.info(f"[ROLEARENA_STATE] Director intent updated:")
    logger.info(f"[ROLEARENA_STATE]   Goal: {goal[:80]}...")
    logger.info(f"[ROLEARENA_STATE]   Constraints: {constraints}")
    logger.info(f"[ROLEARENA_STATE]   Controls: {controls}")


def update_quality_flags(state: Dict[str, Any], flags: Dict[str, float]) -> None:
    """Update quality monitoring flags."""
    state.setdefault("quality_flags", {}).update(flags)

    logger.info(f"[ROLEARENA_STATE] Quality flags updated: {flags}")
    for key, value in flags.items():
        if value > 0.7:
            logger.warning(f"[ROLEARENA_STATE] ⚠️  High {key}: {value:.2f}")

