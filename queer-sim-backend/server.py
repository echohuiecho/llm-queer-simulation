"""
Run `uvicorn server:app --reload --port 8000` to start the server.
"""

import asyncio, json, time, random, os, logging, re
from typing import List, Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware

from llm import OllamaClient, GeminiClient
from rag_index import RAGIndex
from config import config
from youtube_ingest import YouTubeIngestManager

# ADK Imports
from adk_sim.state import get_initial_state
from adk_sim.tools import set_rag_index, compute_storyline_milestone, compute_storyline_expansion_milestone
from adk_sim.agents.root import root_agent, create_root_agent_with_shuffled_order
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
# Create initial runner with shuffled order
# The root agent will be recreated with a new shuffled order before each turn
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
    If storyline_context_content is set, dynamically generates messages about planning that storyline.
    Otherwise uses fixed initial_messages from config.
    This ensures that config changes are reflected when the server restarts or when
    the RAG directory is changed.
    """
    from adk_sim.state import add_message

    storyline_context = config.get("storyline_context_content", "")
    storyline_dir = config.get("storyline_context_dir", "")

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

    # If storyline context is active, generate dynamic initial messages
    if storyline_context and storyline_context.strip():
        print(f"[SEED] Generating dynamic initial messages for storyline: {storyline_dir}")
        initial_messages = await generate_storyline_initial_messages(storyline_context)
    else:
        initial_messages = config.get_initial_messages()

    # Add initial messages
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

async def generate_storyline_initial_messages(storyline_context: str) -> List[Dict[str, Any]]:
    """Generate initial messages from agents discussing the storyline planning.

    Uses LLM to generate 3 messages from different agents (Noor, Ji-woo, Mika)
    that kick off a discussion about planning the given storyline.
    """
    if not HAS_GEMINI:
        # Fallback to simple template if no LLM
        profiles = config.get_agent_profiles()
        agent_names = [profiles.get("a1", {}).get("name", "Noor K."),
                      profiles.get("a2", {}).get("name", "Ji-woo"),
                      profiles.get("a3", {}).get("name", "Mika Tan")]
        return [
            {"sender": agent_names[0], "text": f"Let's start planning this storyline: {storyline_context[:100]}..."},
            {"sender": agent_names[1], "text": "I'm excited to work on this together!"},
            {"sender": agent_names[2], "text": "Same! Let's dive into the details."}
        ]

    lang = config.get("language", "en").replace("-", "_")
    profiles = config.get_agent_profiles(lang)

    # Get agent names in current language
    agent_names = {
        "a1": profiles.get("a1", {}).get("name", "Noor K."),
        "a2": profiles.get("a2", {}).get("name", "Ji-woo"),
        "a3": profiles.get("a3", {}).get("name", "Mika Tan")
    }

    # Build prompt based on language
    if lang == "zh_Hans":
        system_prompt = "你是一个助手，帮助生成三个角色之间的对话，讨论如何规划一个网络漫画故事情节。"
        user_prompt = f"""请为以下三个角色生成3条初始消息，开始讨论如何规划这个故事情节：

故事情节背景：
{storyline_context}

角色：
- {agent_names["a1"]} (a1): {profiles.get("a1", {}).get("persona", "")[:200]}...
- {agent_names["a2"]} (a2): {profiles.get("a2", {}).get("persona", "")[:200]}...
- {agent_names["a3"]} (a3): {profiles.get("a3", {}).get("persona", "")[:200]}...

要求：
1. 生成3条消息，每条来自不同角色（a1, a2, a3各一条）
2. 消息应该自然地开始讨论如何规划这个故事情节的细节
3. 保持每个角色的个性特点
4. 用简体中文回复
5. 返回JSON格式：{{"messages": [{{"sender": "角色名", "text": "消息内容"}}, ...]}}"""
    elif lang == "zh_Hant":
        system_prompt = "你是一個助手，幫助生成三個角色之間的對話，討論如何規劃一個網絡漫畫故事情節。"
        user_prompt = f"""請為以下三個角色生成3條初始消息，開始討論如何規劃這個故事情節：

故事情節背景：
{storyline_context}

角色：
- {agent_names["a1"]} (a1): {profiles.get("a1", {}).get("persona", "")[:200]}...
- {agent_names["a2"]} (a2): {profiles.get("a2", {}).get("persona", "")[:200]}...
- {agent_names["a3"]} (a3): {profiles.get("a3", {}).get("persona", "")[:200]}...

要求：
1. 生成3條消息，每條來自不同角色（a1, a2, a3各一條）
2. 消息應該自然地開始討論如何規劃這個故事情節的細節
3. 保持每個角色的個性特點
4. 用繁體中文回覆
5. 返回JSON格式：{{"messages": [{{"sender": "角色名", "text": "消息內容"}}, ...]}}"""
    else:  # English
        system_prompt = "You are an assistant that helps generate conversations between three characters discussing how to plan a webtoon storyline."
        user_prompt = f"""Generate 3 initial messages from these three characters to start a discussion about planning this storyline:

Storyline Context:
{storyline_context}

Characters:
- {agent_names["a1"]} (a1): {profiles.get("a1", {}).get("persona", "")[:200]}...
- {agent_names["a2"]} (a2): {profiles.get("a2", {}).get("persona", "")[:200]}...
- {agent_names["a3"]} (a3): {profiles.get("a3", {}).get("persona", "")[:200]}...

Requirements:
1. Generate 3 messages, one from each character (a1, a2, a3)
2. Messages should naturally start a discussion about planning the details of this storyline
3. Keep each character's personality traits
4. Return JSON format: {{"messages": [{{"sender": "Character Name", "text": "message text"}}, ...]}}"""

    try:
        response = await llm.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )

        content = response.get("message", {}).get("content", "")
        if not content:
            raise ValueError("Empty response from LLM")

        # Try to parse JSON from response
        import json
        # Extract JSON from markdown code blocks if present
        if "```" in content:
            json_start = content.find("```")
            json_end = content.rfind("```")
            if json_start != -1 and json_end != -1:
                json_str = content[json_start:json_end].replace("```json", "").replace("```", "").strip()
            else:
                json_str = content
        else:
            json_str = content

        # Try to find JSON object
        json_start = json_str.find("{")
        json_end = json_str.rfind("}") + 1
        if json_start != -1 and json_end > json_start:
            json_str = json_str[json_start:json_end]

        parsed = json.loads(json_str)
        messages = parsed.get("messages", [])

        # Ensure we have exactly 3 messages, one from each agent
        if len(messages) >= 3:
            return messages[:3]
        elif len(messages) > 0:
            # Pad with fallback messages if needed
            used_senders = {msg.get("sender", "") for msg in messages}
            all_agents = [agent_names["a1"], agent_names["a2"], agent_names["a3"]]
            for agent_name in all_agents:
                if agent_name not in used_senders and len(messages) < 3:
                    if lang in ["zh_Hans", "zh_Hant"]:
                        messages.append({"sender": agent_name, "text": "我也來參與討論！"})
                    else:
                        messages.append({"sender": agent_name, "text": "I'd like to join the discussion!"})
            return messages[:3]
        else:
            raise ValueError("No messages in response")

    except Exception as e:
        print(f"[SEED] Error generating storyline messages: {e}")
        # Fallback to simple template
        return [
            {"sender": agent_names["a1"], "text": f"Let's start planning this storyline."},
            {"sender": agent_names["a2"], "text": "I'm excited to work on this together!"},
            {"sender": agent_names["a3"], "text": "Same! Let's dive into the details."}
        ]

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
    """Run a full ADK turn based on a new message.

    Before each turn, we create a new root agent with shuffled persona agent order.
    This ensures each agent sees state updates in a different order each turn,
    making their responses more varied and natural.
    """
    # Note: we create the per-turn root agent AFTER we compute milestone state,
    # so we can optionally extend the pipeline with the webtoon storyline loop.

    async def run_scripted_fallback(note: str | None = None):
        """Context-aware fallback so the sim still works if Gemini/ADK fails."""
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

        history = (state.get("history") or {}).get(room) or []
        recent = [m for m in history[-10:] if isinstance(m, dict)]
        anchor = ""
        for m in reversed(recent):
            if m.get("from") and m.get("from") != "System" and isinstance(m.get("text"), str) and m["text"].strip():
                anchor = m["text"].strip()
                break
        if not anchor:
            anchor = new_message_text.strip() if isinstance(new_message_text, str) and new_message_text.strip() else "that last point"

        cur_story = state.get("current_storyline") if isinstance(state.get("current_storyline"), dict) else {}
        title = cur_story.get("title") if isinstance(cur_story.get("title"), str) else ""
        version = int(state.get("storyline_version") or 0)
        try:
            current_ep = int(state.get("current_episode_number") or 1)
        except Exception:
            current_ep = 1

        # New: Get scene progress for fallback
        scenes = cur_story.get("scenes", []) if isinstance(cur_story, dict) else []
        ep1_scenes = sum(1 for s in scenes if isinstance(s, dict) and int(s.get("episode") or 0) == 1)
        progress_suffix = ""
        if current_ep == 1:
            progress_suffix = f" ({ep1_scenes}/12)"

        def _fallback_text(aid: str) -> str:
            if cur_story and title:
                # Check if we need more scenes
                scenes_count = sum(1 for s in scenes if isinstance(s, dict) and int(s.get("episode", 0)) == current_ep)
                needs_scenes = (current_ep == 1 and scenes_count < 12)

                if needs_scenes:
                    # Directive messages to add scenes
                    if aid == "a1":
                        return f"We're at {scenes_count}/12 scenes for episode {current_ep}. Let's add scene {scenes_count + 1} — what happens next in the story?"
                    if aid == "a2":
                        return f"Episode {current_ep} needs {12 - scenes_count} more scenes. Should we add a scene showing their relationship developing?"
                    return f"Only {scenes_count}/12 scenes so far! Let's add scene {scenes_count + 1} — 3-6 panels, punchy dialogue!"
                else:
                    # Regular conversation
                    if aid == "a1":
                        return (
                            f"Quick check-in on our webtoon draft (v{version}) — for episode {current_ep}{progress_suffix}, "
                            f"what's the next clean beat after: \"{anchor[:80]}\"?"
                        )
                    if aid == "a2":
                        return (
                            f"To keep episode {current_ep}{progress_suffix} coherent, should we add one bridging scene after "
                            f"\"{anchor[:70]}\"? What do you want the last panel to *feel* like?"
                        )
                    return (
                        f"Okay wait I'm obsessed. For episode {current_ep}{progress_suffix}, do we add a new scene right after "
                        f"\"{anchor[:70]}\" — like 3 vertical panels, punchy dialogue?"
                    )

            if aid == "a1":
                return f"I’m with you. When you say “{anchor[:90]}”, what’s the subtext you’re reading there?"
            if aid == "a2":
                return f"Same page. If we zoom in on “{anchor[:85]}”, what’s the key need/boundary in that moment?"
            return f"Wait yes. “{anchor[:85]}” is SUCH a moment — what did you want to happen next?"
        for a in agents:
            aid = a.get("id")
            name = a.get("name") or profiles.get(aid, {}).get("name") or aid
            text = _fallback_text(str(aid))
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

        # CRITICAL: Reload storyline from disk to ensure session state is fresh
        # This prevents stale scene counts from causing incorrect agent behavior
        if session_for_summary and session_for_summary.state:
            from adk_sim.persistence import get_storyline_persistence
            storyline_dir = session_for_summary.state.get("storyline_context_dir") or config.get("storyline_context_dir", "default")
            persistence = get_storyline_persistence()
            disk_storyline = persistence.load_latest_storyline(storyline_dir)

            if disk_storyline:
                disk_version = disk_storyline.get("meta", {}).get("version", 0)
                session_version = int(session_for_summary.state.get("storyline_version", 0))

                # Sync session from disk if disk has newer or equal version
                if disk_version >= session_version:
                    print(f"[SERVER] Syncing session from disk: v{session_version} -> v{disk_version}")
                    await apply_state_delta({
                        "current_storyline": disk_storyline,
                        "current_storyline_json": json.dumps(disk_storyline, ensure_ascii=False),
                        "storyline_version": disk_version,
                    }, author="system")

                    # Reload session after update
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

        # Decide whether to trigger webtoon storyline planning this turn.
        # NOTE: We run a "plan-only" pipeline when storyline is missing (version==0),
        # because the full reviewer/refiner loop is slower and was causing timeouts,
        # leaving the system stuck at v0.
        enable_storyline = False
        storyline_mode = "full"  # "full" | "plan_only"
        storyline_focus = "chat"
        if session_for_summary and session_for_summary.state:
            tmp_state = dict(session_for_summary.state)
            tmp_state["new_message"] = new_message_text
            enable_storyline = compute_storyline_milestone(tmp_state, room="group_chat")
            print(f"[SERVER] Milestone check result: enable_storyline={enable_storyline}")

            # Check if we should focus on expansion (adding scenes)
            # Default to expand if storyline exists and we haven't reached 12 scenes
            storyline = tmp_state.get("current_storyline", {})
            if isinstance(storyline, dict):
                scenes = storyline.get("scenes", [])
                current_ep = int(tmp_state.get("current_episode_number", 1))
                if current_ep == 1:
                    ep1_scenes = sum(1 for s in scenes if isinstance(s, dict) and int(s.get("episode", 0)) == 1)
                    if ep1_scenes < 12:
                        storyline_focus = "expand"
                        print(f"[SERVER] Focus: expand (Episode 1 has {ep1_scenes}/12 scenes)")

            if not enable_storyline and compute_storyline_expansion_milestone(tmp_state, room="group_chat"):
                storyline_focus = "expand"

        if enable_storyline:
            print(f"[SERVER] Triggering storyline planning loop")
            # If there's no storyline yet, run the fast plan-only pipeline to reliably create v1.
            try:
                existing_state = session_for_summary.state or {}
                existing_version = int(existing_state.get("storyline_version") or 0)
                has_storyline = bool(existing_state.get("current_storyline")) and bool(
                    str(existing_state.get("current_storyline_json") or "").strip()
                )
                if existing_version <= 0 or not has_storyline:
                    storyline_mode = "plan_only"
            except Exception:
                storyline_mode = "plan_only"

            # Latch so we don't trigger repeatedly.
            await apply_state_delta(
                {
                    "storyline_triggered": True,
                    "storyline_iteration": 0,
                    "storyline_review_status": "",
                    "review_feedback": "",
                },
                author="user",
            )

        # Create a new root agent with shuffled order for this turn.
        # If enable_storyline is True, the root includes the LoopAgent refinement pipeline.
        shuffled_root_agent = create_root_agent_with_shuffled_order(
            enable_storyline=enable_storyline, storyline_mode=storyline_mode
        )

        # Create a new runner with the per-turn root agent.
        turn_runner = Runner(
            agent=shuffled_root_agent,
            app_name="QueerSim",
            session_service=session_service,
        )

        profiles = config.get("agent_profiles", {})
        captured_by_author: dict[str, str] = {}

        # Recalculate episode progress for state_delta (must be fresh each turn)
        from adk_sim.tools import get_episode_progress_summary
        # Get fresh state to ensure we have latest episode info
        fresh_session = await session_service.get_session(
            app_name="QueerSim",
            user_id=GLOBAL_USER_ID,
            session_id=GLOBAL_SESSION_ID,
        )
        episode_progress = get_episode_progress_summary(fresh_session.state if fresh_session else {})

        async def _run():
            async for _event in turn_runner.run_async(
                user_id=GLOBAL_USER_ID,
                session_id=GLOBAL_SESSION_ID,
                new_message=content,
                # Ensure ADK can inject these variables into agent instructions
                state_delta={
                    "new_message": new_message_text,
                    "history_summary": history_str,
                    "storyline_focus": storyline_focus,
                    "storyline_context": config.get("storyline_context_content", ""),
                    "storyline_context_dir": config.get("storyline_context_dir", ""),
                    "episode_progress": episode_progress,
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
        # Increase timeout when storyline planning is enabled (it takes longer)
        # Planning-only should be quick; keep a smaller timeout to avoid hanging the whole turn.
        timeout_seconds = 35 if (enable_storyline and storyline_mode == "plan_only") else (60 if enable_storyline else 30)
        try:
            await asyncio.wait_for(_run(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            print(f"[RUN_ADK] Turn timed out after {timeout_seconds}s (storyline={enable_storyline})")
            # Save partial work and check for episode completion before failing
            try:
                session_after_timeout = await session_service.get_session(
                    app_name="QueerSim",
                    user_id=GLOBAL_USER_ID,
                    session_id=GLOBAL_SESSION_ID,
                )
                if session_after_timeout and session_after_timeout.state:
                    state = session_after_timeout.state

                    # Check if episode completion should trigger completion (e.g. 12 scenes reached)
                    from adk_sim.tools import check_episode_completion_votes, process_episode_completion
                    from adk_sim.state import add_message, add_to_outbox

                    storyline = state.get("current_storyline")
                    if isinstance(storyline, dict):
                        scenes = storyline.get("scenes", [])
                        current_ep = int(state.get("current_episode_number") or 1)
                        ep1_scenes = sum(1 for s in scenes if isinstance(s, dict) and int(s.get("episode") or 0) == 1)

                        if current_ep == 1 and ep1_scenes >= 12:
                            # Auto-complete episode 1 if 12 scenes reached
                            print(f"[TIMEOUT_RECOVERY] Episode 1 reached {ep1_scenes} scenes, processing completion")
                            result = process_episode_completion(state, 1, room="group_chat")

                            await apply_state_delta({
                                "current_storyline": state.get("current_storyline"),
                                "current_storyline_json": json.dumps(state.get("current_storyline"), ensure_ascii=False),
                                "storyline_version": result["version"],
                                "current_episode_number": result["next_episode"],
                                "outbox": state.get("outbox", []),
                            }, author="system")
                            await flush_adk_outbox()

                    # Save partial storyline state - but only if it's not stale
                    storyline = state.get("current_storyline")
                    if isinstance(storyline, dict) and storyline:
                        version = state.get("storyline_version", 0)
                        storyline_dir = state.get("storyline_context_dir") or config.get("storyline_context_dir", "default")
                        from adk_sim.persistence import get_storyline_persistence
                        persistence = get_storyline_persistence()

                        # CRITICAL: Check if a newer version already exists on disk
                        # (Tool calls may have saved successfully before the timeout)
                        disk_storyline = persistence.load_latest_storyline(storyline_dir)
                        disk_version = disk_storyline.get("meta", {}).get("version", 0) if disk_storyline else 0

                        if version > disk_version:
                            # Session has newer version, save it
                            persistence.save_storyline(storyline_dir, storyline, version, update_type="timeout_recovery")
                            print(f"[RUN_ADK] Saved partial storyline state (v{version}) after timeout")
                        else:
                            # Disk has same or newer version, don't overwrite
                            print(f"[RUN_ADK] Skipping timeout save: disk has v{disk_version}, session has v{version}")
                            # Update session to match disk to avoid inconsistency
                            if disk_version > version:
                                print(f"[RUN_ADK] Disk is newer (v{disk_version}), syncing session state from disk")
                                await apply_state_delta({
                                    "current_storyline": disk_storyline,
                                    "current_storyline_json": json.dumps(disk_storyline, ensure_ascii=False),
                                    "storyline_version": disk_version,
                                }, author="system")
            except Exception as e:
                print(f"[RUN_ADK] Error processing timeout recovery: {e}")
                import traceback
                traceback.print_exc()
            raise

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
        state_after = session_after.state if session_after else {}
        outbox = state_after.get("outbox", [])

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

        # Nothing happened: provide fallback so the UI still shows interaction.
        await run_scripted_fallback(note="System: Agents produced no visible actions; using fallback replies for this turn.")
        return
    except Exception as e:
        print(f"ADK Turn error: {e}")
        import traceback
        traceback.print_exc()
        # If any tool output already landed in outbox, flush it instead of spamming fallback.
        try:
            session_err = await session_service.get_session(
                app_name="QueerSim",
                user_id=GLOBAL_USER_ID,
                session_id=GLOBAL_SESSION_ID,
            )
            outbox_err = (session_err.state or {}).get("outbox", []) if session_err else []
            if outbox_err:
                await flush_adk_outbox()
                return
        except Exception:
            pass
        await run_scripted_fallback(note="System: Gemini/ADK turn failed; using fallback replies for this turn.")

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

@app.get("/api/debug/storyline-state")
async def get_storyline_debug_state():
    """Return detailed storyline state for debugging."""
    session = await session_service.get_session(
        app_name="QueerSim",
        user_id=GLOBAL_USER_ID,
        session_id=GLOBAL_SESSION_ID,
    )
    from adk_sim.tools import get_episode_progress_summary
    from adk_sim.validation import validate_storyline_state

    state = session.state if session else {}
    storyline = state.get("current_storyline", {})
    scenes = storyline.get("scenes", []) if isinstance(storyline, dict) else []

    return {
        "version": state.get("storyline_version", 0),
        "scene_count": len(scenes),
        "episode_progress": get_episode_progress_summary(state),
        "last_update": state.get("last_storyline_update_ts", 0),
        "validation_errors": validate_storyline_state(state),
        "current_episode": state.get("current_episode_number", 1),
        "storyline_exists": bool(storyline),
    }

@app.post("/api/debug/force-save-storyline")
async def force_save_storyline():
    """Manually trigger storyline file save."""
    session = await session_service.get_session(
        app_name="QueerSim",
        user_id=GLOBAL_USER_ID,
        session_id=GLOBAL_SESSION_ID,
    )
    if not session or not session.state:
        return {"status": "error", "message": "No session found"}

    state = session.state
    storyline = state.get("current_storyline", {})
    if not isinstance(storyline, dict) or not storyline:
        return {"status": "error", "message": "No storyline to save"}

    version = state.get("storyline_version", 0)
    storyline_dir = state.get("storyline_context_dir") or config.get("storyline_context_dir", "default")

    from adk_sim.persistence import get_storyline_persistence
    persistence = get_storyline_persistence()
    result = persistence.save_storyline(storyline_dir, storyline, version, update_type="manual_save")

    return {"status": "ok", "result": result}

@app.post("/api/recover-from-checkpoint")
async def recover_from_checkpoint():
    """Load the latest saved storyline from disk if state gets corrupted."""
    session = await session_service.get_session(
        app_name="QueerSim",
        user_id=GLOBAL_USER_ID,
        session_id=GLOBAL_SESSION_ID,
    )
    if not session:
        return {"status": "error", "message": "No session found"}

    state = session.state
    storyline_dir = state.get("storyline_context_dir") or config.get("storyline_context_dir", "default")

    from adk_sim.persistence import get_storyline_persistence
    persistence = get_storyline_persistence()
    loaded = persistence.load_latest_storyline(storyline_dir)

    if not loaded:
        return {"status": "error", "message": "No saved storyline found"}

    # Update state with loaded storyline
    state["current_storyline"] = loaded
    state["current_storyline_json"] = json.dumps(loaded, ensure_ascii=False)
    state["storyline_version"] = loaded.get("meta", {}).get("version", 0)

    await apply_state_delta({
        "current_storyline": loaded,
        "current_storyline_json": state["current_storyline_json"],
        "storyline_version": state["storyline_version"],
    }, author="system")

    return {"status": "ok", "version": state["storyline_version"], "message": "Storyline recovered from disk"}

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

@app.post("/api/storyline/reset")
async def reset_storyline():
    """Reset storyline trigger flag to allow re-triggering."""
    session = await session_service.get_session(
        app_name="QueerSim",
        user_id=GLOBAL_USER_ID,
        session_id=GLOBAL_SESSION_ID,
    )
    if session:
        await apply_state_delta(
            {"storyline_triggered": False},
            author="user"
        )
    return {"status": "ok", "message": "Storyline trigger flag reset"}

@app.get("/api/storylines")
async def list_storylines():
    """List available storyline directories."""
    storyline_root = "data/state/storyline"
    if not os.path.exists(storyline_root):
        os.makedirs(storyline_root, exist_ok=True)
        return {"storylines": [], "current": config.get("storyline_context_dir", "")}

    dirs = [d for d in os.listdir(storyline_root) if os.path.isdir(os.path.join(storyline_root, d))]
    return {"storylines": dirs, "current": config.get("storyline_context_dir", "")}

@app.post("/api/storylines/select")
async def select_storyline(data: dict):
    """Select a storyline and load its context.txt."""
    dir_name = data.get("name", "")

    if not dir_name:
        # Clear storyline context
        config.set("storyline_context_dir", "")
        config.set("storyline_context_content", "")
        return {"status": "ok", "current": "", "message": "Storyline context cleared"}

    storyline_path = os.path.join("data/state/storyline", dir_name)
    if not os.path.exists(storyline_path):
        return {"error": "storyline directory not found"}, 404

    context_file = os.path.join(storyline_path, "context.txt")
    if not os.path.exists(context_file):
        return {"error": "context.txt not found in storyline directory"}, 404

    # Read context.txt
    try:
        with open(context_file, "r", encoding="utf-8") as f:
            context_content = f.read().strip()

        config.set("storyline_context_dir", dir_name)
        config.set("storyline_context_content", context_content)

        return {"status": "ok", "current": dir_name, "content": context_content}
    except Exception as e:
        return {"error": f"Failed to read context.txt: {str(e)}"}, 500

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
