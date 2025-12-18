from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import asyncio, json, time, random
from typing import Any, Dict, List, Optional

from memory import MemoryStore
from config import config

TOOLS: List[Dict[str, Any]] = [
  {
    "type": "function",
    "function": {
      "name": "send_message",
      "description": "Send a message to the current room",
      "parameters": {
        "type": "object",
        "required": ["text"],
        "properties": {"text": {"type": "string"}}
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "send_dm",
      "description": "Send a direct message to a specific person",
      "parameters": {
        "type": "object",
        "required": ["to", "text"],
        "properties": {
          "to": {"type": "string"},
          "text": {"type": "string"}
        }
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "move_room",
      "description": "Move to another room",
      "parameters": {
        "type": "object",
        "required": ["room"],
        "properties": {"room": {"type": "string"}}
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "wait",
      "description": "Do nothing for a while",
      "parameters": {
        "type": "object",
        "required": ["minutes"],
        "properties": {"minutes": {"type": "integer"}}
      }
    }
  },
]

@dataclass
class AgentProfile:
    agent_id: str
    name: str
    persona: str

class Agent:
    def __init__(self, profile: AgentProfile, memory: MemoryStore, room: str):
        self.profile = profile
        self.memory = memory
        self.room = room
        self.last_spoke_ts: float = 0.0
        self.room_entered_ts: float = 0.0  # Track when agent entered current room
        self.pos = {"x": random.uniform(0.1, 0.9), "y": random.uniform(0.1, 0.9)}

    async def decide(self, llm, room: str, room_desc: str, recent_chat: List[Dict[str, Any]],
                     trigger: Dict[str, Any], available_rooms: Optional[List[str]] = None, show_snips: str = "") -> Dict[str, Any]:
        # Build retrieval query around the trigger + current room
        trigger_line = f'{trigger.get("from")}: {trigger.get("text")}'
        query = f"Room:{room}. Latest:{trigger_line}. Decide how {self.profile.name} should respond."
        mems = await self.memory.retrieve(query, k=6)

        recent_text = "\n".join([f'{m["from"]}: {m["text"]}' for m in recent_chat[-12:]])

        system = config.get("system_prompt")

        rooms_info = ""
        if available_rooms:
            other_rooms = [r for r in available_rooms if r != room]
            if other_rooms:
                rooms_info = f"\n\nAvailable other rooms: {', '.join(other_rooms)}"

        # Check if this is a proactive trigger (system-initiated)
        is_proactive = trigger.get("from") == "system" or trigger.get("type") == "proactive"

        # Calculate how long agent has been in current room
        time_in_room = time.time() - self.room_entered_ts if self.room_entered_ts > 0 else 0
        minutes_in_room = int(time_in_room / 60)

        proactive_nudge = ""
        if is_proactive:
            room_time_note = ""
            if minutes_in_room > 5:
                room_time_note = f" You've been in #{room} for about {minutes_in_room} minutes - consider if you want to move somewhere else."
            proactive_nudge = f"\n\nNote: This is a proactive moment - you can choose to move rooms, send a message, or wait. Consider if you want to explore other spaces or if the current room feels right.{room_time_note}"

        user = f"""
You are {self.profile.name}.
Persona:
{self.profile.persona}

Current room: #{room}
Room vibe/notes:
{room_desc}{rooms_info}

Recent chat in #{room}:
{recent_text}

Show subtitle lines you may cite:
{show_snips}

Rules for using show quotes:
- When referencing the show, quote the actual subtitle text directly (e.g., "I'm serious" (E1P2 00:12:34–00:12:36)).
- Include the timecode in parentheses after the quote to show when it appears.
- Quote at most ONE short subtitle line; otherwise paraphrase.
- Don't invent quotes that aren't in the provided lines.
- Use the exact wording from the subtitle when possible.

Relevant memories:
- """ + "\n- ".join(mems) + """{proactive_nudge}

Choose exactly ONE action by calling ONE tool:
- send_message(text) - to say something in the current room
- move_room(room) - to move to a different room (use one of: {', '.join(available_rooms) if available_rooms else 'group_chat, cafe, apartment'})
- wait(minutes) - to do nothing for a while

Guidelines:
- Be welcoming to newcomers.
- Keep it conversational and not too long.
- If the topic is heavy, suggest a gentle CW without being preachy.
- You can move rooms naturally - maybe you want a quieter space, want to check another room, need a break, or want to see what's happening elsewhere.
- Don't stay in the same room all the time - variety makes the simulation interesting.
- If the current room has been quiet or you've been there a while, consider moving to another room.
"""

        resp = await llm.chat(
            messages=[{"role":"system","content":system},{"role":"user","content":user}],
            tools=TOOLS
        )

        msg = resp.get("message", {}) or {}
        tool_calls = msg.get("tool_calls") or []

        if tool_calls:
            # Ollama typically returns {"function":{"name":..,"arguments":{..}}}
            return tool_calls[0]["function"]

        # fallback if no tool call
        content = (msg.get("content") or "").strip()
        if content:
            return {"name": "send_message", "arguments": {"text": content}}

        return {"name": "wait", "arguments": {"minutes": 10}}

    async def decide_dm(self, llm, recent_dms: List[Dict[str, Any]], trigger: Dict[str, Any],
                       recent_room: List[Dict[str, Any]], room_desc: str, show_snips: str = "") -> Dict[str, Any]:
        """Decide how to respond to a DM from the user."""
        trigger_line = f'{trigger.get("from")}: {trigger.get("text")}'
        query = f"DM conversation. Latest:{trigger_line}. Decide how {self.profile.name} should respond privately."
        mems = await self.memory.retrieve(query, k=6)

        recent_dm_text = "\n".join([f'{m.get("from", "?")}: {m.get("text", "")}' for m in recent_dms[-10:]])
        recent_room_text = "\n".join([f'{m.get("from", "?")}: {m.get("text", "")}' for m in recent_room[-5:]])

        system = config.get("system_prompt")

        user = f"""
You are {self.profile.name}.
Persona:
{self.profile.persona}

You are having a private direct message conversation with the user.

Recent DM conversation:
{recent_dm_text}

Recent activity in your current room (for context):
{recent_room_text}

Show subtitle lines you may cite:
{show_snips}

Rules for using show quotes:
- When referencing the show, quote the actual subtitle text directly (e.g., "I'm serious" (E1P2 00:12:34–00:12:36)).
- Include the timecode in parentheses after the quote to show when it appears.
- Quote at most ONE short subtitle line; otherwise paraphrase.
- Don't invent quotes that aren't in the provided lines.
- Use the exact wording from the subtitle when possible.

Relevant memories:
- """ + "\n- ".join(mems) + """

Choose exactly ONE action by calling ONE tool:
- send_dm(to="You", text) - to reply to the user's DM
- send_message(text) - to say something in the current room (if you want to mention something publicly)
- wait(minutes) - to do nothing for a while

Guidelines:
- This is a private conversation - be more personal and direct than in public rooms.
- Keep it conversational and not too long.
- You can reference what's happening in rooms if relevant, but focus on the private conversation.
- Be genuine and authentic to your persona.
"""

        resp = await llm.chat(
            messages=[{"role":"system","content":system},{"role":"user","content":user}],
            tools=TOOLS
        )

        msg = resp.get("message", {}) or {}
        tool_calls = msg.get("tool_calls") or []

        if tool_calls:
            return tool_calls[0]["function"]

        # fallback if no tool call
        content = (msg.get("content") or "").strip()
        if content:
            return {"name": "send_dm", "arguments": {"to": "You", "text": content}}

        return {"name": "wait", "arguments": {"minutes": 10}}
