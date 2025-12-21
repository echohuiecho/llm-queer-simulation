"""
Run `uvicorn server:app --reload --port 8000` to start the server.
"""

import asyncio, json, time, random, os, logging, re
from typing import List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware

from llm import OllamaClient, GeminiClient
from rag_index import RAGIndex
from config import config
from youtube_ingest import YouTubeIngestManager

# ADK Imports
from adk_sim.state import get_initial_state
from adk_sim.tools import set_rag_index
from adk_sim.agents.root import root_agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai import types

# Silence noisy google-genai warning logs when responses include function_call parts.
# (ADK responses commonly include tool/function_call parts.)
logging.getLogger("google_genai.types").setLevel(logging.ERROR)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CONNS: List[WebSocket] = []

# Use Gemini for ADK and RAG if API key exists
google_api_key = config.get("google_api_key")
if google_api_key:
    llm = GeminiClient(google_api_key)
else:
    llm = OllamaClient(
        config.get("ollama_base"),
        config.get("chat_model"),
        config.get("embed_model"),
    )

# If GOOGLE_API_KEY isn't set, ADK's Gemini LlmAgents can't produce replies.
# We fall back to lightweight scripted replies so the UI still feels interactive.
HAS_GEMINI = bool(google_api_key)

# Generalized RAG index
rag = RAGIndex(llm.embed)
set_rag_index(rag)

# ADK Initialization
session_service = InMemorySessionService()
adk_runner = Runner(
    agent=root_agent,
    app_name="QueerSim",
    session_service=session_service
)
# Fixed session ID for the single simulation "world" for now
# or we can use one session per connection if we want isolated sims.
# The plan says "One ADK session per conversation (maps to UI session)".
GLOBAL_SESSION_ID = "default_sim"
GLOBAL_USER_ID = "simulation_user"

# Initialize global session
session_service.create_session_sync(
    app_name="QueerSim",
    user_id=GLOBAL_USER_ID,
    session_id=GLOBAL_SESSION_ID,
    state=get_initial_state()
)

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

async def seed_initial_chat():
    """Seed the initial chat log into group_chat.

    Clears existing group_chat history and replaces it with initial messages from config.
    This ensures that config changes are reflected when the server restarts or when
    the RAG directory is changed.
    """
    initial_messages = config.get("initial_messages", [])
    from adk_sim.state import add_message

    # Get current session state
    session = await session_service.get_session(
        app_name="QueerSim",
        user_id=GLOBAL_USER_ID,
        session_id=GLOBAL_SESSION_ID
    )
    state = session.state

    # Clear existing group_chat history to ensure we start fresh with config values
    if "history" not in state:
        state["history"] = {}
    state["history"]["group_chat"] = []

    # Clear outbox to avoid sending stale events
    state["outbox"] = []

    # Add initial messages from config
    for msg in initial_messages:
        sender = msg["sender"]
        text = msg["text"]
        add_message(state, "group_chat", sender, text)
        await asyncio.sleep(0.1)  # Small delay between messages

    # Persist updated state (get_session returns a copy, so we need to apply the delta)
    await apply_state_delta(
        {"history": state.get("history", {}), "outbox": state.get("outbox", [])},
        author="user"
    )

    # Flush outbox to broadcast initial messages to any connected clients
    await flush_adk_outbox()

    # Verify the state was persisted by re-reading the session
    session_after = await session_service.get_session(
        app_name="QueerSim",
        user_id=GLOBAL_USER_ID,
        session_id=GLOBAL_SESSION_ID
    )
    print(f"Seeded {len(initial_messages)} initial messages. Session history has {len(session_after.state.get('history', {}).get('group_chat', []))} messages.")

async def apply_state_delta(delta: dict, author: str = "user"):
    """Persist state updates into the ADK session store via a state-delta event.

    NOTE: ADK expects `Event.author` to be either "user" or a known agent name.
    Using "system" here causes noisy logs: "Event from an unknown agent: system".
    """
    session = await session_service.get_session(
        app_name="QueerSim",
        user_id=GLOBAL_USER_ID,
        session_id=GLOBAL_SESSION_ID
    )
    if session is None:
        return

    event = Event(
        author=author,
        invocation_id=f"server-{time.time()}",
        actions=EventActions(state_delta=delta),
    )
    await session_service.append_event(session=session, event=event)

async def flush_adk_outbox():
    """Flush the ADK state outbox to all WebSocket connections."""
    session = await session_service.get_session(
        app_name="QueerSim",
        user_id=GLOBAL_USER_ID,
        session_id=GLOBAL_SESSION_ID
    )
    outbox = session.state.get("outbox", [])
    if not outbox:
        return

    print(f"[FLUSH] Flushing {len(outbox)} events from outbox")
    for i, event in enumerate(outbox):
        # Check if this is a message with frameReference
        if event.get("type") == "message":
            if event.get("frameReference"):
                print(f"[FLUSH] Event {i}: message with frameReference: {event.get('from')} - frame_file: {event.get('frameReference', {}).get('frame_file')}")
                # Ensure frameReference is properly structured
                if not isinstance(event.get("frameReference"), dict):
                    print(f"[FLUSH] WARNING: frameReference is not a dict: {type(event.get('frameReference'))}")
            else:
                print(f"[FLUSH] Event {i}: message without frameReference: {event.get('from')} - keys: {list(event.keys())}")
                # Debug: print full event to see what's there
                import json
                print(f"[FLUSH] Full event {i}: {json.dumps(event, default=str)[:200]}")
        elif event.get("type") == "frame_reference":
            print(f"[FLUSH] Event {i}: frame_reference event: {event.get('frame_file')} for agent {event.get('agent')}")
        else:
            print(f"[FLUSH] Event {i}: {event.get('type')} - {str(event)[:100]}")
        await broadcast(event)

    # Clear outbox
    await apply_state_delta({"outbox": []}, author="user")

async def run_adk_turn(new_message_text: str):
    """Run a full ADK turn based on a new message."""
    async def run_scripted_fallback(note: str | None = None):
        """Scripted fallback so the sim still works if Gemini is unavailable."""
        session = await session_service.get_session(
            app_name="QueerSim",
            user_id=GLOBAL_USER_ID,
            session_id=GLOBAL_SESSION_ID,
        )
        state = session.state
        room = "group_chat"
        agents = state.get("agents", [])
        profiles = config.get("agent_profiles", {})

        from adk_sim.state import add_message
        if note:
            add_message(state, room, "System", note)

        templates = {
            "a1": "I’m here. EP2 ending hit hard — what part landed for you most?",
            "a2": "I hear you. Do we want a quick CW check-in before we unpack it?",
            "a3": "NO because I’m STILL thinking about that last scene 😭 what did you yell at your screen?",
        }
        for a in agents:
            aid = a.get("id")
            name = a.get("name") or profiles.get(aid, {}).get("name") or aid
            text = templates.get(aid) or "yeah, that was a lot — what stood out to you?"
            add_message(state, room, name, text)

        await apply_state_delta(
            {"history": state.get("history", {}), "outbox": state.get("outbox", [])},
            author="user",
        )
        await flush_adk_outbox()

    if not HAS_GEMINI:
        await run_scripted_fallback(
            note="System: GOOGLE_API_KEY not set; using scripted replies. Set GOOGLE_API_KEY to enable Gemini-powered agents."
        )
        return

    content = types.Content(role="user", parts=[types.Part(text=new_message_text)])

    # Run the ADK runner
    try:
        # Build a lightweight history summary for instruction injection
        session_for_summary = await session_service.get_session(
            app_name="QueerSim",
            user_id=GLOBAL_USER_ID,
            session_id=GLOBAL_SESSION_ID
        )
        history_str = ""
        if session_for_summary:
            for room, msgs in session_for_summary.state.get("history", {}).items():
                if msgs:
                    history_str += f"\n#{room}:\n"
                    for m in msgs[-10:]:
                        history_str += f"- {m['from']}: {m['text']}\n"

        profiles = config.get("agent_profiles", {})
        captured_by_author: dict[str, str] = {}

        async def _run():
            async for _event in adk_runner.run_async(
                user_id=GLOBAL_USER_ID,
                session_id=GLOBAL_SESSION_ID,
                new_message=content,
                # Ensure ADK can inject these variables into agent instructions
                state_delta={
                    "new_message": new_message_text,
                    "history_summary": history_str,
                },
            ):
                # Primary path: agents call tools (send_message) which write to outbox.
                # Fallback: if a persona agent outputs plain text, bridge it into chat so the UI still updates.
                try:
                    if (
                        _event.author
                        and _event.author != "user"
                        and _event.author in profiles
                        and _event.is_final_response()
                        and _event.content
                        and _event.content.parts
                    ):
                        text_parts: list[str] = []
                        for part in _event.content.parts:
                            if isinstance(part.text, str) and part.text.strip():
                                # Skip hidden "thought" parts if present
                                if isinstance(getattr(part, "thought", None), bool) and part.thought:
                                    continue
                                # Skip function_call parts - these are tool calls, not messages
                                if hasattr(part, "function_call") and part.function_call:
                                    continue
                                text_parts.append(part.text)
                        text = "".join(text_parts).strip()

                        # Filter out tool call patterns before capturing
                        if text:
                            import re
                            tool_call_pattern = r'^\s*(prepare_turn_context|retrieve_scene|send_message|send_dm|move_room|wait)\s*\([^)]*\)\s*$'
                            if not re.match(tool_call_pattern, text.strip(), re.IGNORECASE):
                                # Also check for JSON tool call structures
                                if not (text.strip().startswith('{') and ('"function"' in text or '"tool"' in text or '"name"' in text)):
                                    captured_by_author[_event.author] = text
                except Exception:
                    # Never fail the whole turn due to bridging logic.
                    pass

        # Guard against model/network hangs: fall back to scripted replies.
        await asyncio.wait_for(_run(), timeout=20)

        # ADK tools modify tool_context.state directly, and those changes should be automatically
        # persisted. However, get_session() returns a deep copy, so we need to ensure we're
        # reading the latest persisted state. Wait a bit for ADK to commit state changes.
        await asyncio.sleep(0.3)

        # Read the session state to get the outbox
        session_after = await session_service.get_session(
            app_name="QueerSim",
            user_id=GLOBAL_USER_ID,
            session_id=GLOBAL_SESSION_ID,
        )
        outbox = (session_after.state or {}).get("outbox", []) if session_after else []

        print(f"[RUN_ADK] Session outbox has {len(outbox)} events after tool execution")
        if outbox:
            # Debug: Check if any messages have frameReference
            has_frame_ref = False
            for i, evt in enumerate(outbox):
                if evt.get('type') == 'message' and 'frameReference' in evt:
                    print(f"[RUN_ADK] Outbox event {i} has frameReference: {evt.get('frameReference')}")
                    has_frame_ref = True
                elif evt.get('type') == 'message':
                    print(f"[RUN_ADK] Outbox event {i} is message without frameReference: {evt.get('from')}")
                    # Debug: print the full event to see what's there
                    import json
                    print(f"[RUN_ADK] Full event {i}: {json.dumps(evt, default=str)[:300]}")
                elif evt.get('type') == 'frame_reference':
                    print(f"[RUN_ADK] Outbox event {i} is frame_reference event: {evt.get('frame_file')}")

            # Flush the outbox - this will broadcast all events including frame_reference events
            await flush_adk_outbox()
            return

        # If no tool-driven outbox events, bridge any captured persona text into chat/outbox.
        if captured_by_author:
            session_bridge = await session_service.get_session(
                app_name="QueerSim",
                user_id=GLOBAL_USER_ID,
                session_id=GLOBAL_SESSION_ID,
            )
            state = session_bridge.state
            from adk_sim.state import add_message

            for author in sorted(captured_by_author.keys()):
                display = profiles.get(author, {}).get("name") or author
                add_message(state, "group_chat", display, captured_by_author[author])

            await apply_state_delta(
                {"history": state.get("history", {}), "outbox": state.get("outbox", [])},
                author="user",
            )
            await flush_adk_outbox()
            return

        # Nothing happened: provide scripted fallback so the UI still shows interaction.
        await run_scripted_fallback(
            note="System: Agents produced no visible actions; using scripted replies for this turn."
        )
        return
    except Exception as e:
        print(f"ADK Turn error: {e}")
        import traceback
        traceback.print_exc()
        await run_scripted_fallback(
            note="System: Gemini/ADK turn failed; using scripted replies for this turn."
        )

# Replace run_reactions and run_dm_reaction with ADK turns
async def run_reactions(trigger_msg):
    # For now, just trigger an ADK turn with the message text
    await run_adk_turn(trigger_msg["text"])

async def run_dm_reaction(agent_name: str, trigger_msg):
    # Trigger ADK turn, tools will handle DM logic
    await run_adk_turn(trigger_msg["text"])

# ---------- Proactive loop ----------

async def proactive_loop():
    """Every 20-60 seconds, trigger an ADK turn."""
    while True:
        await asyncio.sleep(random.uniform(20, 60))

        # 50% chance to just move agents slightly in state before turn
        session = await session_service.get_session(
            app_name="QueerSim",
            user_id=GLOBAL_USER_ID,
            session_id=GLOBAL_SESSION_ID,
        )

        if random.random() < 0.5:
            state = session.state
            agents = state.get("agents", [])
            if agents:
                agent = random.choice(agents)
                from adk_sim.state import update_agent_pos, add_to_outbox

                new_pos = {"x": random.uniform(0.1, 0.9), "y": random.uniform(0.1, 0.9)}
                update_agent_pos(state, agent["name"], agent["room"], new_pos)
                add_to_outbox(
                    state,
                    {
                        "type": "agent_state",
                        "id": agent["id"],
                        "name": agent["name"],
                        "room": agent["room"],
                        "pos": new_pos,
                        "ts": time.time(),
                    },
                )
                await apply_state_delta(
                    {"agents": state.get("agents", []), "outbox": state.get("outbox", [])},
                    author="user",
                )
                await flush_adk_outbox()

        await run_adk_turn("nothing happened, what do you do?")

# ---------- WebSocket ----------

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    CONNS.append(ws)

    # Get state from ADK session instead of world
    session = await session_service.get_session(
        app_name="QueerSim",
        user_id=GLOBAL_USER_ID,
        session_id=GLOBAL_SESSION_ID
    )
    sim_state = {
        "rooms": session.state["rooms"],
        "agents": session.state["agents"],
        "history": session.state["history"]
    }
    await ws.send_text(json.dumps({"type":"state", **sim_state}))

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)

            if msg["type"] == "user_message":
                room = msg["room"]
                text = msg["text"]

                # Update ADK state
                session = await session_service.get_session(
                    app_name="QueerSim",
                    user_id=GLOBAL_USER_ID,
                    session_id=GLOBAL_SESSION_ID
                )
                from adk_sim.state import add_message
                state = session.state
                add_message(state, room, "You", text)
                await apply_state_delta(
                    {"history": state.get("history", {}), "outbox": state.get("outbox", [])},
                    author="user"
                )

                # Broadcast user message immediately
                await flush_adk_outbox()

                # Run ADK turn for agent reactions
                try:
                    await run_adk_turn(text)
                except Exception as e:
                    print(f"Error running reactions: {e}")
                    await ws.send_text(json.dumps({
                        "type": "error",
                        "message": f"Agent response error: {str(e)}"
                    }))

            elif msg["type"] == "user_dm":
                agent_name = msg["agent"]
                text = msg["text"]

                # Update ADK state
                session = await session_service.get_session(
                    app_name="QueerSim",
                    user_id=GLOBAL_USER_ID,
                    session_id=GLOBAL_SESSION_ID
                )
                from adk_sim.state import add_dm
                state = session.state
                add_dm(state, "You", agent_name, text)
                await apply_state_delta(
                    {"history": state.get("history", {}), "outbox": state.get("outbox", [])},
                    author="user"
                )

                # Broadcast user DM immediately
                await flush_adk_outbox()

                # Run ADK turn for agent response
                try:
                    await run_adk_turn(text)
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
