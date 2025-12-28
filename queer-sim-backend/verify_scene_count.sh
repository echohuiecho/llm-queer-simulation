#!/bin/bash
# Script to verify scene count is consistent and progressing correctly

echo "=========================================="
echo "Storyline Scene Count Verification"
echo "=========================================="
echo ""

STORYLINE_DIR="output/stylish-black-masc"

if [ ! -f "$STORYLINE_DIR/current.json" ]; then
    echo "❌ No current.json found. Storyline not yet created."
    exit 0
fi

# Count scenes in current.json
DISK_SCENES=$(grep -c '"scene_number"' "$STORYLINE_DIR/current.json")
DISK_VERSION=$(grep '"version"' "$STORYLINE_DIR/current.json" | tail -1 | grep -o '[0-9]\+')

echo "📁 Disk State:"
echo "   Version: v$DISK_VERSION"
echo "   Scenes:  $DISK_SCENES"
echo ""

# Show recent version history
echo "📜 Recent Version History (last 5):"
if [ -f "$STORYLINE_DIR/updates.jsonl" ]; then
    tail -5 "$STORYLINE_DIR/updates.jsonl" | while read line; do
        version=$(echo "$line" | grep -o '"version": [0-9]\+' | grep -o '[0-9]\+')
        scene_count=$(echo "$line" | grep -o '"scene_count": [0-9]\+' | grep -o '[0-9]\+')
        update_type=$(echo "$line" | grep -o '"update_type": "[^"]\+"' | cut -d'"' -f4)
        echo "   v$version: $scene_count scenes ($update_type)"
    done
else
    echo "   (no updates.jsonl yet)"
fi
echo ""

# Check for rollbacks
echo "🔍 Checking for Rollbacks:"
if [ -f "$STORYLINE_DIR/updates.jsonl" ]; then
    prev_count=0
    rollback_detected=0
    while read line; do
        scene_count=$(echo "$line" | grep -o '"scene_count": [0-9]\+' | grep -o '[0-9]\+')
        if [ "$scene_count" -lt "$prev_count" ]; then
            echo "   ⚠️  ROLLBACK DETECTED: $prev_count -> $scene_count"
            rollback_detected=1
        fi
        prev_count=$scene_count
    done < "$STORYLINE_DIR/updates.jsonl"

    if [ $rollback_detected -eq 0 ]; then
        echo "   ✅ No rollbacks detected!"
    fi
else
    echo "   (no history to check)"
fi
echo ""

# Progress to Episode 1 completion
EP1_TARGET=12
REMAINING=$((EP1_TARGET - DISK_SCENES))
if [ $DISK_SCENES -ge $EP1_TARGET ]; then
    echo "🎉 Episode 1 Complete! ($DISK_SCENES/$EP1_TARGET scenes)"
elif [ $DISK_SCENES -gt 0 ]; then
    echo "📈 Episode 1 Progress: $DISK_SCENES/$EP1_TARGET scenes"
    echo "   Need $REMAINING more scene(s)"
else
    echo "🆕 Ready to start Episode 1 (0/$EP1_TARGET scenes)"
fi
echo ""

# Check if corrupted files exist
if [ -d "$STORYLINE_DIR/corrupted" ]; then
    CORRUPTED_COUNT=$(ls "$STORYLINE_DIR/corrupted"/*.json 2>/dev/null | wc -l)
    if [ $CORRUPTED_COUNT -gt 0 ]; then
        echo "📦 Archived corrupted files: $CORRUPTED_COUNT"
    fi
fi

echo "=========================================="
echo "✅ Verification complete!"
echo "=========================================="

