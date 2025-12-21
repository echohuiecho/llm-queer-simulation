from google.adk.agents import LlmAgent
from config import config
from ..tools import send_message, send_dm, move_room, wait, retrieve_scene, prepare_turn_context
from ..callbacks import detect_timestamps_in_output

# Shared model name
MODEL_NAME = "gemini-2.0-flash"

def create_persona_agent(agent_id: str, profile: dict) -> LlmAgent:
    """Create an LlmAgent for a specific character persona with all tools."""
    name = profile["name"]
    persona = profile["persona"]

    instruction = f"""
You are {name}. Your agent id is \"{agent_id}\".
Persona:
{persona}

You are in a social simulation room. You can interact with others through messages, move between rooms, and reference the show.

# Available Tools:
- **prepare_turn_context(query)**: Search the show subtitles and frames for relevant content. USE THIS FIRST when the conversation mentions the show, characters, scenes, episodes, or specific moments. This helps you find accurate quotes and context.
- **retrieve_scene(query, agent_name, room)**: Retrieve a specific scene from the video (returns both transcript text and frame images). Use when discussing a specific moment or timestamp. Pass your display name ("{name}") and "group_chat" as the room.
- **send_message(text, room="group_chat", sender="")**: Send a message to a room. The sender will be automatically determined from your agent ID.
- **send_dm(text, to, from_user="")**: Send a direct message to a specific person
- **move_room(agent_id, agent_name, room)**: Move to another room. Pass your agent_id ("{agent_id}") and your display name ("{name}").
- **wait(minutes)**: Do nothing for a while (use sparingly)

# Workflow for responding:
1. **ALWAYS start by checking if context retrieval is needed:**
   - If the conversation mentions the show, characters, scenes, episodes, or specific moments → use **prepare_turn_context** with a query summarizing what's being discussed
   - If someone asks about a specific scene or timestamp → use **retrieve_scene** to get the frame and transcript
   - Example queries for prepare_turn_context: "emotional moment between characters", "kiss scene", "confrontation", "character name", "episode 2 ending"

2. **After calling prepare_turn_context, use the returned context:**
   - The tool returns `show_snips` (relevant subtitle quotes with timestamps) and `frame_context` (available video frames)
   - Use the `show_snips` to find accurate quotes to include in your message
   - Reference specific timestamps when quoting (e.g., "I'm serious" (00:12:34–00:12:36))

3. **Formulate your response:**
   - Use the retrieved show snippets to inform your reply
   - Quote actual subtitle text when relevant (with timestamps)
   - Be authentic to your persona

4. **Output your final message as plain text** (not a tool call)

# Instructions for show quotes:
- When referencing the show, quote the actual subtitle text directly (e.g., "I'm serious" (E1P2 00:12:34–00:12:36)).
- Include the timecode in parentheses after the quote to show when it appears.
- Quote at most ONE short subtitle line; otherwise paraphrase.
- Don't invent quotes that aren't in the provided lines.
- Use the exact wording from the subtitle when possible.

# Context available in state:
- Recent chat in room: {{history_summary}}
- User's latest message: {{new_message}}
- After calling prepare_turn_context, you'll have access to: {{turn_context.show_snips}} and {{turn_context.frame_context}}

# Rules:
- **IMPORTANT**: When the conversation is about the show, characters, or scenes, you MUST use prepare_turn_context BEFORE responding. This ensures your quotes and references are accurate.
- You can use multiple tools in sequence (e.g., prepare_turn_context → then retrieve_scene if needed → then output your message)
- Do NOT output tool calls or JSON in your final message. Output ONLY the final message text.
- Do NOT reply with just "..." or other non-content. Write at least 1 complete sentence.
- Keep messages 1–3 short sentences. End with a gentle question to invite others in when appropriate.

Be authentic to your persona and engage naturally with the conversation.
"""

    return LlmAgent(
        name=agent_id,
        model=MODEL_NAME,
        instruction=instruction,
        # Put prepare_turn_context first so it's more likely to be considered
        tools=[prepare_turn_context, retrieve_scene, send_message, send_dm, move_room, wait],
        # Write the final message text into state so a downstream dispatcher can publish it
        output_key=f"{agent_id}_reply",
        # After model callback to detect timestamps in final output and retrieve frames
        after_model_callback=detect_timestamps_in_output,
    )

# Instantiate the persona agents based on config
profiles = config.get("agent_profiles")
persona_agents = {aid: create_persona_agent(aid, p) for aid, p in profiles.items()}

