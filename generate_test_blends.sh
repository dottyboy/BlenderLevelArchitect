#!/usr/bin/env bash
# Generates one .blend file per scenario in tests/generate_test_blends.py's
# SCENARIOS list, all on the same fixed seed, into test_blends/ -- plus
# test_blends/testfiles.txt mapping each generic filename (test_01.blend,
# test_02.blend, ...) to the settings it actually used, since encoding that
# many toggles into a filename would be unreadable. Also renders a top-down
# PNG of each scenario into test_blends/Renders/ (test_01.png alongside
# test_01.blend, etc.) -- a scenario's shape can be glanced at without
# opening Blender at all, not just confirmed to generate without erroring.
#
# Usage: ./generate_test_blends.sh [path-to-blender-binary]
# Falls back to $BLENDER_BIN, then whatever "blender" resolves to on PATH.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BLENDER="${1:-${BLENDER_BIN:-blender}}"

# Keep in sync with len(SCENARIOS) in tests/generate_test_blends.py.
NUM_SCENARIOS=21

if ! command -v "$BLENDER" >/dev/null 2>&1 && [ ! -x "$BLENDER" ]; then
    echo "ERROR: Blender binary not found: $BLENDER" >&2
    echo "Pass it as an argument, or set BLENDER_BIN, e.g.:" >&2
    echo "  ./generate_test_blends.sh /path/to/blender" >&2
    exit 1
fi

OUTPUT_DIR="$SCRIPT_DIR/test_blends"
mkdir -p "$OUTPUT_DIR"

echo "# Game Level Architect -- test .blend files, one per scenario, same seed." > "$OUTPUT_DIR/testfiles.txt"
echo "# file  [status]  description" >> "$OUTPUT_DIR/testfiles.txt"

for ((i = 0; i < NUM_SCENARIOS; i++)); do
    echo "=== Scenario $i / $((NUM_SCENARIOS - 1)) ==="
    "$BLENDER" --background --factory-startup \
        --python "$SCRIPT_DIR/tests/generate_test_blends.py" -- "$i"
done

echo ""
echo "Done. $NUM_SCENARIOS .blend files + testfiles.txt written to: $OUTPUT_DIR"
echo "Renders (top-down PNG per scenario) written to: $OUTPUT_DIR/Renders"
