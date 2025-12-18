"""
Run `uvicorn server:app --reload --port 8000` to start the server.
"""

import asyncio, json, time, random, os
from typing import List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware

from llm import OllamaClient
from world import World
from agents import Agent, AgentProfile
from memory import MemoryStore
from rag_index import RAGIndex
from config import config

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CONNS: List[WebSocket] = []

llm = OllamaClient(
    config.get("ollama_base"),
    config.get("chat_model"),
    config.get("embed_model")
)

world = World(
    rooms={"group_chat": [], "cafe": [], "apartment": []},
    room_desc=config.get("room_desc"),
)

# Generalized RAG index
rag = RAGIndex(llm.embed)

async def broadcast(event):
    dead = []
    for ws in CONNS:
        try:
            await ws.send_text(json.dumps(event))
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in CONNS:
            CONNS.remove(ws)

world.broadcast = broadcast

def seed_agents_and_scene():
    profiles = config.get("agent_profiles")
    agents = {}
    for aid, p in profiles.items():
        agents[aid] = Agent(
            AgentProfile(aid, p["name"], p["persona"]),
            MemoryStore(llm.embed),
            room="group_chat"
        )

    # Initialize room entry times
    for agent in agents.values():
        agent.room_entered_ts = time.time()

    world.agents = agents

async def seed_initial_chat():
    """Seed the initial chat log into group_chat"""
    initial_messages = config.get("initial_messages")

    for msg in initial_messages:
        sender = msg["sender"]
        text = msg["text"]
        await world.post_message("group_chat", sender, text)
        await asyncio.sleep(0.1)  # Small delay between messages

seed_agents_and_scene()

async def run_dm_reaction(agent_name: str, trigger_msg):
    """Handle agent response to a DM from the user."""
    agent = next((a for a in world.agents.values() if a.profile.name == agent_name), None)
    if not agent:
        return

    # Get recent DM history
    key_parts = sorted(["You", agent_name])
    dm_key = f"{key_parts[0]}:{key_parts[1]}"
    recent_dms = world.dms.get(dm_key, [])[-20:]

    # Get recent room context for the agent's current room
    room = agent.room
    recent_room = world.recent(room, n=10)
    desc = world.room_desc.get(room, "")

    # Search show subtitles
    query = f'You: {trigger_msg["text"]}\n' + "\n".join([m.get("text", "") for m in recent_dms[-5:]])
    hits = await rag.search(query, k=3)
    show_snips = RAGIndex.render_for_prompt(hits)

    # Create a DM-specific decision context
    # The agent should respond in a more personal, direct way
    try:
        action = await agent.decide_dm(llm, recent_dms, trigger_msg, recent_room, desc, show_snips)
        await dispatch(agent.profile.agent_id, action)
    except Exception as e:
        print(f"Agent {agent_name} DM decision failed: {e}")

async def run_reactions(trigger_msg):
    room = trigger_msg["room"]
    recent = world.recent(room, n=20)
    desc = world.room_desc.get(room, "")
    available_rooms = list(world.rooms.keys())

    # Search show subtitles for relevant lines
    query = f'{trigger_msg["from"]}: {trigger_msg["text"]}\n' + "\n".join([m["text"] for m in recent[-8:]])
    hits = await rag.search(query, k=4)
    show_snips = RAGIndex.render_for_prompt(hits)

    tasks = []
    agent_list = []
    for a in world.agents.values():
        if a.room == room and a.profile.name != trigger_msg["from"]:
            tasks.append(a.decide(llm, room, desc, recent, trigger_msg, available_rooms, show_snips))
            agent_list.append(a)

    if not tasks:
        return  # No agents to react

    # Use gather with return_exceptions to handle individual agent failures
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Dispatch actions in a stable order based on agent IDs to reduce chaos
    for aid in sorted(world.agents.keys()):
        for i, a in enumerate(agent_list):
            if a.profile.agent_id == aid:
                if i < len(results):
                    result = results[i]
                    if isinstance(result, Exception):
                        print(f"Agent {a.profile.name} decision failed: {result}")
                        # Skip this agent's action
                        continue
                    action = result
                    try:
                        await dispatch(a.profile.agent_id, action)
                    except Exception as e:
                        print(f"Agent {a.profile.name} dispatch failed: {e}")
                    # Small delay between agent actions
                    await asyncio.sleep(0.5)

async def dispatch(agent_id: str, fn: dict):
    name = fn.get("name")
    args = fn.get("arguments") or {}
    a = world.agents[agent_id]

    if name == "send_message":
        text = (args.get("text") or "").strip()
        if text:
            await world.post_message(a.room, a.profile.name, text)

    elif name == "send_dm":
        to = args.get("to", "You")
        text = (args.get("text") or "").strip()
        if text:
            await world.post_dm(a.profile.name, to, text)

    elif name == "move_room":
        room = args.get("room")
        if room in world.rooms:
            await world.move_agent(agent_id, room)

    elif name == "wait":
        return

# ---------- Proactive loop ----------

async def proactive_loop():
    """Every 20-60 seconds, pick one agent to consider doing something."""
    while True:
        # Random interval between 20-60 seconds
        await asyncio.sleep(random.uniform(20, 60))

        # Pick a random agent
        agents_list = list(world.agents.values())
        if not agents_list:
            continue

        agent = random.choice(agents_list)
        room = agent.room
        recent = world.recent(room, n=20)
        desc = world.room_desc.get(room, "")
        available_rooms = list(world.rooms.keys())

        # Search show subtitles for proactive moments (use recent chat context)
        query = "\n".join([m["text"] for m in recent[-8:]]) if recent else "show discussion"
        hits = await rag.search(query, k=4)
        show_snips = RAGIndex.render_for_prompt(hits)

        # Trigger with "nothing happened, what do you do?"
        trigger = {
            "type": "proactive",
            "from": "system",
            "text": "nothing happened, what do you do?",
            "room": room,
            "ts": time.time()
        }

        try:
            # 50% chance to just move slightly within the room if not deciding a major action
            if random.random() < 0.5:
                agent.pos = {"x": random.uniform(0.1, 0.9), "y": random.uniform(0.1, 0.9)}
                await broadcast({
                    "type": "agent_state",
                    "id": agent.profile.agent_id,
                    "name": agent.profile.name,
                    "room": agent.room,
                    "pos": agent.pos,
                    "ts": time.time()
                })

            action = await agent.decide(llm, room, desc, recent, trigger, available_rooms, show_snips)
            await dispatch(agent.profile.agent_id, action)
        except Exception as e:
            print(f"Proactive loop error for {agent.profile.name}: {e}")
            # Continue the loop even if one agent fails

# ---------- WebSocket ----------

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    CONNS.append(ws)
    await ws.send_text(json.dumps({"type":"state", **world.snapshot()}))

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)

            if msg["type"] == "user_message":
                room = msg["room"]
                text = msg["text"]
                trigger = await world.post_message(room, "You", text)
                try:
                    await run_reactions(trigger)
                except Exception as e:
                    print(f"Error running reactions: {e}")
                    # Send error message to client
                    await ws.send_text(json.dumps({
                        "type": "error",
                        "message": f"Agent response error: {str(e)}"
                    }))

            elif msg["type"] == "user_dm":
                agent_name = msg["agent"]
                text = msg["text"]
                trigger = await world.post_dm("You", agent_name, text)
                # Trigger agent response to DM
                try:
                    await run_dm_reaction(agent_name, trigger)
                except Exception as e:
                    print(f"Error running DM reaction: {e}")
                    await ws.send_text(json.dumps({
                        "type": "error",
                        "message": f"Agent DM response error: {str(e)}"
                    }))

            elif msg["type"] == "seed_scene":
                # Optional: let UI request the initial chat seed
                await seed_initial_chat()

    except WebSocketDisconnect:
        if ws in CONNS:
            CONNS.remove(ws)

# ---------- API Endpoints ----------

@app.get("/api/settings")
async def get_settings():
    return config.settings

@app.post("/api/settings")
async def update_settings(new_settings: dict):
    for k, v in new_settings.items():
        config.set(k, v)
    return {"status": "ok"}

@app.get("/api/rag/directories")
async def list_rag_dirs():
    rag_root = "data/rag"
    if not os.path.exists(rag_root):
        os.makedirs(rag_root, exist_ok=True)
        # Create a default directory with a sample file if empty
        default_dir = os.path.join(rag_root, "default")
        os.makedirs(default_dir, exist_ok=True)
        with open(os.path.join(default_dir, "welcome.txt"), "w") as f:
            f.write("Welcome to the queer simulation. This is a default RAG file.")

    dirs = [d for d in os.listdir(rag_root) if os.path.isdir(os.path.join(rag_root, d))]
    return {"directories": dirs, "current": config.get("rag_directory")}

@app.post("/api/rag/directories")
async def create_rag_dir(data: dict):
    name = data.get("name")
    if not name:
        return {"error": "name required"}, 400

    path = os.path.join("data/rag", name)
    os.makedirs(path, exist_ok=True)
    return {"status": "ok", "path": path}

from fastapi import UploadFile, File

@app.post("/api/rag/upload")
async def upload_rag_file(dir_name: str = Query(...), file: UploadFile = File(...)):
    target_dir = os.path.join("data/rag", dir_name)
    if not os.path.exists(target_dir):
        return {"error": "directory not found"}, 404

    file_path = os.path.join(target_dir, file.filename)
    with open(file_path, "wb") as f:
        f.write(await file.read())

    # Trigger rebuild of this directory
    await rag.load_directory(target_dir, force_rebuild=True)

    return {"status": "ok", "filename": file.filename}

@app.post("/api/rag/select")
async def select_rag_dir(data: dict):
    name = data.get("name")
    if not name:
        return {"error": "name required"}, 400

    target_dir = os.path.join("data/rag", name)
    if not os.path.exists(target_dir):
        return {"error": "directory not found"}, 404

    config.set("rag_directory", name)
    await rag.load_directory(target_dir)
    return {"status": "ok", "current": name}

# ---------- Startup ----------

@app.on_event("startup")
async def startup_event():
    """Start the proactive loop and seed initial chat when the server starts."""
    # Build RAG index from selected directory
    rag_dir_name = config.get("rag_directory", "default")
    rag_path = os.path.join("data/rag", rag_dir_name)

    # Ensure default dir exists if it's the one we want
    if rag_dir_name == "default" and not os.path.exists(rag_path):
        os.makedirs(rag_path, exist_ok=True)
        # Check if we have legacy SRTs to move or copy?
        # For now let's just create a placeholder or let user upload.
        with open(os.path.join(rag_path, "info.txt"), "w") as f:
            f.write("Default RAG directory.")

    print(f"Building RAG index from {rag_path}...")
    await rag.load_directory(rag_path)

    asyncio.create_task(proactive_loop())
    # Seed initial chat after a short delay to let connections establish
    await asyncio.sleep(1)
    await seed_initial_chat()
