#!/usr/bin/env bash
# Builds the installable Blender add-on package for Game Level Architect.
#
# Copies the working source file + Textures/ + LICENSE into a proper
# add-on package folder (game_level_architect/__init__.py, matching what
# Blender's "Install from Disk" expects), then zips it. Run from anywhere;
# paths are resolved relative to this script's own location.
#
# Usage: ./build_package.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_PY="$SCRIPT_DIR/levelArchitect_v2.py"
SRC_TEXTURES="$SCRIPT_DIR/Textures"
SRC_LICENSE="$SCRIPT_DIR/LICENSE"
SRC_CHANGELOG="$SCRIPT_DIR/CHANGELOG.md"
SRC_README="$SCRIPT_DIR/README.md"
SRC_SCREENSHOT="$SCRIPT_DIR/docs/screenshot.png"

DIST_DIR="$SCRIPT_DIR/dist"
PKG_NAME="game_level_architect"
PKG_DIR="$DIST_DIR/$PKG_NAME"
ZIP_PATH="$DIST_DIR/$PKG_NAME.zip"

for required in "$SRC_PY" "$SRC_TEXTURES" "$SRC_LICENSE" "$SRC_CHANGELOG" "$SRC_README" "$SRC_SCREENSHOT"; do
    if [ ! -e "$required" ]; then
        echo "ERROR: missing $required" >&2
        exit 1
    fi
done

echo "Building package from: $SRC_PY"

# Clean rebuild -- avoids stale files (e.g. a texture removed from Textures/
# since the last build) lingering in the package.
rm -rf "$PKG_DIR" "$ZIP_PATH"
mkdir -p "$PKG_DIR/Textures"

cp "$SRC_PY" "$PKG_DIR/__init__.py"
cp "$SRC_LICENSE" "$PKG_DIR/LICENSE"
cp "$SRC_TEXTURES"/*.png "$PKG_DIR/Textures/"

# Not part of the installable package itself -- copied alongside the zip in
# dist/ as release-page assets. README.md used to be maintained by hand here
# and quietly drifted out of sync with the real one (missing the showcase
# video + all 4 tutorial sections added to the root README since) -- always
# copied fresh now, same as CHANGELOG.md/screenshot.png, so it can't drift
# again.
cp "$SRC_README" "$DIST_DIR/README.md"
# The root README's relative links/video embeds (e.g. "docs/showcase.mp4")
# are correct from the REPO ROOT, where README.md itself lives -- GitHub
# resolves relative img/video src paths against the file's own location, so
# copied verbatim into dist/ (one directory down) they'd point at a
# nonexistent dist/docs/... and silently render as broken. Rewriting every
# "docs/" reference to "../docs/" makes them resolve correctly from dist/'s
# actual location instead. screenshot.png is untouched -- it already has its
# own local copy directly in dist/ (below), so its bare relative reference
# is already correct as-is for this file's new location.
# Only the link TARGETS need rewriting -- "(docs/..." for a markdown link
# href, `src="docs/...` for the <video> embed -- not the "[docs/..." visible
# link text, which should keep reading as the real repo-root-relative path.
sed -i -e 's#(docs/#(../docs/#g' -e 's#src="docs/#src="../docs/#g' "$DIST_DIR/README.md"
cp "$SRC_CHANGELOG" "$DIST_DIR/CHANGELOG.md"
cp "$SRC_SCREENSHOT" "$DIST_DIR/screenshot.png"

# Sanity checks -- catch a broken source file before it ever reaches a
# tester instead of shipping something that fails to install.
python3 -m py_compile "$PKG_DIR/__init__.py"
python3 - "$PKG_DIR/__init__.py" <<'PYEOF'
import ast
import sys

path = sys.argv[1]
tree = ast.parse(open(path).read(), filename=path)
top_level_names = {
    node.name for node in tree.body
    if isinstance(node, ast.FunctionDef)
}
assert "register" in top_level_names, "register() not found"
assert "unregister" in top_level_names, "unregister() not found"
assert any(
    isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "bl_info" for t in node.targets
    )
    for node in tree.body
), "bl_info not found"
print("register()/unregister()/bl_info: present")
PYEOF

rm -rf "$PKG_DIR/__pycache__"

texture_count=$(find "$PKG_DIR/Textures" -name '*.png' | wc -l | tr -d ' ')
echo "Bundled $texture_count texture(s)"

(cd "$DIST_DIR" && zip -rq "$PKG_NAME.zip" "$PKG_NAME" -x '*__pycache__*' -x '*.pyc')

version=$(python3 -c "
import ast
tree = ast.parse(open('$PKG_DIR/__init__.py').read())
for node in tree.body:
    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'bl_info' for t in node.targets):
        info = ast.literal_eval(node.value)
        print('.'.join(str(n) for n in info['version']))
        break
")

size=$(du -h "$ZIP_PATH" | cut -f1)
echo ""
echo "Built: $ZIP_PATH ($size)"
echo "Version: $version"
