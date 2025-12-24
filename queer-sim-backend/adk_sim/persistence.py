"""Persistent file storage for storyline state.

This module handles saving and loading storyline JSON to/from disk,
providing durability across server restarts and recovery from failures.
"""

import json
import time
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime


class StorylinePersistence:
    """Manages persistent storage of storyline state to disk."""

    def __init__(self, base_dir: str = "output"):
        """Initialize persistence with base directory.

        Args:
            base_dir: Base directory for storing storyline files (relative to backend root)
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_storyline_dir(self, storyline_dir: str) -> Path:
        """Get the full path for a storyline directory.

        Args:
            storyline_dir: Storyline directory name (e.g., 'stylish-black-masc')

        Returns:
            Path to the storyline directory
        """
        if not storyline_dir or storyline_dir == "default":
            storyline_dir = "default"
        path = self.base_dir / storyline_dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_storyline(
        self,
        storyline_dir: str,
        storyline: Dict[str, Any],
        version: int,
        update_type: str = "update"
    ) -> Dict[str, Any]:
        """Save storyline JSON to disk after every update.

        Saves:
        - current.json: Latest version (always overwritten)
        - v{version}.json: Versioned backup
        - updates.jsonl: Append-only log of all updates

        Args:
            storyline_dir: Storyline directory name
            storyline: Storyline dictionary to save
            version: Version number
            update_type: Type of update (e.g., 'plan', 'refine', 'add_scene', 'complete_episode')

        Returns:
            Dict with save status and file paths
        """
        try:
            story_path = self.get_storyline_dir(storyline_dir)

            # Ensure meta is present and up to date
            if "meta" not in storyline:
                storyline["meta"] = {}
            storyline["meta"]["version"] = version
            storyline["meta"]["updated_ts"] = time.time()

            # Save current.json (latest version)
            current_file = story_path / "current.json"
            with open(current_file, "w", encoding="utf-8") as f:
                json.dump(storyline, f, indent=2, ensure_ascii=False)

            # Save versioned backup
            versioned_file = story_path / f"v{version}.json"
            with open(versioned_file, "w", encoding="utf-8") as f:
                json.dump(storyline, f, indent=2, ensure_ascii=False)

            # Append to update log
            log_entry = {
                "timestamp": time.time(),
                "datetime": datetime.now().isoformat(),
                "version": version,
                "update_type": update_type,
                "scene_count": len(storyline.get("scenes", [])),
                "episodes": self._extract_episode_info(storyline),
            }
            self.append_update_log(storyline_dir, log_entry)

            print(f"[PERSISTENCE] Saved storyline v{version} to {current_file} and {versioned_file}")

            return {
                "status": "ok",
                "current_file": str(current_file),
                "versioned_file": str(versioned_file),
                "version": version
            }
        except Exception as e:
            print(f"[PERSISTENCE] Error saving storyline: {e}")
            import traceback
            traceback.print_exc()
            return {
                "status": "error",
                "error": str(e)
            }

    def load_latest_storyline(self, storyline_dir: str) -> Optional[Dict[str, Any]]:
        """Load most recent storyline from disk.

        Tries to load current.json first, then falls back to highest version number.

        Args:
            storyline_dir: Storyline directory name

        Returns:
            Storyline dictionary or None if not found
        """
        try:
            story_path = self.get_storyline_dir(storyline_dir)

            # Try current.json first
            current_file = story_path / "current.json"
            if current_file.exists():
                with open(current_file, "r", encoding="utf-8") as f:
                    return json.load(f)

            # Fallback: find highest version number
            version_files = list(story_path.glob("v*.json"))
            if version_files:
                # Sort by version number (extract from filename)
                def get_version(f: Path) -> int:
                    try:
                        return int(f.stem[1:])  # Remove 'v' prefix
                    except ValueError:
                        return 0

                latest_file = max(version_files, key=get_version)
                with open(latest_file, "r", encoding="utf-8") as f:
                    return json.load(f)

            return None
        except Exception as e:
            print(f"[PERSISTENCE] Error loading storyline: {e}")
            return None

    def append_update_log(self, storyline_dir: str, log_entry: Dict[str, Any]) -> None:
        """Append to updates.jsonl for audit trail.

        Args:
            storyline_dir: Storyline directory name
            log_entry: Dictionary to append as JSON line
        """
        try:
            story_path = self.get_storyline_dir(storyline_dir)
            log_file = story_path / "updates.jsonl"

            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[PERSISTENCE] Error appending to update log: {e}")

    def _extract_episode_info(self, storyline: Dict[str, Any]) -> Dict[str, Any]:
        """Extract episode information from storyline.

        Args:
            storyline: Storyline dictionary

        Returns:
            Dict with episode counts and completion status
        """
        scenes = storyline.get("scenes", [])
        episodes = {}

        for scene in scenes:
            if not isinstance(scene, dict):
                continue
            ep_num = scene.get("episode", 0)
            if ep_num > 0:
                ep_key = str(ep_num)
                if ep_key not in episodes:
                    episodes[ep_key] = {"scene_count": 0, "complete": False}
                episodes[ep_key]["scene_count"] += 1

        # Check completion status from meta
        meta = storyline.get("meta", {})
        episodes_meta = meta.get("episodes", {})
        if isinstance(episodes_meta, dict):
            for ep_key, ep_info in episodes_meta.items():
                if ep_key in episodes and isinstance(ep_info, dict):
                    episodes[ep_key]["complete"] = ep_info.get("complete", False)

        return episodes

    def get_update_history(self, storyline_dir: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent update history from log file.

        Args:
            storyline_dir: Storyline directory name
            limit: Maximum number of entries to return

        Returns:
            List of update log entries (most recent first)
        """
        try:
            story_path = self.get_storyline_dir(storyline_dir)
            log_file = story_path / "updates.jsonl"

            if not log_file.exists():
                return []

            entries = []
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue

            # Return most recent first
            entries.reverse()
            return entries[:limit]
        except Exception as e:
            print(f"[PERSISTENCE] Error reading update history: {e}")
            return []


# Global instance
_storyline_persistence: Optional[StorylinePersistence] = None


def get_storyline_persistence(base_dir: str = "output") -> StorylinePersistence:
    """Get or create global storyline persistence instance.

    Args:
        base_dir: Base directory for storage (only used on first call)

    Returns:
        StorylinePersistence instance
    """
    global _storyline_persistence
    if _storyline_persistence is None:
        _storyline_persistence = StorylinePersistence(base_dir=base_dir)
    return _storyline_persistence


def set_storyline_persistence(persistence: StorylinePersistence) -> None:
    """Set the global persistence instance (for testing).

    Args:
        persistence: StorylinePersistence instance
    """
    global _storyline_persistence
    _storyline_persistence = persistence

