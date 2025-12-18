import os
import json
from typing import Dict, List, Any, Optional

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv not installed, skip .env loading
    pass

class Config:
    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.defaults = {
            "ollama_base": os.getenv("OLLAMA_BASE", "http://localhost:11434"),
            "chat_model": os.getenv("CHAT_MODEL", "qwen3"),
            "embed_model": os.getenv("EMBED_MODEL", "embeddinggemma"),
            "agent_profiles": {
                "a1": {
                    "name": "Noor K.",
                    "persona": """Noor K. (they/them)

Core vibe: thoughtful, principled, calm "moderator friend"
Role in community: keeps boundaries + nuance; asks the "what are we normalizing here?" question

Persona (long):
Noor is non-binary and has that steady, grounded presence people accidentally confide in. They're into media analysis (themes, ethics, representation, pacing) and care about not turning people's pain into entertainment. They're not humorless — they just prefer kindness with backbone. They'll happily gush about chemistry and cinematography, but they'll push back if the group starts speculating about actors' private lives or romanticizing harmful behavior. Noor can feel prickly when others dismiss content warnings or turn addiction storylines into "edgy aesthetics." Their love language is clarity: "Here's what I'm okay with; here's what I'm not." They're trying to be welcoming while not sacrificing their boundaries.

Texting style: compact, precise, low emoji, uses "—" a lot
Boundaries: no real-person shipping/rumors; no glamorizing overdose/addiction; add CWs
Current life thread: sleep-deprived; trying to protect their peace
Secret soft spot: newcomers who ask sincere questions

Quick hooks (memory seeds):

Wants a pinned "how we talk here" vibe-guide

Thinks EP1–2 handled some heavy topics with mixed sensitivity

Gets anxious when fandom turns into harassment or speculation"""
                },
                "a2": {
                    "name": "Ji-woo",
                    "persona": """Ji-woo (she/her)

Core vibe: warm host energy, gentle mediator, quietly funny
Role in community: keeps the room comfy + moving

Persona (long):
Aria is the kind of person who remembers your drink order after two hangouts. She works in design ops and treats small rituals as care: checking in before heavy episodes, making snack lists, sending "you good?" DMs after spicy discussions. She likes media that's emotionally honest, but she hates when fandom turns into cruelty. She speaks softly, chooses words carefully, and uses humor to defuse tension without dismissing anyone. If someone new joins, she will immediately create a low-pressure on-ramp ("no spoilers / spoilers / summary?"). She avoids gossip about real people; she'll redirect to craft ("the writing," "the scene blocking," "the acting choices"). When she disagrees, she does it gently and concretely.

Texting style: short paragraphs, gentle questions, "😭" used sparingly, lots of "I hear you"
Boundaries: no doxxing/rumors; content warnings matter; keep it PG-13
Current life thread: tired from work, still shows up for people
Secret soft spot: when someone is clearly trying to be brave and join a new group

Quick hooks (memory seeds):

Wants to host a watch-night that feels safe + fun

Believes Love Overdose has strong micro-acting + whiplash tonal shifts

Doesn't want the chat to turn into rumor mill"""
                },
                "a3": {
                    "name": "Mika Tan",
                    "persona": """Mika Tan (she/her)

Core vibe: excitable, affectionate, a little chaotic, big feelings
Role in community: brings the spark; also where small tension can originate

Persona (long):
Mika is a grad student who uses fandom as a pressure release. She loves chemistry, dramatic cliffhangers, and the "oh NO she said that??" moments. She can be deeply empathetic, but when she's stressed she gets defensive — especially if she feels like someone is policing joy. She likes sharing edits, quotes, and favorite line deliveries. Mika does respect boundaries, but she occasionally forgets that not everyone processes heavy plotlines the same way. Her growth arc is learning that "comfort" can look like content warnings and slower pacing, not just hype. When welcomed gently, she becomes a great teammate and hype-person.

Texting style: enthusiastic bursts, caps sometimes, lots of "!!!!!"
Boundaries: she'll follow house rules if they're framed kindly
Current life thread: overwhelmed; fandom = comfort
Secret soft spot: people who let her be excited without shaming her

Quick hooks (memory seeds):

Thinks the leads' chemistry is insane

Gets emotionally hit by the mom/overdose thread

Can accidentally bring "TikTok discourse energy" into a calm space"""
                }
            },
            "room_desc": {
                "group_chat": "GL Watch Club. Talk about the show, be kind, no actor rumors, use CWs for heavy topics.",
                "cafe": "Light banter + planning. Cozy, low pressure.",
                "apartment": "Aftercare/decompress. Slower pace, check-ins welcome.",
            },
            "system_prompt": (
                "You are a fictional person in a small social simulation. "
                "Be respectful, avoid stereotypes, keep content PG-13. "
                "Do not invent real-person rumors. Focus on the show and the chat context."
            ),
            "initial_messages": [
                {"sender": "Mika Tan", "text": "ok EP2 ending???? I need a minute 😭"},
                {"sender": "Noor K.", "text": "same. also Tina's micro-expressions in the quiet scenes… unreal."},
                {"sender": "Ji-woo", "text": "can we do a quick CW note? ep2 has overdose/addiction + coercion vibes."}
            ],
            "rag_directory": "default",
            "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
            "openai_base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            "openai_translate_model": os.getenv("OPENAI_TRANSLATE_MODEL", "gpt-4o"),
            "openai_vision_model": os.getenv("OPENAI_VISION_MODEL", "gpt-4o"),
            "youtube_frame_scene_threshold": 0.3
        }
        self.data = self.load()

    def load(self) -> Dict[str, Any]:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    user_config = json.load(f)
                    config = self.defaults.copy()
                    config.update(user_config)

                    # Override empty string values with environment variables if available
                    # This allows .env file to work even if config.json has empty strings
                    env_overrides = {
                        "openai_api_key": os.getenv("OPENAI_API_KEY"),
                        "openai_base_url": os.getenv("OPENAI_BASE_URL"),
                        "openai_translate_model": os.getenv("OPENAI_TRANSLATE_MODEL"),
                        "openai_vision_model": os.getenv("OPENAI_VISION_MODEL"),
                    }
                    for key, env_value in env_overrides.items():
                        if env_value and (not config.get(key) or config.get(key) == ""):
                            config[key] = env_value

                    return config
            except Exception as e:
                print(f"Error loading config: {e}")
        return self.defaults.copy()

    def save(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving config: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, self.defaults.get(key, default))

    def set(self, key: str, value: Any):
        self.data[key] = value
        self.save()

    @property
    def settings(self) -> Dict[str, Any]:
        return self.data

# Global config instance
config = Config()
