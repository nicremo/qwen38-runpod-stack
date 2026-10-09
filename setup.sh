#!/usr/bin/env bash
# setup.sh - installs the stack for the current user.
#   1. bin/* into ~/.local/bin
#   2. create LaunchAgents with the real home path and load them
#   3. notes for the RunPod CLI, HF token and pi
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "== 1) scripts into ~/.local/bin"
mkdir -p "$HOME/.local/bin" "$HOME/.runpod"
cp "$HERE"/bin/* "$HOME/.local/bin/"
chmod +x "$HOME"/.local/bin/qwen38fast "$HOME"/.local/bin/qwen38pi \
         "$HOME"/.local/bin/qwen38bench "$HOME"/.local/bin/qwen38-proxy \
         "$HOME"/.local/bin/rp "$HOME"/.local/bin/runpod-reaper
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *)
  echo "   NOTE: ~/.local/bin is not on PATH. Add it to your shell config." ;;
esac

echo "== 1b) bootstrap into ~/.local/share/qwen38-runpod-stack"
BOOTSTRAP_DIR="$HOME/.local/share/qwen38-runpod-stack"
mkdir -p "$BOOTSTRAP_DIR"
install -m 700 \
  "$HERE/scripts/bootstrap-sglang-openwebui.sh" \
  "$BOOTSTRAP_DIR/bootstrap-sglang-openwebui.sh"

echo "== 2) LaunchAgents (macOS)"
if [ "$(uname)" = "Darwin" ]; then
  LA="$HOME/Library/LaunchAgents"; mkdir -p "$LA"
  for name in proxy reaper; do
    sed "s|__HOME__|$HOME|g" "$HERE/launchagents/com.qwen38.$name.plist.template" > "$LA/com.qwen38.$name.plist"
    launchctl unload "$LA/com.qwen38.$name.plist" 2>/dev/null || true
    launchctl load "$LA/com.qwen38.$name.plist"
    echo "   loaded: com.qwen38.$name"
  done
else
  echo "   skipped (not macOS). Start the proxy by hand: qwen38-proxy &"
fi

echo "== 3) create the RunPod templates"
echo "   ./create-templates.sh   then export the ids:"
echo "     export QWEN38_TEMPLATE=<id>  QWEN38_TEMPLATE_PI=<id>"

echo "== 4) wire up pi"
echo "   copy the block from pi/models.runpod.json into ~/.pi/agent/models.json."

echo
echo "Requirements: runpodctl logged in, HF token in ~/.cache/huggingface/token,"
echo "RunPod SSH key in ~/.runpod/ssh/runpodctl-ssh-key (for the full stack)."
echo "Then:  qwen38pi   (lean, for pi)   or   qwen38fast   (with OpenWebUI)"
