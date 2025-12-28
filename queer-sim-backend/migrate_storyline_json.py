"""Migration script to fix existing storyline JSON files.

This script:
1. Adds episode numbers to scenes that are missing them
2. Reconstructs episode metadata from existing scenes
3. Ensures schema consistency
"""

import json
import sys
from pathlib import Path


def migrate_storyline_json(file_path: Path) -> bool:
    """Migrate a single storyline JSON file.

    Args:
        file_path: Path to JSON file

    Returns:
        True if migration was successful, False otherwise
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            print(f"  Error: {file_path} is not a JSON object")
            return False

        scenes = data.get("scenes", [])
        if not isinstance(scenes, list):
            print(f"  Error: {file_path} has invalid scenes field")
            return False

        changes_made = False

        # Fix scenes missing episode numbers
        for scene in scenes:
            if not isinstance(scene, dict):
                continue

            if "episode" not in scene or scene.get("episode") == 0:
                scene["episode"] = 1
                changes_made = True
                print(f"  Fixed: Added episode=1 to scene {scene.get('scene_number', '?')}")

        # Reconstruct episode metadata
        if "meta" not in data:
            data["meta"] = {}

        meta = data["meta"]
        if not isinstance(meta, dict):
            meta = {}
            data["meta"] = meta

        if "episodes" not in meta:
            meta["episodes"] = {}

        episodes_meta = meta["episodes"]
        if not isinstance(episodes_meta, dict):
            episodes_meta = {}
            meta["episodes"] = episodes_meta

        # Count scenes per episode and mark complete if they have good structure
        episode_scene_counts = {}
        for scene in scenes:
            if isinstance(scene, dict):
                ep = int(scene.get("episode") or 0)
                if ep > 0:
                    episode_scene_counts[ep] = episode_scene_counts.get(ep, 0) + 1

        # Update metadata for each episode
        for ep_num, count in episode_scene_counts.items():
            ep_key = str(ep_num)
            if ep_key not in episodes_meta:
                episodes_meta[ep_key] = {}

            if not isinstance(episodes_meta[ep_key], dict):
                episodes_meta[ep_key] = {}

            # If episode has scenes but no completion status, leave it incomplete
            # (Don't auto-complete, let agents decide)
            if "complete" not in episodes_meta[ep_key]:
                episodes_meta[ep_key]["complete"] = False
                changes_made = True

        if changes_made:
            # Backup original file
            backup_path = file_path.with_suffix(file_path.suffix + ".backup")
            with open(backup_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"  Created backup: {backup_path}")

            # Write migrated file
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"  Migrated: {file_path}")
            return True
        else:
            print(f"  No changes needed: {file_path}")
            return True

    except Exception as e:
        print(f"  Error migrating {file_path}: {e}")
        return False


def main():
    """Run migration on all storyline JSON files."""
    # Find all JSON files in output directory
    output_dir = Path("output")
    if not output_dir.exists():
        print(f"Output directory not found: {output_dir}")
        return

    json_files = []
    for storyline_dir in output_dir.iterdir():
        if storyline_dir.is_dir():
            # Check for current.json or v*.json files
            for pattern in ["current.json", "v*.json"]:
                json_files.extend(storyline_dir.glob(pattern))

    # Also check the specific file mentioned in the issue
    specific_file = Path("output/stylish-black-masc/251222-v1-conversation-response.json")
    if specific_file.exists() and specific_file not in json_files:
        json_files.append(specific_file)

    if not json_files:
        print("No JSON files found to migrate")
        return

    print(f"Found {len(json_files)} JSON file(s) to migrate")
    print()

    success_count = 0
    for json_file in json_files:
        print(f"Migrating: {json_file}")
        if migrate_storyline_json(json_file):
            success_count += 1
        print()

    print(f"Migration complete: {success_count}/{len(json_files)} files migrated successfully")


if __name__ == "__main__":
    main()

