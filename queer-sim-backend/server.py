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
from youtube_ingest import YouTubeIngestManager

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

# YouTube Ingest Manager
youtube_ingest = YouTubeIngestManager(config, rag)

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

    # Search show subtitles and frames
    query = f'You: {trigger_msg["text"]}\n' + "\n".join([m.get("text", "") for m in recent_dms[-5:]])
    hits = await rag.search(query, k=5)
    show_snips = RAGIndex.render_for_prompt(hits)

    # Extract frame info for context
    frame_info = RAGIndex.extract_frame_info(hits)
    if frame_info:
        frame_context = f"\n\nAvailable video frames matching this context:\n"
        for i, frame in enumerate(frame_info[:2]):
            frame_context += f"- {frame['timestamp']}: {frame['caption'][:100]}...\n"
        show_snips += frame_context

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

    # Search show subtitles and frames for relevant lines
    query = f'{trigger_msg["from"]}: {trigger_msg["text"]}\n' + "\n".join([m["text"] for m in recent[-8:]])
    hits = await rag.search(query, k=6)  # Get more hits to include both transcript and frames
    show_snips = RAGIndex.render_for_prompt(hits)

    # Extract frame info for context (agents can see what frames are available)
    frame_info = RAGIndex.extract_frame_info(hits)
    if frame_info:
        frame_context = f"\n\nAvailable video frames matching this context:\n"
        for i, frame in enumerate(frame_info[:3]):  # Show top 3 frames
            frame_context += f"- {frame['timestamp']}: {frame['caption'][:100]}...\n"
        show_snips += frame_context

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

    elif name == "retrieve_scene":
        query = args.get("query", "")
        if query:
            # Check if query is a timestamp (e.g., "00:11:06,919" or "frame at 00:11:06,919")
            import re
            # Match timestamp pattern: HH:MM:SS,mmm or HH:MM:SS
            timestamp_match = re.search(r'(\d{1,2}):(\d{2}):(\d{2})(?:[,.](\d{1,3}))?', query)
            timestamp_str = None
            if timestamp_match:
                # Extract and normalize the timestamp
                hh, mm, ss = timestamp_match.groups()[:3]
                ms = timestamp_match.group(4) or "000"
                # Pad milliseconds to 3 digits
                ms = ms.ljust(3, '0')[:3]
                timestamp_str = f"{hh.zfill(2)}:{mm}:{ss},{ms}"

            # Search for frames - use timestamp search if we found a timestamp, otherwise semantic search
            if timestamp_str:
                # Search by timestamp first
                timestamp_hits = await rag.search_frames_by_timestamp(timestamp_str, tolerance_seconds=10.0)
                if timestamp_hits:
                    # Found frames by timestamp, prioritize them but also add semantic results for context
                    semantic_hits = await rag.search(query, k=3)
                    all_hits = timestamp_hits + semantic_hits
                else:
                    # Timestamp search found nothing, fall back to semantic search
                    print(f"No frames found at timestamp {timestamp_str}, using semantic search")
                    all_hits = await rag.search(query, k=8)
            else:
                # Regular semantic search
                all_hits = await rag.search(query, k=8)

            frame_info = RAGIndex.extract_frame_info(all_hits)

            # Get the best frame if available
            best_frame = frame_info[0] if frame_info else None

            # Get transcript context - prioritize temporal proximity if we have a frame
            if best_frame:
                # Search for transcripts near the frame's timestamp
                frame_timestamp_seconds = best_frame.get("timestamp_seconds")
                if frame_timestamp_seconds:
                    # Search with wider tolerance to get more context (before and after the frame)
                    temporal_transcript_hits = await rag.search_transcript_by_timestamp(
                        frame_timestamp_seconds,
                        tolerance_seconds=30.0  # Look for transcripts within 30 seconds (15s before and after)
                    )
                    # Prioritize transcripts that overlap with or are very close to the frame timestamp
                    # Sort by proximity to frame timestamp
                    def proximity_score(hit):
                        score, seg = hit
                        start_s = seg.metadata.get("start_s", 0)
                        end_s = seg.metadata.get("end_s", start_s + 5)
                        # Calculate how close this segment is to the frame
                        if start_s <= frame_timestamp_seconds <= end_s:
                            return 2.0  # Within segment - highest priority
                        else:
                            distance = min(abs(start_s - frame_timestamp_seconds), abs(end_s - frame_timestamp_seconds))
                            return 1.0 / (1.0 + distance)  # Closer = higher score

                    # Re-score and sort by proximity
                    temporal_transcript_hits = sorted(temporal_transcript_hits, key=proximity_score, reverse=True)

                    # Also get semantic matches for additional context
                    semantic_transcript_hits = [(score, s) for score, s in all_hits if s.metadata.get("type") == "srt"]
                    # Combine: temporal matches first (up to 8), then semantic (up to 3)
                    transcript_hits = temporal_transcript_hits[:8] + semantic_transcript_hits[:3]
                else:
                    # Fallback to semantic search if no timestamp
                    transcript_hits = [(score, s) for score, s in all_hits if s.metadata.get("type") == "srt"]
            else:
                # No frame found, use semantic search for transcripts
                transcript_hits = [(score, s) for score, s in all_hits if s.metadata.get("type") == "srt"]

            # Get nearby transcript context (prioritize temporal matches)
            # Use specialized transcript rendering for scene discussion
            if transcript_hits:
                transcript_context = RAGIndex.render_transcript_for_scene(transcript_hits, max_lines=6)
            else:
                transcript_context = "(no transcript lines found)"

            # Get recent chat context for the room
            recent = world.recent(a.room, n=10)
            recent_text = "\n".join([f'{m["from"]}: {m["text"]}' for m in recent[-8:]])

            # Get agent persona
            agent_profile = config.get("agent_profiles", {}).get(a.profile.agent_id, {})
            persona = agent_profile.get("persona", "")

            # Generate LLM response about the scene
            if best_frame:
                system = config.get("system_prompt")

                # Build transcript section - make it prominent
                transcript_section = ""
                if transcript_context and transcript_context != "(no transcript lines found)":
                    transcript_section = f"""
Transcript lines from around {best_frame['timestamp']}:
{transcript_context}

IMPORTANT: These transcript lines are from the exact moment or very close to the frame timestamp ({best_frame['timestamp']}). You MUST quote or reference at least one of these lines in your response to connect the visual moment with what's being said. Use the exact wording from the transcript.
"""
                else:
                    transcript_section = f"\n(No transcript lines found for this exact moment ({best_frame['timestamp']}), but you can still describe the visual content.)\n"

                user_prompt = f"""You are {a.profile.name}.

Persona:
{persona}

Recent chat in #{a.room}:
{recent_text}

You just retrieved a scene from the video. Here's what you found:

Frame at {best_frame['timestamp']}:
{best_frame['caption']}
{transcript_section}
Generate a natural, conversational response about this scene. You should:
- React to the visual content in the frame
- QUOTE at least one transcript line above - these are from the exact moment shown in the frame
- Connect the visual moment with what's being said in the transcript
- Use the exact wording from the transcript when quoting
- Connect it to the recent conversation if relevant
- Be authentic to your persona
- Keep it conversational (2-4 sentences)
- Mention the timestamp naturally (e.g., "at {best_frame['timestamp']}" or "around {best_frame['timestamp']}")

Example of how to quote: "Look at this moment at {best_frame['timestamp']} - when they say '[quote from transcript]', you can see [visual description]. The way [character] reacts here really shows..."

Write your response as if you're sharing this scene with the group. Make sure to include a direct quote from the transcript above:"""

                try:
                    resp = await llm.chat(
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user_prompt}
                        ]
                    )
                    frame_msg = (resp.get("message", {}).get("content") or "").strip()
                    if not frame_msg:
                        # Fallback if LLM doesn't return content
                        frame_msg = f"看看这个画面 ({best_frame['timestamp']}): {best_frame['caption']}"
                except Exception as e:
                    print(f"Error generating scene response for {a.profile.name}: {e}")
                    # Fallback message
                    frame_msg = f"看看这个画面 ({best_frame['timestamp']}): {best_frame['caption']}"

                # Send message with frame reference
                await world.post_message(a.room, a.profile.name, frame_msg)

                # Broadcast frame info for frontend to display
                await broadcast({
                    "type": "frame_reference",
                    "agent": a.profile.name,
                    "frame_file": best_frame["frame_file"],
                    "timestamp": best_frame["timestamp"],
                    "timestamp_seconds": best_frame["timestamp_seconds"],
                    "caption": best_frame["caption"],
                    "room": a.room,
                    "ts": time.time()
                })
            else:
                # No frame found, but might have transcript - generate response about transcript
                if transcript_context and transcript_context != "(no relevant knowledge base lines found)":
                    system = config.get("system_prompt")
                    user_prompt = f"""You are {a.profile.name}.

Persona:
{persona}

Recent chat in #{a.room}:
{recent_text}

You searched for "{query}" but couldn't find a specific frame. However, you found these transcript lines:

{transcript_context}

Generate a natural response about these transcript lines, connecting them to the conversation if relevant. Keep it conversational (1-3 sentences)."""

                    try:
                        resp = await llm.chat(
                            messages=[
                                {"role": "system", "content": system},
                                {"role": "user", "content": user_prompt}
                            ]
                        )
                        transcript_msg = (resp.get("message", {}).get("content") or "").strip()
                        if not transcript_msg:
                            transcript_msg = f"关于「{query}」:\n{transcript_context}"
                    except Exception as e:
                        print(f"Error generating transcript response for {a.profile.name}: {e}")
                        transcript_msg = f"关于「{query}」:\n{transcript_context}"

                    await world.post_message(a.room, a.profile.name, transcript_msg)
                else:
                    await world.post_message(a.room, a.profile.name, f"没找到关于「{query}」的画面或台词。")

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

        # Search show subtitles and frames for proactive moments (use recent chat context)
        query = "\n".join([m["text"] for m in recent[-8:]]) if recent else "show discussion"
        hits = await rag.search(query, k=6)  # Get more hits to include both transcript and frames
        show_snips = RAGIndex.render_for_prompt(hits)

        # Extract frame info for context
        frame_info = RAGIndex.extract_frame_info(hits)
        if frame_info:
            frame_context = f"\n\nAvailable video frames matching this context:\n"
            for i, frame in enumerate(frame_info[:3]):
                frame_context += f"- {frame['timestamp']}: {frame['caption'][:100]}...\n"
            show_snips += frame_context

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
from fastapi.responses import FileResponse

@app.get("/api/rag/frame")
async def get_frame(path: str = Query(...)):
    """Serve frame images from RAG directories."""
    # Path format from index: "frames/000001.jpg"
    # Actual location: "data/rag/<kb>/youtube/<video_id>/frames/000001.jpg"
    rag_dir_name = config.get("rag_directory", "default")
    rag_path = os.path.join("data/rag", rag_dir_name)

    # Extract just the filename
    frame_filename = path.split("/")[-1] if "/" in path else path

    # Search recursively in the RAG directory for this frame
    for root, dirs, files in os.walk(rag_path):
        if frame_filename in files:
            frame_path = os.path.join(root, frame_filename)
            if os.path.exists(frame_path) and frame_path.endswith(('.jpg', '.jpeg', '.png')):
                return FileResponse(frame_path, media_type="image/jpeg")

    return {"error": "Frame not found"}, 404

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

@app.post("/api/rag/youtube/ingest")
async def ingest_youtube(data: dict):
    dir_name = data.get("dir_name")
    urls = data.get("urls")
    if not dir_name or not urls:
        return {"error": "dir_name and urls required"}, 400

    job_id = await youtube_ingest.create_job(dir_name, urls)
    return {"status": "ok", "job_id": job_id}

@app.get("/api/rag/youtube/jobs/{job_id}")
async def get_youtube_job(job_id: str):
    job = youtube_ingest.jobs.get(job_id)
    if not job:
        return {"error": "job not found"}, 404
    return {
        "job_id": job.job_id,
        "status": job.status,
        "progress": job.progress,
        "current_url": job.current_url,
        "errors": job.errors,
        "results": job.results
    }

@app.post("/api/rag/start-conversation")
async def start_conversation_with_kb(data: dict):
    """Select a knowledge base and kick start a conversation with it."""
    name = data.get("name")
    if not name:
        return {"error": "name required"}, 400

    target_dir = os.path.join("data/rag", name)
    if not os.path.exists(target_dir):
        return {"error": "directory not found"}, 404

    # Select and load the RAG directory
    config.set("rag_directory", name)
    await rag.load_directory(target_dir)

    # Seed the initial chat
    await seed_initial_chat()

    return {"status": "ok", "current": name, "message": "Conversation started with knowledge base"}

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
