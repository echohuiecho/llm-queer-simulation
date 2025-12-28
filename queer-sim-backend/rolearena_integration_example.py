"""
RoleArena Integration Example

This script demonstrates how to use the RoleArena system with your existing ADK setup.

To enable RoleArena mode in your server:
1. Initialize state with init_rolearena_story_state() instead of get_initial_state()
2. Use create_rolearena_root_agent() instead of create_root_agent_with_shuffled_order()
3. Process turns through the RoleArena orchestrator

This example shows the complete flow.
"""

import logging
from adk_sim.rolearena_state import init_rolearena_story_state, get_current_node, advance_plot_node
from adk_sim.agents.rolearena_agents import (
    create_director_intent_parser,
    create_env_agent,
    create_critic_gate,
    should_advance_node,
    generate_bridge_narration,
    compute_quality_flags,
)
from adk_sim.agents.rolearena_root import create_rolearena_root_agent
from adk_sim.rolearena_tools import (
    emit_narration,
    emit_character_response,
    advance_plot,
    increment_story_turn,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def example_rolearena_initialization():
    """Example 1: Initialize RoleArena state"""
    logger.info("=" * 80)
    logger.info("EXAMPLE 1: Initialize RoleArena State")
    logger.info("=" * 80)

    director_message = "Create a slow-burn GL story about two masc lesbians meeting in a coffee shop"

    state = init_rolearena_story_state(
        director_first_message=director_message,
        controls={"pace": "slow", "spice": 1, "angst": 2, "comedy": 1},
        num_nodes=9
    )

    logger.info(f"\n✓ State initialized with {len(state['plot']['nodes'])} plot nodes")
    logger.info(f"✓ Starting at node 0: {state['plot']['nodes'][0]['beat']}")
    logger.info(f"✓ Director controls: {state['director']['controls']}")
    logger.info(f"✓ Turn budgets: {state['plot']['turn_budget']}")
    logger.info(f"✓ Node budgets: {state['plot']['node_budget']}")

    return state


def example_env_agent_turn_plan(state):
    """Example 2: EnvAgent generates a turn plan"""
    logger.info("\n" + "=" * 80)
    logger.info("EXAMPLE 2: EnvAgent Generates Turn Plan")
    logger.info("=" * 80)

    current_node = get_current_node(state)
    logger.info(f"\nCurrent node: {current_node['beat']}")
    logger.info(f"Goal: {current_node['goal']}")
    logger.info(f"Stakes: {current_node['stakes']}")

    # Simulate EnvAgent output
    turn_plan = {
        "narration": "The coffee shop hums with quiet conversation. A1 notices A2 ordering, their presence somehow magnetic.",
        "beat_focus": "Establish the initial spark between A1 and A2",
        "speaker_order": ["a1", "a2", "a3"],
        "next_speaker": "a1",
        "micro_objectives": {
            "a1": "Notice A2 in a way that feels undeniable, but cover it with composure",
            "a2": "Be present and authentic, unknowingly catching A1's attention",
            "a3": "Provide social context, notice something's shifting"
        },
        "style_rules": [
            "Show don't tell",
            "Use subtext and micro-actions",
            "Keep GL slow-burn tone",
            "No repetition from previous turns"
        ],
        "advance_candidate": False,
        "advance_reason": "Node just started, need more development",
        "node_idx": 0,
        "node_turns": 1
    }

    state["env_turn_plan"] = turn_plan
    logger.info(f"\n✓ Narration: {turn_plan['narration']}")
    logger.info(f"✓ Next speaker: {turn_plan['next_speaker']}")
    logger.info(f"✓ A1 objective: {turn_plan['micro_objectives']['a1']}")

    return turn_plan


def example_advance_detection(state):
    """Example 3: EnvAdvanceJudge detects if node should advance"""
    logger.info("\n" + "=" * 80)
    logger.info("EXAMPLE 3: EnvAdvanceJudge Detection")
    logger.info("=" * 80)

    # Simulate some dialogue
    recent_dialogue = """
    A1: *glances up from her laptop* Nice choice. The oat milk latte is perfect here.
    A2: *smiles warmly* Thanks. I'm new to the neighborhood, still finding my spots.
    A3: *from nearby table* You two should sit together! A1 knows everything about this place.
    A1: *slight flush, tries to look casual* I mean... if you want company.
    A2: *holds her gaze for a moment* I'd like that.
    """

    # After 5 turns in node 0
    state["plot"]["node_turns"] = 5

    result = should_advance_node(state, recent_dialogue)

    logger.info(f"\n✓ Should advance: {result['should_advance']}")
    logger.info(f"✓ Reason: {result['reason']}")
    logger.info(f"✓ Heuristic check: {result['heuristic']}")
    logger.info(f"✓ Semantic check: {result['semantic']}")

    return result


def example_critic_approval(state):
    """Example 4: CriticGate approves/rejects advancement"""
    logger.info("\n" + "=" * 80)
    logger.info("EXAMPLE 4: CriticGate Approval")
    logger.info("=" * 80)

    # Simulate critic verdict
    verdict = {
        "approve_advance": True,
        "why": "Exit conditions met: A1 noticed A2 undeniably, A2 showed she sees through A1's composure. Node turns (5) at target (5).",
        "required_before_advance": [],
        "suggested_min_extra_turns": 0
    }

    state["critic_verdict"] = verdict
    logger.info(f"\n✓ Approved: {verdict['approve_advance']}")
    logger.info(f"✓ Reason: {verdict['why']}")

    return verdict


def example_plot_advancement(state):
    """Example 5: Advance plot node with bridge narration"""
    logger.info("\n" + "=" * 80)
    logger.info("EXAMPLE 5: Plot Node Advancement")
    logger.info("=" * 80)

    current_node = get_current_node(state)
    nodes = state["plot"]["nodes"]
    next_node = nodes[state["plot"]["node_idx"] + 1]

    logger.info(f"\nCurrent: {current_node['beat']}")
    logger.info(f"Next: {next_node['beat']}")

    # Generate bridge narration
    bridge = generate_bridge_narration(state, current_node, next_node)
    logger.info(f"\n✓ Bridge narration: {bridge}")

    # Advance
    advance_plot_node(state, bridge)

    new_current = get_current_node(state)
    logger.info(f"✓ Advanced to node {state['plot']['node_idx']}: {new_current['beat']}")
    logger.info(f"✓ Node turns reset to: {state['plot']['node_turns']}")

    return bridge


def example_quality_monitoring(state):
    """Example 6: Quality flag monitoring"""
    logger.info("\n" + "=" * 80)
    logger.info("EXAMPLE 6: Quality Monitoring")
    logger.info("=" * 80)

    # Simulate dialogue with some repetition
    recent_dialogue = "A1 smiles. A2 smiles back. They smile at each other. Smiling continues."

    flags = compute_quality_flags(state, recent_dialogue)

    logger.info(f"\n✓ Repetition risk: {flags['repetition_risk']:.2f}")
    logger.info(f"✓ Character drift risk: {flags['character_drift_risk']:.2f}")
    logger.info(f"✓ Plot stall risk: {flags['plot_stall_risk']:.2f}")

    for key, value in flags.items():
        if value > 0.7:
            logger.warning(f"⚠️  HIGH RISK: {key} = {value:.2f}")

    return flags


def run_all_examples():
    """Run all examples in sequence"""
    logger.info("\n" + "=" * 80)
    logger.info("ROLEARENA INTEGRATION EXAMPLES")
    logger.info("=" * 80)

    # Example 1: Initialize
    state = example_rolearena_initialization()

    # Example 2: EnvAgent turn plan
    turn_plan = example_env_agent_turn_plan(state)

    # Example 3: Advance detection
    advance_result = example_advance_detection(state)

    # Example 4: Critic approval
    verdict = example_critic_approval(state)

    # Example 5: Plot advancement
    if verdict["approve_advance"]:
        bridge = example_plot_advancement(state)

    # Example 6: Quality monitoring
    flags = example_quality_monitoring(state)

    logger.info("\n" + "=" * 80)
    logger.info("ALL EXAMPLES COMPLETED SUCCESSFULLY")
    logger.info("=" * 80)

    # Summary
    logger.info("\n### ROLEARENA STATE SUMMARY ###")
    logger.info(f"Current node: {state['plot']['node_idx']} - {get_current_node(state)['beat']}")
    logger.info(f"Total turns: {state['plot']['total_turns']}")
    logger.info(f"Node turns: {state['plot']['node_turns']}")
    logger.info(f"Quality flags: {state.get('quality_flags', {})}")
    logger.info(f"Narrations emitted: {len(state.get('narrations', []))}")
    logger.info(f"Character responses: {len(state.get('character_responses', []))}")

    logger.info("\n✓ RoleArena system working correctly!")


if __name__ == "__main__":
    run_all_examples()

