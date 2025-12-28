# RoleArena Integration Guide

## Overview

This guide explains how to integrate the RoleArena-style narrative control system into your existing ADK-based application.

## Architecture Changes Applied

### 1. State Structure (`adk_sim/rolearena_state.py`)

**New state fields:**

```python
state = {
    "series": {"genre": "girlslove", "tone": "slow-burn", "rating": "PG-13"},
    "characters": {
        "a1": {...profile...},
        "a2": {...profile...},
        "a3": {...profile...}
    },
    "plot": {
        "nodes": [  # Discrete plot beats (9 for GL arc)
            {"id": 0, "beat": "Setup + Spark", "goal": "...", "stakes": "...", "exit_conditions": [...]},
            ...
        ],
        "node_idx": 0,           # Current plot node
        "node_turns": 0,          # Turns in current node
        "total_turns": 0,         # Total turns overall
        "turn_budget": {"min": 50, "max": 90},
        "node_budget": {"min": 3, "target": 5, "hard_cap": 7}
    },
    "director": {
        "latest_goal": "...",
        "constraints": [],
        "controls": {"pace": "slow", "spice": 1, "angst": 2, "comedy": 1}
    },
    "dialogue": [...],
    "quality_flags": {
        "repetition_risk": 0.0,
        "character_drift_risk": 0.0,
        "plot_stall_risk": 0.0
    },
    "env_turn_plan": {},        # EnvAgent output
    "advance_candidate": False,  # Should we advance node?
    "critic_verdict": {},        # CriticGate output
    "narrations": [],            # Narration log (separate from dialogue)
    "character_responses": []    # Character responses log
}
```

### 2. New Agents (`adk_sim/agents/rolearena_agents.py`)

#### DirectorIntentParser
- Parses user (director) messages into structured format
- Extracts: `director_goal`, `constraints`, `controls`, `branch_hint`
- User is treated as out-of-world director, not in-character

#### EnvAgent (Environment Agent)
- Runs **every turn**
- Generates:
  - Short narration (1-3 sentences)
  - Next speaker selection
  - Micro-objectives for all 3 characters
  - Beat focus for current node
  - Advance candidate flag
- Maintains GL tone and director controls

#### CriticGate
- Only runs when `advance_candidate=true`
- Approves or rejects plot node advancement
- Considers:
  - Turn budgets (min/target/hard_cap)
  - Director pace settings
  - Story development quality
  - Exit conditions satisfaction
- Output: `approve_advance`, `why`, `required_before_advance`, `suggested_min_extra_turns`

#### EnvAdvanceJudge (Hybrid Function)
- Combines heuristic + semantic checks
- Heuristic: node_turns vs budgets
- Semantic: exit conditions satisfied?
- Returns: `should_advance`, `reason`, `heuristic`, `semantic`

### 3. New Tools (`adk_sim/rolearena_tools.py`)

#### `emit_narration(narration, narration_type, room)`
- Emit scene narration (separate from character dialogue)
- Types: "scene", "bridge", "hint"
- Goes to narrations log + system message

#### `emit_character_response(speaker, utterance, action, thought, room)`
- Emit character dialogue/action/thought
- Goes to character_responses log + character message
- Keeps narration and dialogue in separate channels

#### `advance_plot(approve, bridge_narration, room)`
- Advance to next plot node (if approved)
- Emits bridge narration
- Resets node_turns, increments node_idx
- Emits plot_advance event

#### `increment_story_turn()`
- Increment turn counters
- Updates node_turns and total_turns

### 4. Orchestration (`adk_sim/agents/rolearena_root.py`)

#### Turn Loop Flow

```
1. DirectorIntentParser → extract user intent
   ↓
2. EnvAgent → generate turn plan
   ↓
3. Selected Persona Agent → character speaks (using micro-objective)
   ↓
4. EnvAdvanceJudge → check if node should advance
   ↓
5. IF advance_candidate:
   CriticGate → approve/reject
   ↓
   IF approved:
   Advance plot with bridge narration
   ↓
6. Increment turn counters
   ↓
7. Update quality flags
```

## Integration Steps

### Step 1: Initialize RoleArena State

```python
from adk_sim.rolearena_state import init_rolearena_story_state

# In your server startup or session creation:
state = init_rolearena_story_state(
    director_first_message=user_message,
    controls={"pace": "slow", "spice": 1, "angst": 2, "comedy": 1},
    num_nodes=9  # 9-node GL arc
)
```

### Step 2: Use RoleArena Root Agent

```python
from adk_sim.agents.rolearena_root import create_rolearena_root_agent

# Instead of create_root_agent_with_shuffled_order():
root_agent = create_rolearena_root_agent()
```

### Step 3: Process Turns Through RoleArena Orchestrator

```python
# In your turn processing (e.g., server.py):
from adk_sim.agents.rolearena_agents import (
    create_env_agent,
    create_critic_gate,
    should_advance_node,
    generate_bridge_narration
)
from adk_sim.rolearena_tools import (
    emit_narration,
    advance_plot,
    increment_story_turn
)

# 1. EnvAgent runs every turn
env_agent = create_env_agent()
turn_plan = env_agent.run(state)  # Gets TurnPlan

# 2. Selected persona speaks
next_speaker = turn_plan["next_speaker"]
persona = create_rolearena_persona_agent(next_speaker, profiles[next_speaker], turn_plan)
response = persona.run(state)

# 3. Check advancement
advance_result = should_advance_node(state, recent_dialogue)
if advance_result["should_advance"]:
    # 4. Critic approves/rejects
    critic = create_critic_gate()
    verdict = critic.run(state)

    if verdict["approve_advance"]:
        # 5. Advance plot
        bridge = generate_bridge_narration(state, current_node, next_node)
        advance_plot(True, bridge, tool_context=tool_context)

# 6. Increment turn
increment_story_turn(tool_context=tool_context)
```

### Step 4: Update Persona Agents

Persona agents now receive RoleArena context:

```python
from adk_sim.agents.rolearena_root import create_rolearena_persona_agent

# Instead of create_persona_agent():
persona = create_rolearena_persona_agent(
    agent_id="a1",
    profile=profiles["a1"],
    env_turn_plan=state["env_turn_plan"]
)
```

This augments the persona instruction with:
- Scene narration from EnvAgent
- Beat focus
- Character's micro-objective for this turn
- Style rules

## Logging and Monitoring

All RoleArena modules include comprehensive logging:

```python
import logging
logging.basicConfig(level=logging.INFO)

# You'll see logs like:
# [ROLEARENA_STATE] Initializing RoleArena story state
# [ROLEARENA_STATE] Generated 9 plot nodes
# [ROLEARENA_STATE] Starting at node 0: Setup + Spark
# [ROLEARENA_AGENTS] EnvAgent evaluating node advancement
# [ROLEARENA_AGENTS]   Node 0, turns: 5/5 (min:3, cap:7)
# [ROLEARENA_AGENTS]   ✓ Heuristic: Within range (3≤5<7), check semantic
# [ROLEARENA_AGENTS]   ✓ Semantic: Exit conditions referenced (2/2)
# [ROLEARENA_AGENTS]   Decision: ADVANCE
# [ROLEARENA_STATE] ✓ Plot advanced from node 0 to 1
# [ROLEARENA_STATE]   Previous: Setup + Spark
# [ROLEARENA_STATE]   Current:  Proximity Lock-in
```

## Testing

Run the integration example:

```bash
cd queer-sim-backend
python rolearena_integration_example.py
```

This will run through all RoleArena components and validate the integration.

## Differences from Original System

### What Changed

1. **State Structure**: Added discrete plot nodes, turn counters, director controls
2. **Turn Control**: EnvAgent now runs every turn (not just at milestones)
3. **Advancement**: Continuous detection + critic approval (not milestone-triggered)
4. **Separation**: Narration vs character dialogue are separate channels
5. **Director Mode**: User is out-of-world director (not in-character participant)

### What Stayed the Same

1. **ADK Architecture**: Still uses ADK agents, tools, and orchestration
2. **Persona Agents**: Character profiles and behaviors are preserved
3. **RAG Integration**: prepare_turn_context and retrieve_scene still work
4. **WebSocket Events**: Outbox and event broadcasting unchanged
5. **Webtoon Generation**: Legacy storyline planning loop can still be used

### Compatibility

RoleArena mode is **opt-in**. You can:

- Use RoleArena for live GL dialogue
- Use legacy mode for webtoon storyline generation
- Switch between modes based on use case

## Next Steps

1. **Run the example**: `python rolearena_integration_example.py`
2. **Check logs**: Verify all components working
3. **Integrate into server.py**: Replace root agent creation
4. **Test with frontend**: Send messages through WebSocket
5. **Monitor quality flags**: Watch for repetition/drift/stall warnings
6. **Tune budgets**: Adjust pace/node budgets based on your needs

## Advanced: Customizing Plot Nodes

To create custom plot node sequences:

```python
from adk_sim.rolearena_state import init_rolearena_story_state

custom_nodes = [
    {
        "id": 0,
        "beat": "Your Custom Beat",
        "goal": "What should happen in this beat",
        "stakes": "Why it matters emotionally",
        "exit_conditions": [
            "Specific condition 1",
            "Specific condition 2"
        ]
    },
    # ... more nodes
]

state = init_rolearena_story_state(...)
state["plot"]["nodes"] = custom_nodes
```

## Questions?

Check the code comments in:
- `adk_sim/rolearena_state.py` - State management
- `adk_sim/agents/rolearena_agents.py` - Agent implementations
- `adk_sim/rolearena_tools.py` - Tool implementations
- `rolearena_integration_example.py` - Working examples

All modules have extensive inline documentation and logging.

## Summary

✅ **RoleArena integration complete!**

The system now supports:
- ✅ Discrete plot nodes with turn-by-turn control
- ✅ Environment agent running every turn
- ✅ Critic gate for pacing control
- ✅ Director mode (out-of-world user)
- ✅ Separate narration/dialogue channels
- ✅ Quality monitoring flags
- ✅ Comprehensive logging throughout
- ✅ Full compatibility with existing ADK architecture

**Log markers to watch for:**
- `[ROLEARENA_STATE]` - State changes, node advancement
- `[ROLEARENA_AGENTS]` - Agent decisions, advancement detection
- `[ROLEARENA_TOOLS]` - Tool executions, event emissions
- `[ROLEARENA_ROOT]` - Orchestration flow

**Success indicators:**
- ✓ State initialized with plot nodes
- ✓ EnvAgent generates turn plans
- ✓ Persona agents receive micro-objectives
- ✓ Advancement detection working
- ✓ Critic gate approving/rejecting
- ✓ Plot nodes advancing with bridges
- ✓ Quality flags updating

