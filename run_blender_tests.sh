#!/usr/bin/env bash
# Runs the headless Blender verification suite (tests/blender_headless_test.py)
# against the working source file -- this is the only check in the project
# that actually constructs and evaluates the Geometry Nodes graph, so it's
# what catches GN node-type/socket mistakes the stub_bpy mock harness can't.
#
# Usage: ./run_blender_tests.sh [path-to-blender-binary]
# Falls back to $BLENDER_BIN, then whatever "blender" resolves to on PATH.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BLENDER="${1:-${BLENDER_BIN:-blender}}"

if ! command -v "$BLENDER" >/dev/null 2>&1 && [ ! -x "$BLENDER" ]; then
    echo "ERROR: Blender binary not found: $BLENDER" >&2
    echo "Pass it as an argument, or set BLENDER_BIN, e.g.:" >&2
    echo "  ./run_blender_tests.sh /path/to/blender" >&2
    exit 1
fi

"$BLENDER" --background --factory-startup --python "$SCRIPT_DIR/tests/blender_headless_test.py"
