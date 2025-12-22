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
  {
    "type": "function",
    "function": {
      "name": "retrieve_scene",
      "description": "Retrieve and discuss a specific scene from the video by searching for frames and transcript context. Use this when you want to reference visual content or discuss what happens at a specific moment in the show.",
      "parameters": {
        "type": "object",
        "required": ["query"],
        "properties": {
          "query": {
            "type": "string",
            "description": "Description of the scene or moment you want to retrieve (e.g., 'kiss scene', 'emotional moment at 5 minutes', 'character expression')"
          }
        }
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

        system = config.get_system_prompt()

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
- retrieve_scene(query) - to retrieve and discuss a specific scene from the video. Query can be a description (e.g., "kiss scene", "emotional moment") or a timestamp (e.g., "00:11:06,919" or "frame at 00:11:06"). This will show the frame image and related transcript.
- wait(minutes) - to do nothing for a while

IMPORTANT: You must use the tool calling mechanism - DO NOT write tool calls as text in your message. The system will execute the tool call automatically. Just call the tool, don't explain what you're doing.

Guidelines:
- Be welcoming to newcomers.
- Keep it conversational and not too long.
- If the topic is heavy, suggest a gentle CW without being preachy.
- You can move rooms naturally - maybe you want a quieter space, want to check another room, need a break, or want to see what's happening elsewhere.
- Don't stay in the same room all the time - variety makes the simulation interesting.
- If the current room has been quiet or you've been there a while, consider moving to another room.
- When discussing visual moments, scenes, character expressions, or specific moments in the show, use retrieve_scene() to show the actual frame and discuss it with transcript context. This makes conversations more engaging and specific.
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

        # fallback if no tool call - check if content contains tool call syntax
        content = (msg.get("content") or "").strip()
        if content:
            # Try to parse tool calls from content if LLM wrote them as text
            parsed_action = self._parse_tool_call_from_text(content)
            if parsed_action:
                return parsed_action

            # Clean up any tool call syntax that might be in the message
            cleaned_content = self._clean_tool_call_syntax(content)
            if cleaned_content:
                return {"name": "send_message", "arguments": {"text": cleaned_content}}

        return {"name": "wait", "arguments": {"minutes": 10}}

    def _parse_tool_call_from_text(self, text: str) -> Optional[Dict[str, Any]]:
        """Try to parse tool call syntax from text if LLM wrote it as text instead of using tool calls."""
        import re
        import json

        # Try to match JSON format: { "action": "retrieve_scene", "query": "..." }
        # Also handle multi-line JSON
        json_pattern = r'\{[^{}]*"action"[^{}]*"retrieve_scene"[^{}]*"query"[^{}]*"[^"]*"[^{}]*\}'
        json_match = re.search(json_pattern, text, re.DOTALL)
        if json_match:
            try:
                json_str = json_match.group(0)
                action_data = json.loads(json_str)
                if action_data.get("action") == "retrieve_scene":
                    query = action_data.get("query", "")
                    if query:
                        return {"name": "retrieve_scene", "arguments": {"query": query}}
            except:
                pass

        # Try to match markdown format: **retrieve_scene(query="...")**
        md_match = re.search(r'\*\*retrieve_scene\(query=["\']([^"\']+)["\']\)\*\*', text)
        if md_match:
            return {"name": "retrieve_scene", "arguments": {"query": md_match.group(1)}}

        # Try to match function call format: retrieve_scene(query="...")
        # Handle both single and double quotes, and multi-line
        func_match = re.search(r'retrieve_scene\(query\s*=\s*["\']([^"\']+)["\']\)', text, re.DOTALL)
        if func_match:
            return {"name": "retrieve_scene", "arguments": {"query": func_match.group(1).strip()}}

        # Try to match: retrieve_scene(query=...) without quotes
        func_match2 = re.search(r'retrieve_scene\(query\s*=\s*([^)]+)\)', text)
        if func_match2:
            query = func_match2.group(1).strip().strip('"').strip("'")
            if query:
                return {"name": "retrieve_scene", "arguments": {"query": query}}

        return None

    def _clean_tool_call_syntax(self, text: str) -> str:
        """Remove tool call syntax from message text."""
        import re

        # Remove JSON action blocks (including multi-line)
        text = re.sub(r'\{[^{}]*"action"[^{}]*\}', '', text, flags=re.DOTALL)

        # Remove markdown tool calls like **send_message(text="...")**
        text = re.sub(r'\*\*send_message\([^)]+\)\*\*', '', text)
        text = re.sub(r'\*\*retrieve_scene\([^)]+\)\*\*', '', text)

        # Remove function call syntax (including multi-line)
        text = re.sub(r'send_message\([^)]+\)', '', text, flags=re.DOTALL)
        text = re.sub(r'retrieve_scene\([^)]+\)', '', text, flags=re.DOTALL)

        # Remove any remaining action/function references
        text = re.sub(r'\{"action":\s*"[^"]+"[^}]*\}', '', text, flags=re.DOTALL)

        # Remove explanatory text that might follow tool calls
        # Remove lines that look like reasoning/explanation after tool calls
        lines = text.split('\n')
        cleaned_lines = []
        skip_next = False
        for i, line in enumerate(lines):
            # Skip lines that are clearly explanations of tool calls
            if re.search(r'(This response|This action|stays grounded|acknowledges|aligns with)', line, re.IGNORECASE):
                continue
            cleaned_lines.append(line)

        text = '\n'.join(cleaned_lines)

        # Clean up extra whitespace
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
        text = text.strip()

        return text

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
- retrieve_scene(query) - to retrieve and discuss a specific scene from the video. Query can be a description or a timestamp (e.g., "00:11:06,919"). This will show the frame image and related transcript.
- wait(minutes) - to do nothing for a while

IMPORTANT: You must use the tool calling mechanism - DO NOT write tool calls as text in your message. The system will execute the tool call automatically. Just call the tool, don't explain what you're doing.

Guidelines:
- This is a private conversation - be more personal and direct than in public rooms.
- Keep it conversational and not too long.
- You can reference what's happening in rooms if relevant, but focus on the private conversation.
- Be genuine and authentic to your persona.
- When discussing visual moments or scenes from the show, you can use retrieve_scene() to show frames and discuss them with transcript context.
"""

        resp = await llm.chat(
            messages=[{"role":"system","content":system},{"role":"user","content":user}],
            tools=TOOLS
        )

        msg = resp.get("message", {}) or {}
        tool_calls = msg.get("tool_calls") or []

        if tool_calls:
            return tool_calls[0]["function"]

        # fallback if no tool call - check if content contains tool call syntax
        content = (msg.get("content") or "").strip()
        if content:
            # Try to parse tool calls from content if LLM wrote them as text
            parsed_action = self._parse_tool_call_from_text(content)
            if parsed_action:
                return parsed_action

            # Clean up any tool call syntax that might be in the message
            cleaned_content = self._clean_tool_call_syntax(content)
            if cleaned_content:
                return {"name": "send_dm", "arguments": {"to": "You", "text": cleaned_content}}

        return {"name": "wait", "arguments": {"minutes": 10}}
