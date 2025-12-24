"""Validation functions for storyline state.

This module provides validation checks to ensure storyline state consistency
and catch data corruption issues early.
"""

from typing import Dict, Any, List


def validate_storyline_state(state: Dict[str, Any]) -> List[str]:
    """Return list of validation errors.

    Args:
        state: Current state dictionary

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []
    storyline = state.get("current_storyline", {})

    if not isinstance(storyline, dict):
        return ["current_storyline is not a dictionary"]

    if not storyline:
        # Empty storyline is valid (not created yet)
        return []

    # Check all scenes have episode numbers
    scenes = storyline.get("scenes", [])
    if not isinstance(scenes, list):
        errors.append("scenes is not a list")
        return errors

    seen_keys = set()
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            errors.append(f"scenes[{i}] is not a dictionary")
            continue

        ep = scene.get("episode")
        sn = scene.get("scene_number")

        if ep is None or ep == 0:
            errors.append(f"scenes[{i}] missing or invalid episode number")

        if sn is None or sn == 0:
            errors.append(f"scenes[{i}] missing or invalid scene_number")

        if ep is not None and sn is not None:
            key = (int(ep), int(sn))
            if key in seen_keys:
                errors.append(f"Duplicate scene: episode {ep}, scene {sn}")
            seen_keys.add(key)

    # Check episode metadata matches actual scenes
    meta = storyline.get("meta", {})
    if isinstance(meta, dict):
        episodes_meta = meta.get("episodes", {})
        if isinstance(episodes_meta, dict):
            # Count scenes per episode
            episode_scene_counts = {}
            for scene in scenes:
                if isinstance(scene, dict):
                    ep = int(scene.get("episode") or 0)
                    if ep > 0:
                        episode_scene_counts[ep] = episode_scene_counts.get(ep, 0) + 1

            # Check metadata consistency
            for ep_key, ep_info in episodes_meta.items():
                try:
                    ep_num = int(ep_key)
                    if ep_num not in episode_scene_counts:
                        errors.append(f"Episode {ep_num} marked in metadata but has no scenes")
                    elif isinstance(ep_info, dict) and ep_info.get("complete"):
                        # Completed episodes should have at least 1 scene
                        if episode_scene_counts[ep_num] == 0:
                            errors.append(f"Episode {ep_num} marked complete but has no scenes")
                except ValueError:
                    errors.append(f"Invalid episode key in metadata: {ep_key}")

    # Check version consistency
    version = state.get("storyline_version", 0)
    meta_version = meta.get("version", 0) if isinstance(meta, dict) else 0
    if version != meta_version:
        errors.append(f"Version mismatch: state has {version}, meta has {meta_version}")

    # Check characters
    characters = storyline.get("characters", [])
    if not isinstance(characters, list):
        errors.append("characters is not a list")
    elif len(characters) != 2:
        errors.append(f"Expected exactly 2 characters, found {len(characters)}")
    else:
        for i, char in enumerate(characters):
            if not isinstance(char, dict):
                errors.append(f"characters[{i}] is not a dictionary")
                continue
            if not char.get("name"):
                errors.append(f"characters[{i}] missing name")
            if not char.get("description"):
                errors.append(f"characters[{i}] missing description")

    return errors

