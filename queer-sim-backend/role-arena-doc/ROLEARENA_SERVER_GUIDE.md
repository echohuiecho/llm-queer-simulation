# RoleArena Server Integration Guide

## ✅ Integration Complete!

RoleArena has been integrated directly into your `server.py`. You can now run it with:

```bash
uvicorn server:app --reload --port 8000
```

## How to Use

### 1. Start the Server

```bash
cd queer-sim-backend
uvicorn server:app --reload --port 8000
```

The server starts in **Legacy mode** by default (existing behavior unchanged).

### 2. Toggle RoleArena Mode

**Enable RoleArena:**
```bash
curl -X POST http://localhost:8000/api/rolearena/toggle \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'
```

**Disable RoleArena (back to Legacy):**
```bash
curl -X POST http://localhost:8000/api/rolearena/toggle \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

**Note:** Toggling mode resets the session to start fresh with the appropriate state structure.

### 3. Check RoleArena Status

```bash
curl http://localhost:8000/api/rolearena/status
```

Response when enabled:
```json
{
  "enabled": true,
  "mode": "rolearena",
  "plot_state": {
    "node_idx": 0,
    "node_turns": 3,
    "total_turns": 3,
    "current_beat": "Setup + Spark",
    "total_nodes": 9,
    "director_controls": {
      "pace": "slow",
      "spice": 1,
      "angst": 2,
      "comedy": 1
    },
    "quality_flags": {
      "repetition_risk": 0.0,
      "character_drift_risk": 0.0,
      "plot_stall_risk": 0.0
    }
  }
}
```

### 4. Update Director Controls

```bash
curl -X POST http://localhost:8000/api/rolearena/controls \
  -H "Content-Type: application/json" \
  -d '{
    "controls": {
      "pace": "fast",
      "spice": 2,
      "angst": 3,
      "comedy": 0
    }
  }'
```

**Control Values:**
- `pace`: "slow" | "med" | "fast"
- `spice`: 0-3 (intimacy level)
- `angst`: 0-3 (tension level)
- `comedy`: 0-2 (humor level)

### 5. Send Messages (Through WebSocket or API)

Once RoleArena mode is enabled, all messages route through the RoleArena turn processor automatically.

Via WebSocket (from frontend):
```javascript
ws.send(JSON.stringify({
  type: "user_message",
  room: "group_chat",
  text: "Let's create a story about two women falling in love at a coffee shop"
}));
```

## Architecture Flow (RoleArena Mode)

```
User Message
    ↓
run_rolearena_turn()
    ↓
1. Extract Director Intent (user as director)
    ↓
2. EnvAgent: Generate Turn Plan
   - Narration (1-3 sentences)
   - Next speaker selection
   - Micro-objectives for all characters
   - Beat focus
   - Advance detection
    ↓
3. Selected Persona Speaks
   - Uses micro-objective from EnvAgent
   - Produces dialogue/action/thought
    ↓
4. EnvAdvanceJudge: Check if node should advance
   - Heuristic check (turn budgets)
   - Semantic check (exit conditions)
    ↓
5. IF advance_candidate:
   CriticGate: Approve/Reject
   - Based on pace, development, budgets
    ↓
6. IF approved:
   Advance Plot Node
   - Generate bridge narration
   - Increment node_idx
   - Reset node_turns
    ↓
7. Increment Turn Counters
    ↓
8. Update Quality Flags
   - Repetition risk
   - Plot stall risk
    ↓
Broadcast to WebSocket clients
```

## Logging

All RoleArena operations are logged with `[ROLEARENA]` prefix:

```
[ROLEARENA] Starting RoleArena turn
[ROLEARENA] Director message: Let's create a story...
[ROLEARENA] Current node: Setup + Spark
[ROLEARENA] Next speaker: a1
[ROLEARENA] Advance check: False - Below minimum turns (2<3)
[ROLEARENA] Turn complete
```

Watch logs:
```bash
# In your terminal running the server
tail -f <your_log_file> | grep ROLEARENA
```

## State Structure Differences

### Legacy Mode State
```python
{
    "rooms": [...],
    "history": {...},
    "agents": [...],
    "current_storyline": {},  # Webtoon storyline
    "storyline_version": 0
}
```

### RoleArena Mode State
```python
{
    "series": {"genre": "girlslove", "tone": "slow-burn", "rating": "PG-13"},
    "characters": {
        "a1": {...},
        "a2": {...},
        "a3": {...}
    },
    "plot": {
        "nodes": [  # 9 discrete plot beats
            {"id": 0, "beat": "Setup + Spark", "goal": "...", "exit_conditions": [...]},
            ...
        ],
        "node_idx": 0,
        "node_turns": 0,
        "total_turns": 0,
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
    "env_turn_plan": {},
    "narrations": []
}
```

## Current Implementation Status

### ✅ Implemented
- RoleArena state initialization
- Mode toggle API endpoint
- Status and control APIs
- Turn routing (RoleArena vs Legacy)
- Turn-level tracking (node_turns, total_turns)
- Advance detection logic
- Plot node advancement
- Quality flag monitoring
- Comprehensive logging

### 🚧 Simplified (For Quick Integration)
- **EnvAgent**: Using simple turn plan instead of full LLM (upgrade by calling `create_env_agent()`)
- **Persona Agents**: Using simple response instead of full RoleArena persona (upgrade by calling `create_rolearena_persona_agent()`)
- **CriticGate**: Using heuristic approval instead of full LLM (upgrade by calling `create_critic_gate()`)
- **DirectorIntentParser**: Skipping for now (can add later)

### 🎯 Ready to Upgrade

When you're ready for full LLM-powered RoleArena, replace the simplified sections in `run_rolearena_turn()`:

**Full EnvAgent:**
```python
# Instead of simple turn_plan dict:
env_agent = create_env_agent()
turn_plan_result = await env_agent.run(state)
turn_plan = turn_plan_result.get("env_turn_plan", {})
```

**Full Persona:**
```python
# Instead of simple response:
persona = create_rolearena_persona_agent(
    next_speaker,
    profiles[next_speaker],
    turn_plan
)
persona_result = await persona.run(state)
```

**Full Critic:**
```python
# Instead of simple min_turns check:
critic = create_critic_gate()
verdict = await critic.run(state)
if verdict.get("approve_advance"):
    # Advance
```

## Testing

### 1. Quick Test (Command Line)

```bash
# Terminal 1: Start server
cd queer-sim-backend
uvicorn server:app --reload --port 8000

# Terminal 2: Enable RoleArena
curl -X POST http://localhost:8000/api/rolearena/toggle \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'

# Check status
curl http://localhost:8000/api/rolearena/status

# Update controls
curl -X POST http://localhost:8000/api/rolearena/controls \
  -H "Content-Type: application/json" \
  -d '{"controls": {"pace": "fast", "spice": 2}}'
```

### 2. Test with Frontend

1. Start server: `uvicorn server:app --reload --port 8000`
2. Start frontend: `cd queer-sim-frontend && npm run dev`
3. Open browser: `http://localhost:3000`
4. Enable RoleArena via API (or add UI button)
5. Send messages through chat
6. Watch server logs for `[ROLEARENA]` markers

### 3. Test Plot Progression

Send multiple messages to trigger plot advancement:

```bash
# Message 1-2: Stay in node 0 (below min_turns)
# Message 3-5: Advance to node 1 (if exit conditions met)
# Watch logs for advancement messages
```

## Monitoring

### Key Metrics to Watch

1. **Node Progression:**
   ```bash
   curl http://localhost:8000/api/rolearena/status | jq '.plot_state.node_idx'
   ```

2. **Turn Counts:**
   ```bash
   curl http://localhost:8000/api/rolearena/status | jq '.plot_state | {node_turns, total_turns}'
   ```

3. **Quality Flags:**
   ```bash
   curl http://localhost:8000/api/rolearena/status | jq '.plot_state.quality_flags'
   ```

### Warning Signs

- **High repetition_risk (>0.7):** Characters repeating themselves
- **High plot_stall_risk (>0.6):** Stuck in same node too long
- **Node never advancing:** Check min_turns threshold

## Troubleshooting

### Issue: RoleArena mode not working

**Check:**
```bash
curl http://localhost:8000/api/rolearena/status
```

If `enabled: false`, toggle it on:
```bash
curl -X POST http://localhost:8000/api/rolearena/toggle \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'
```

### Issue: Plot not advancing

**Check node_turns:**
```bash
curl http://localhost:8000/api/rolearena/status | jq '.plot_state.node_turns'
```

If below `min` (default 3), send more messages.

### Issue: No logs visible

**Check server terminal:**
```bash
# Logs should show:
[SERVER] RoleArena mode ENABLED
[ROLEARENA] Starting RoleArena turn
[ROLEARENA] Current node: Setup + Spark
...
```

### Issue: Want to switch back to Legacy mode

```bash
curl -X POST http://localhost:8000/api/rolearena/toggle \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

## Next Steps

1. **Test basic flow:** Enable mode, send messages, check logs
2. **Monitor progression:** Watch plot nodes advance
3. **Tune controls:** Adjust pace/spice/angst/comedy
4. **Upgrade to full LLM:** Replace simplified sections with full agents
5. **Add UI:** Create frontend controls for RoleArena mode

## Summary

✅ **RoleArena is now integrated and ready to use!**

- **Toggle on/off** via API without code changes
- **Automatic turn routing** based on mode
- **Full state management** with discrete plot nodes
- **Quality monitoring** with real-time flags
- **Director controls** for pace/spice/angst/comedy
- **Backward compatible** with existing Legacy mode

**Start the server and try it out:**
```bash
uvicorn server:app --reload --port 8000
```

Then toggle RoleArena mode on and start chatting! 🚀

