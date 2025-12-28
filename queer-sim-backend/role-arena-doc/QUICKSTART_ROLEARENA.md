# RoleArena Quick Start (2 Minutes)

## ✅ Integration Complete - Ready to Use!

Your server now has RoleArena built-in. Here's how to use it:

## 1️⃣ Start Server (1 command)

```bash
cd queer-sim-backend
uvicorn server:app --reload --port 8000
```

## 2️⃣ Enable RoleArena (1 command)

```bash
curl -X POST http://localhost:8000/api/rolearena/toggle \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'
```

**Response:**
```json
{
  "status": "ok",
  "enabled": true,
  "mode": "rolearena",
  "message": "Switched to RoleArena mode. Session reset."
}
```

## 3️⃣ Verify It's Working (1 command)

```bash
curl http://localhost:8000/api/rolearena/status
```

**Response:**
```json
{
  "enabled": true,
  "mode": "rolearena",
  "plot_state": {
    "node_idx": 0,
    "current_beat": "Setup + Spark",
    "total_nodes": 9,
    "node_turns": 0,
    "total_turns": 0,
    "director_controls": {
      "pace": "slow",
      "spice": 1,
      "angst": 2,
      "comedy": 1
    }
  }
}
```

✅ **That's it! RoleArena is now active.**

## What Happens Now?

When you send messages through your frontend:

1. **User message** → interpreted as director intent
2. **EnvAgent** → generates turn plan (narration, objectives, advancement check)
3. **Persona speaks** → using micro-objective from EnvAgent
4. **Advancement check** → should plot node advance?
5. **Critic approval** → if advancing, check if appropriate
6. **Plot advances** → move to next beat if approved

All automatically logged with `[ROLEARENA]` markers.

## Watch It Work

### Server Logs

In your server terminal, watch for:

```
[SERVER] RoleArena mode ENABLED
[ROLEARENA] Starting RoleArena turn
[ROLEARENA] Director message: Let's create a story...
[ROLEARENA] Current node: Setup + Spark
[ROLEARENA] Next speaker: a1
[ROLEARENA] a1: [Objective: Show emotion through action] ...
[ROLEARENA] Advance check: False - Below minimum turns (2<3)
[ROLEARENA] Turn complete
```

### Monitor Status

```bash
# Watch status update in real-time
watch -n 2 'curl -s http://localhost:8000/api/rolearena/status | python -m json.tool'
```

## Control The Story

### Update Director Controls

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

**Controls:**
- `pace`: "slow" (50-90 turns) | "med" (40-75) | "fast" (28-55)
- `spice`: 0 (none) → 3 (intimate)
- `angst`: 0 (none) → 3 (high tension)
- `comedy`: 0 (none) → 2 (humorous)

## Switch Back to Legacy

```bash
curl -X POST http://localhost:8000/api/rolearena/toggle \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

Your original system is untouched and works as before.

## Plot Progression (9 Nodes)

Watch the story progress through these beats:

0. **Setup + Spark** ← Starting here
1. **Proximity Lock-in**
2. **Misread / Misunderstanding**
3. **Almost-Date Scenario**
4. **Small Vulnerability Reveal**
5. **External Pressure Event**
6. **Choice Point**
7. **Near-Confession / Confession**
8. **Aftermath Calibration + Hook**

Check current node:
```bash
curl -s http://localhost:8000/api/rolearena/status | grep current_beat
```

## Automated Tests

```bash
python test_rolearena_server.py
```

Should show:
```
✓ PASS: Initial Status
✓ PASS: Enable RoleArena
✓ PASS: Check Enabled Status
✓ PASS: Update Controls
✓ PASS: Disable RoleArena

5/5 tests passed

✅ ALL TESTS PASSED!
```

## That's All!

**Your server is now RoleArena-enabled.**

- ✅ No code changes needed to use it
- ✅ Toggle on/off via API
- ✅ All existing features work
- ✅ Backward compatible

**Send messages through your frontend and watch the plot unfold!**

---

## Need More Info?

- **Full usage guide:** `ROLEARENA_SERVER_GUIDE.md`
- **Technical details:** `ROLEARENA_INTEGRATION_GUIDE.md`
- **Implementation report:** `ROLEARENA_IMPLEMENTATION_SUMMARY.md`
- **Complete summary:** `INTEGRATION_COMPLETE.md`

## Troubleshooting

**Server not starting?**
```bash
pip install -r requirements.txt
```

**RoleArena not enabled?**
```bash
curl -X POST http://localhost:8000/api/rolearena/toggle \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'
```

**Want to see what's happening?**
```bash
# Watch status
watch -n 2 'curl -s http://localhost:8000/api/rolearena/status | python -m json.tool'

# Check logs for [ROLEARENA] markers
```

---

**Start now:**
```bash
uvicorn server:app --reload --port 8000
```

Then enable RoleArena and chat! 🚀

