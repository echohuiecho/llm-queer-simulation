"""
RoleArena-style root orchestration.

This module implements the turn loop:
1. DirectorIntentParser → extract user intent
2. EnvAgent → generate turn plan (narration + speaker selection + advance detection)
3. Persona Agent → character speaks (using micro-objective from EnvAgent)
4. EnvAdvanceJudge → check if node should advance
5. CriticGate → approve/reject advancement (if candidate)
6. Advance plot (if approved) or continue current node
"""

import logging
import random
from typing import Any, Dict
from google.adk.agents import LlmAgent, SequentialAgent
from config import config
from .rolearena_agents import (
    create_director_intent_parser,
    create_env_agent,
    create_critic_gate,
    should_advance_node,
    generate_bridge_narration,
    compute_quality_flags,
)
from .personas import create_persona_agent
from ..rolearena_tools import (
    update_env_turn_plan,
    emit_narration,
    emit_character_response,
    advance_plot,
    update_quality_flags,
    increment_story_turn,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

MODEL_NAME = "gemini-2.0-flash"


# ============================================================================
# RoleArena Persona Wrapper
# ============================================================================

def create_rolearena_persona_agent(agent_id: str, profile: dict, env_turn_plan: Dict[str, Any]) -> LlmAgent:
    """
    Create a RoleArena-adapted persona agent.

    This wraps the standard persona agent with:
    - Env narration context
    - Micro-objective for this turn
    - Beat focus
    - Director constraints

    Args:
        agent_id: Agent ID (a1/a2/a3)
        profile: Character profile
        env_turn_plan: EnvAgent's turn plan for this turn

    Returns:
        LlmAgent configured for RoleArena workflow
    """
    logger.info(f"[ROLEARENA_ROOT] Creating RoleArena persona agent for {agent_id}")

    # Get base persona agent
    base_agent = create_persona_agent(agent_id, profile)

    # Augment instruction with RoleArena context
    base_instruction = base_agent.instruction

    # Extract RoleArena-specific context from turn plan
    narration = env_turn_plan.get("narration", "")
    beat_focus = env_turn_plan.get("beat_focus", "")
    micro_objectives = env_turn_plan.get("micro_objectives", {})
    my_objective = micro_objectives.get(agent_id, "Continue naturally")
    style_rules = env_turn_plan.get("style_rules", [])

    rolearena_context = f"""

## RoleArena Context (This Turn)

**Scene Narration**: {narration}

**Beat Focus**: {beat_focus}

**Your Micro-Objective**: {my_objective}

**Style Rules**:
{chr(10).join('- ' + rule for rule in style_rules)}

**IMPORTANT**: Focus on your micro-objective. Keep responses SHORT (1-5 lines of dialogue). Show don't tell.
"""

    augmented_instruction = base_instruction + rolearena_context

    # Create new agent with augmented instruction
    rolearena_agent = LlmAgent(
        name=f"{agent_id}_rolearena",
        model=MODEL_NAME,
        instruction=augmented_instruction,
        tools=base_agent.tools,
        output_key=f"{agent_id}_reply",
    )

    logger.info(f"[ROLEARENA_ROOT]   Agent {agent_id} micro-objective: {my_objective}")

    return rolearena_agent


# ============================================================================
# RoleArena Turn Orchestrator
# ============================================================================

def create_rolearena_turn_orchestrator() -> SequentialAgent:
    """
    Create the main RoleArena turn orchestrator.

    Flow:
    1. DirectorIntentParser (if user message exists)
    2. EnvAgent (always runs, generates turn plan)
    3. Selected Persona Agent (based on env_turn_plan.next_speaker)
    4. EnvAdvanceJudge (check if node should advance)
    5. CriticGate (if advance_candidate, approve/reject)
    6. AdvancePlot (if approved, advance with bridge narration)
    7. IncrementTurn

    Returns:
        SequentialAgent orchestrating the full turn
    """
    logger.info("[ROLEARENA_ROOT] Creating RoleArena turn orchestrator")

    # Note: This is a simplified version. In production, you'd want to:
    # 1. Conditionally run DirectorIntentParser only when user message exists
    # 2. Dynamically select which persona agent to run based on env_turn_plan
    # 3. Conditionally run CriticGate only when advance_candidate=true
    #
    # For now, we'll create a basic sequential flow and rely on state checks

    sub_agents = [
        # Step 1: Parse director intent
        create_director_intent_parser(),

        # Step 2: EnvAgent generates turn plan
        create_env_agent(),

        # Step 3: Persona agents (all three, will be filtered by env_turn_plan later)
        # In production, use a ParallelAgent or conditional logic to run only the selected speaker
        # For now, we'll create them dynamically in the server

        # Step 4: CriticGate (conditional on advance_candidate)
        create_critic_gate(),
    ]

    orchestrator = SequentialAgent(
        name="RoleArenaOrchestrator",
        sub_agents=sub_agents,
        description="RoleArena turn-by-turn orchestrator with discrete plot nodes and director controls"
    )

    logger.info("[ROLEARENA_ROOT] RoleArena turn orchestrator created")

    return orchestrator


# ============================================================================
# Simplified Root Agent (for testing)
# ============================================================================

def create_rolearena_root_agent() -> SequentialAgent:
    """
    Create a simplified RoleArena root agent for initial testing.

    This runs a basic turn loop with:
    - EnvAgent
    - One persona agent (a1)
    - Turn increment

    For full implementation, use create_rolearena_turn_orchestrator() with dynamic speaker selection.
    """
    logger.info("[ROLEARENA_ROOT] Creating simplified RoleArena root agent")

    # Get agent profiles
    profiles = config.get("agent_profiles", {})

    # Create a test persona agent (a1)
    test_persona = create_persona_agent("a1", profiles.get("a1", {}))

    # Create env agent
    env_agent = create_env_agent()

    # Create root
    root = SequentialAgent(
        name="RoleArenaRoot_Simple",
        sub_agents=[env_agent, test_persona],
        description="Simplified RoleArena root for testing"
    )

    logger.info("[ROLEARENA_ROOT] Simplified RoleArena root agent created")

    return root


# ============================================================================
# Export
# ============================================================================

__all__ = [
    "create_rolearena_persona_agent",
    "create_rolearena_turn_orchestrator",
    "create_rolearena_root_agent",
]

