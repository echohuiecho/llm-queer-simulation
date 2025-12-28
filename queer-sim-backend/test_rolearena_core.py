"""
Test RoleArena Core Logic (No ADK Dependencies)

This tests the RoleArena state and logic without requiring ADK imports.
"""

import logging
import sys
import json

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_rolearena_state():
    """Test RoleArena state initialization"""
    logger.info("=" * 80)
    logger.info("TEST 1: RoleArena State Initialization")
    logger.info("=" * 80)

    from adk_sim.rolearena_state import init_rolearena_story_state, get_current_node

    state = init_rolearena_story_state(
        director_first_message="Create a slow-burn GL story",
        controls={"pace": "slow", "spice": 1, "angst": 2, "comedy": 1},
        num_nodes=9
    )

    assert "plot" in state
    assert "nodes" in state["plot"]
    assert len(state["plot"]["nodes"]) == 9
    assert state["plot"]["node_idx"] == 0
    assert state["plot"]["node_turns"] == 0

    current = get_current_node(state)
    assert current is not None
    assert current["beat"] == "Setup + Spark"

    logger.info("✓ State initialized correctly")
    logger.info(f"✓ 9 plot nodes created")
    logger.info(f"✓ Current node: {current['beat']}")
    logger.info(f"✓ Director controls: {state['director']['controls']}")

    return state


def test_plot_advancement():
    """Test plot node advancement"""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 2: Plot Node Advancement")
    logger.info("=" * 80)

    from adk_sim.rolearena_state import (
        init_rolearena_story_state,
        advance_plot_node,
        get_current_node,
        increment_turn
    )

    state = init_rolearena_story_state(
        director_first_message="Test",
        controls={"pace": "slow", "spice": 1, "angst": 2, "comedy": 1}
    )

    # Initial state
    assert state["plot"]["node_idx"] == 0
    node_0 = get_current_node(state)
    logger.info(f"Starting node: {node_0['beat']}")

    # Advance to node 1
    advance_plot_node(state, "Bridge narration: the story shifts...")
    assert state["plot"]["node_idx"] == 1
    assert state["plot"]["node_turns"] == 0  # Reset on advance

    node_1 = get_current_node(state)
    logger.info(f"✓ Advanced to node: {node_1['beat']}")

    # Test turn increment
    increment_turn(state)
    assert state["plot"]["node_turns"] == 1
    assert state["plot"]["total_turns"] == 1
    logger.info(f"✓ Turn incremented: node_turns={state['plot']['node_turns']}")

    return state


def test_advance_detection():
    """Test EnvAdvanceJudge logic"""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 3: Advance Detection Logic")
    logger.info("=" * 80)

    from adk_sim.rolearena_state import init_rolearena_story_state
    from adk_sim.agents.rolearena_agents import should_advance_node

    state = init_rolearena_story_state(
        director_first_message="Test",
        controls={"pace": "slow", "spice": 1, "angst": 2, "comedy": 1}
    )

    # Test 1: Too few turns
    state["plot"]["node_turns"] = 2  # Below min (3)
    dialogue = "A1: Hello. A2: Hi."
    result = should_advance_node(state, dialogue)
    assert result["should_advance"] == False
    logger.info(f"✓ Test 1 (too few turns): {result['should_advance']} - {result['reason']}")

    # Test 2: At target with conditions met
    state["plot"]["node_turns"] = 5  # At target
    dialogue = "A1 notices A2 in an undeniable way. A2 shows she sees through A1."
    result = should_advance_node(state, dialogue)
    logger.info(f"✓ Test 2 (at target, conditions met): {result['should_advance']} - {result['reason']}")

    # Test 3: Hard cap reached
    state["plot"]["node_turns"] = 7  # At hard cap
    dialogue = "Just talking"
    result = should_advance_node(state, dialogue)
    assert result["should_advance"] == True  # Hard cap forces advance
    logger.info(f"✓ Test 3 (hard cap): {result['should_advance']} - {result['reason']}")

    return state


def test_quality_monitoring():
    """Test quality flag computation"""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 4: Quality Monitoring")
    logger.info("=" * 80)

    from adk_sim.rolearena_state import init_rolearena_story_state
    from adk_sim.agents.rolearena_agents import compute_quality_flags

    state = init_rolearena_story_state(
        director_first_message="Test",
        controls={"pace": "slow", "spice": 1, "angst": 2, "comedy": 1}
    )

    # Test 1: Repetitive dialogue
    repetitive = "smile smile smile smile smile smile smile smile"
    flags = compute_quality_flags(state, repetitive)
    assert flags["repetition_risk"] > 0.5
    logger.info(f"✓ Test 1 (repetitive): repetition_risk={flags['repetition_risk']:.2f}")

    # Test 2: Stalling (too many turns)
    state["plot"]["node_turns"] = 10  # Way over target
    flags = compute_quality_flags(state, "normal dialogue")
    assert flags["plot_stall_risk"] > 0.5
    logger.info(f"✓ Test 2 (stalling): plot_stall_risk={flags['plot_stall_risk']:.2f}")

    return flags


def test_state_helpers():
    """Test state helper functions"""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 5: State Helper Functions")
    logger.info("=" * 80)

    from adk_sim.rolearena_state import (
        init_rolearena_story_state,
        get_current_node,
        get_next_node,
        update_director_intent,
        update_quality_flags
    )

    state = init_rolearena_story_state(
        director_first_message="Test",
        controls={"pace": "slow", "spice": 1, "angst": 2, "comedy": 1}
    )

    # Test get_current_node
    current = get_current_node(state)
    assert current["id"] == 0
    logger.info(f"✓ get_current_node: {current['beat']}")

    # Test get_next_node
    next_node = get_next_node(state)
    assert next_node["id"] == 1
    logger.info(f"✓ get_next_node: {next_node['beat']}")

    # Test update_director_intent
    update_director_intent(state, "New goal", ["no cheating"], {"pace": "fast", "spice": 2, "angst": 3, "comedy": 0})
    assert state["director"]["latest_goal"] == "New goal"
    assert "no cheating" in state["director"]["constraints"]
    assert state["director"]["controls"]["pace"] == "fast"
    logger.info(f"✓ update_director_intent: goal='{state['director']['latest_goal']}'")

    # Test update_quality_flags
    update_quality_flags(state, {"repetition_risk": 0.8, "plot_stall_risk": 0.3})
    assert state["quality_flags"]["repetition_risk"] == 0.8
    logger.info(f"✓ update_quality_flags: {state['quality_flags']}")

    return state


def run_all_tests():
    """Run all tests"""
    logger.info("\n" + "=" * 80)
    logger.info("ROLEARENA CORE LOGIC TESTS")
    logger.info("=" * 80)

    try:
        # Test 1: State initialization
        state1 = test_rolearena_state()

        # Test 2: Plot advancement
        state2 = test_plot_advancement()

        # Test 3: Advance detection
        state3 = test_advance_detection()

        # Test 4: Quality monitoring
        flags = test_quality_monitoring()

        # Test 5: State helpers
        state5 = test_state_helpers()

        logger.info("\n" + "=" * 80)
        logger.info("✅ ALL TESTS PASSED")
        logger.info("=" * 80)

        logger.info("\n### SUMMARY ###")
        logger.info("✓ RoleArena state initialization working")
        logger.info("✓ Plot node advancement working")
        logger.info("✓ Turn tracking working")
        logger.info("✓ Advance detection logic working")
        logger.info("✓ Quality monitoring working")
        logger.info("✓ State helper functions working")

        logger.info("\n✅ RoleArena core system validated successfully!")

        return True

    except Exception as e:
        logger.error(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)

