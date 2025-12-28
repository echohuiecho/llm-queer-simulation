"""
RoleArena-style agents for plot-driven narrative control.

This module implements:
- DirectorIntentParser: extracts user intent into structured controls
- EnvAgent: always-on environment agent that runs every turn
- CriticGate: pacing controller that approves/rejects plot advances
- EnvAdvanceJudge: determines if current node is ready to advance
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from google.adk.agents import LlmAgent
from google.adk.tools.tool_context import ToolContext
from config import config

# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

MODEL_NAME = "gemini-2.0-flash"

# Load prompt templates
PROMPTS_DIR = Path(__file__).parent.parent / "runtime" / "prompts"

def load_prompt(filename: str) -> str:
    """Load a prompt template from the prompts directory."""
    prompt_path = PROMPTS_DIR / filename
    if not prompt_path.exists():
        logger.warning(f"[ROLEARENA_AGENTS] Prompt file not found: {prompt_path}")
        return ""
    return prompt_path.read_text()


# ============================================================================
# DirectorIntentParser
# ============================================================================

def create_director_intent_parser() -> LlmAgent:
    """
    Create DirectorIntentParser agent.

    Extracts user intent into structured format:
    - director_goal: what the user wants
    - constraints: do-not rules
    - controls: pace/spice/angst/comedy sliders
    - branch_hint: optional plot direction
    """
    logger.info("[ROLEARENA_AGENTS] Creating DirectorIntentParser agent")

    instruction = load_prompt("director_intent_parser.txt")

    return LlmAgent(
        name="DirectorIntentParser",
        model=MODEL_NAME,
        instruction=instruction,
        description="Parses director (user) messages into structured intent and controls",
        tools=[],  # Pure LLM, no tools
    )


# ============================================================================
# EnvAgent (Environment Agent)
# ============================================================================

def create_env_agent() -> LlmAgent:
    """
    Create EnvAgent (Environment/Showrunner).

    Runs every turn to:
    - Generate scene narration (1-3 sentences)
    - Choose next speaker and set micro-objectives for all characters
    - Track plot node state and decide if ready to advance
    - Maintain GL tone and director controls
    """
    logger.info("[ROLEARENA_AGENTS] Creating EnvAgent")

    instruction = load_prompt("env_agent.txt")

    return LlmAgent(
        name="EnvAgent",
        model=MODEL_NAME,
        instruction=instruction,
        description="Environment agent that controls narration, speaker selection, and plot advancement",
        tools=[],  # No tools, outputs to state
        output_key="env_turn_plan",  # Write TurnPlan to state
    )


# ============================================================================
# CriticGate
# ============================================================================

def create_critic_gate() -> LlmAgent:
    """
    Create CriticGate (Pacing Controller).

    Only runs when EnvAgent sets advance_candidate=true.
    Approves or rejects plot node advancement based on:
    - Turn budgets (min/target/hard_cap)
    - Director pace settings
    - Story development quality
    """
    logger.info("[ROLEARENA_AGENTS] Creating CriticGate")

    instruction = load_prompt("critic_gate.txt")

    return LlmAgent(
        name="CriticGate",
        model=MODEL_NAME,
        instruction=instruction,
        description="Pacing critic that approves/rejects plot node advances",
        tools=[],
        output_key="critic_verdict",
    )


# ============================================================================
# EnvAdvanceJudge (hybrid: semantic + heuristic)
# ============================================================================

def should_advance_node(
    state: Dict[str, Any],
    recent_dialogue: str,
    *,
    tool_context: Optional[ToolContext] = None
) -> Dict[str, bool]:
    """
    Determine if current plot node should advance.

    This is a hybrid approach:
    1. Heuristic checks (node_turns vs budgets)
    2. Semantic check (are exit conditions satisfied?)

    Args:
        state: Current RoleArena state
        recent_dialogue: Recent dialogue for semantic analysis
        tool_context: Optional tool context for LLM call

    Returns:
        {"should_advance": bool, "reason": str, "heuristic": bool, "semantic": bool}
    """
    logger.info("[ROLEARENA_AGENTS] EnvAdvanceJudge evaluating node advancement")

    plot = state.get("plot", {})
    node_idx = plot.get("node_idx", 0)
    node_turns = plot.get("node_turns", 0)
    nodes = plot.get("nodes", [])
    node_budget = plot.get("node_budget", {})

    min_turns = node_budget.get("min", 3)
    target_turns = node_budget.get("target", 5)
    hard_cap = node_budget.get("hard_cap", 7)

    logger.info(f"[ROLEARENA_AGENTS]   Node {node_idx}, turns: {node_turns}/{target_turns} (min:{min_turns}, cap:{hard_cap})")

    # Current node
    current_node = nodes[node_idx] if node_idx < len(nodes) else None
    if not current_node:
        logger.warning(f"[ROLEARENA_AGENTS]   No current node found at index {node_idx}")
        return {"should_advance": False, "reason": "no_current_node", "heuristic": False, "semantic": False}

    # Heuristic checks
    heuristic_advance = False
    heuristic_reason = ""

    if node_turns >= hard_cap:
        heuristic_advance = True
        heuristic_reason = f"Hard cap reached ({node_turns}>={hard_cap})"
        logger.info(f"[ROLEARENA_AGENTS]   ✓ Heuristic: {heuristic_reason}")
    elif node_turns < min_turns:
        heuristic_reason = f"Below minimum turns ({node_turns}<{min_turns})"
        logger.info(f"[ROLEARENA_AGENTS]   ✗ Heuristic: {heuristic_reason}")
    else:
        heuristic_reason = f"Within range ({min_turns}≤{node_turns}<{hard_cap}), check semantic"
        logger.info(f"[ROLEARENA_AGENTS]   ~ Heuristic: {heuristic_reason}")

    # Semantic check (simple version: check if exit conditions mentioned in recent dialogue)
    semantic_advance = False
    semantic_reason = ""

    exit_conditions = current_node.get("exit_conditions", [])
    if exit_conditions and recent_dialogue:
        # Simple keyword matching for now (could be upgraded to LLM call)
        conditions_met = 0
        for condition in exit_conditions:
            # Extract key phrases from condition
            keywords = [word.lower() for word in condition.split() if len(word) > 3]
            if any(kw in recent_dialogue.lower() for kw in keywords):
                conditions_met += 1

        if conditions_met >= len(exit_conditions) // 2:  # At least half conditions mentioned
            semantic_advance = True
            semantic_reason = f"Exit conditions referenced ({conditions_met}/{len(exit_conditions)})"
            logger.info(f"[ROLEARENA_AGENTS]   ✓ Semantic: {semantic_reason}")
        else:
            semantic_reason = f"Exit conditions not fully met ({conditions_met}/{len(exit_conditions)})"
            logger.info(f"[ROLEARENA_AGENTS]   ✗ Semantic: {semantic_reason}")
    else:
        semantic_reason = "No exit conditions or dialogue to check"
        logger.info(f"[ROLEARENA_AGENTS]   ~ Semantic: {semantic_reason}")

    # Final decision
    should_advance = heuristic_advance or (node_turns >= min_turns and semantic_advance)

    # Check for stagnation
    quality_flags = state.get("quality_flags", {})
    if node_turns >= target_turns and quality_flags.get("plot_stall_risk", 0) > 0.6:
        should_advance = True
        heuristic_reason += " + stagnation detected"
        logger.warning(f"[ROLEARENA_AGENTS]   ⚠️  Stagnation detected, forcing advance")

    final_reason = f"{heuristic_reason}; {semantic_reason}"

    logger.info(f"[ROLEARENA_AGENTS]   Decision: {'ADVANCE' if should_advance else 'CONTINUE'}")
    logger.info(f"[ROLEARENA_AGENTS]   Reason: {final_reason}")

    return {
        "should_advance": should_advance,
        "reason": final_reason,
        "heuristic": heuristic_advance,
        "semantic": semantic_advance
    }


# ============================================================================
# Helper: Generate Bridge Narration
# ============================================================================

def generate_bridge_narration(
    state: Dict[str, Any],
    from_node: Dict[str, Any],
    to_node: Dict[str, Any]
) -> str:
    """
    Generate a short bridge narration for plot node transition.

    Args:
        state: Current state
        from_node: Node we're leaving
        to_node: Node we're entering

    Returns:
        1-3 sentence bridge narration
    """
    logger.info(f"[ROLEARENA_AGENTS] Generating bridge narration: {from_node['beat']} → {to_node['beat']}")

    # Simple template-based bridge (could be upgraded to LLM generation)
    templates = [
        f"The moment shifts. {to_node['stakes']}",
        f"Something changes between them. {to_node['goal']}",
        f"Time moves forward. {to_node['beat']} begins.",
    ]

    # Pick based on node index
    template_idx = to_node['id'] % len(templates)
    bridge = templates[template_idx]

    logger.info(f"[ROLEARENA_AGENTS]   Bridge: {bridge}")
    return bridge


# ============================================================================
# Quality Monitoring (lightweight)
# ============================================================================

def compute_quality_flags(state: Dict[str, Any], recent_dialogue: str) -> Dict[str, float]:
    """
    Compute quality monitoring flags.

    Returns:
        {"repetition_risk": 0.0-1.0, "character_drift_risk": 0.0-1.0, "plot_stall_risk": 0.0-1.0}
    """
    logger.info("[ROLEARENA_AGENTS] Computing quality flags")

    # Simple heuristics for now
    flags = {
        "repetition_risk": 0.0,
        "character_drift_risk": 0.0,
        "plot_stall_risk": 0.0
    }

    # Check for repetition (repeated words)
    if recent_dialogue:
        words = recent_dialogue.lower().split()
        if len(words) > 10:
            unique_ratio = len(set(words)) / len(words)
            flags["repetition_risk"] = 1.0 - unique_ratio

    # Check for plot stall (node_turns too high)
    plot = state.get("plot", {})
    node_turns = plot.get("node_turns", 0)
    target = plot.get("node_budget", {}).get("target", 5)
    if node_turns > target * 1.2:
        flags["plot_stall_risk"] = min(1.0, (node_turns - target) / target)

    logger.info(f"[ROLEARENA_AGENTS]   Flags: {flags}")

    return flags


# ============================================================================
# Export
# ============================================================================

__all__ = [
    "create_director_intent_parser",
    "create_env_agent",
    "create_critic_gate",
    "should_advance_node",
    "generate_bridge_narration",
    "compute_quality_flags",
]

