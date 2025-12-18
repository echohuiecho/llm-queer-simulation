from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Awaitable
import time

@dataclass
class World:
    rooms: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    room_desc: Dict[str, str] = field(default_factory=dict)
    agents: Dict[str, Any] = field(default_factory=dict)  # Agent objects
    dms: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)  # DMs keyed by "user:agent" or "agent:user"
    broadcast: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None

    def ensure_room(self, room: str) -> None:
        if room not in self.rooms:
            self.rooms[room] = []
        if room not in self.room_desc:
            self.room_desc[room] = ""

    async def post_message(self, room: str, sender: str, text: str) -> Dict[str, Any]:
        self.ensure_room(room)
        msg = {"type":"message","room":room,"from":sender,"text":text,"ts":time.time()}
        self.rooms[room].append(msg)
        if self.broadcast:
            await self.broadcast(msg)

        # everyone in same room observes -> memory
        obs = f"[{room}] {sender}: {text}"
        for a in self.agents.values():
            if a.room == room:
                await a.memory.add(obs, ts=msg["ts"])

        return msg

    async def move_agent(self, agent_id: str, new_room: str) -> None:
        self.ensure_room(new_room)
        a = self.agents[agent_id]
        a.room = new_room
        a.room_entered_ts = time.time()  # Update room entry time

        # New random position in the new room
        import random
        a.pos = {"x": random.uniform(0.1, 0.9), "y": random.uniform(0.1, 0.9)}

        if self.broadcast:
            await self.broadcast({
                "type":"presence",
                "agent":agent_id,
                "room":new_room,
                "pos": a.pos,
                "ts":time.time()
            })

    def recent(self, room: str, n: int = 50) -> List[Dict[str, Any]]:
        self.ensure_room(room)
        return self.rooms[room][-n:]

    async def post_dm(self, from_user: str, to_agent: str, text: str) -> Dict[str, Any]:
        """Post a DM message. from_user can be "You" or an agent name."""
        # Create a consistent key for the DM conversation
        # Sort names to ensure same key regardless of direction
        key_parts = sorted([from_user, to_agent])
        dm_key = f"{key_parts[0]}:{key_parts[1]}"

        if dm_key not in self.dms:
            self.dms[dm_key] = []

        msg = {"type":"message","room":f"dm:{to_agent if from_user == 'You' else from_user}","from":from_user,"text":text,"ts":time.time()}
        self.dms[dm_key].append(msg)

        if self.broadcast:
            await self.broadcast(msg)

        # Add to agent memory if it's a message to an agent
        if from_user == "You":
            agent = next((a for a in self.agents.values() if a.profile.name == to_agent), None)
            if agent:
                obs = f"[DM with You] {from_user}: {text}"
                await agent.memory.add(obs, ts=msg["ts"])

        return msg

    def snapshot(self) -> Dict[str, Any]:
        # Convert DM keys to room-like format for frontend
        dm_history = {}
        for key, msgs in self.dms.items():
            # Extract agent name from key (the one that's not "You")
            parts = key.split(":")
            if len(parts) == 2:
                # Since keys are sorted, "You" will always be first if present
                agent_name = parts[1] if parts[0] == "You" else parts[0]
                # Store under "dm:agent_name" for frontend
                dm_history[f"dm:{agent_name}"] = msgs[-50:]

        return {
            "rooms": list(self.rooms.keys()),
            "agents": [
                {
                    "id": a.profile.agent_id,
                    "name": a.profile.name,
                    "room": a.room,
                    "pos": a.pos
                } for a in self.agents.values()
            ],
            "history": {**{r: self.rooms[r][-50:] for r in self.rooms}, **dm_history},
        }
