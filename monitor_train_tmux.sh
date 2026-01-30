#!/usr/bin/env bash
# Advanced tmux-based training monitor with split panes
# Usage: ./monitor_train_tmux.sh
# Creates a tmux session with 4 panes showing different aspects

SESSION_NAME="hydra-monitor"

# Check if tmux is installed
if ! command -v tmux &> /dev/null; then
    echo "❌ tmux is not installed"
    echo "Install with: sudo apt-get install tmux"
    echo ""
    echo "Or use the simple monitor: ./monitor_train.sh"
    exit 1
fi

# Check if session already exists
if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo "Session '$SESSION_NAME' already exists"
    echo "Attaching to existing session..."
    tmux attach-session -t "$SESSION_NAME"
    exit 0
fi

echo "Creating tmux monitoring dashboard..."
echo ""
echo "Layout:"
echo "  ┌─────────────────┬─────────────────┐"
echo "  │  GRPO Training  │  GPU Stats      │"
echo "  ├─────────────────┼─────────────────┤"
echo "  │  Serve Queue    │  API Activity   │"
echo "  └─────────────────┴─────────────────┘"
echo ""

# Find latest logs
GRPO_LOG=$(ls -t /tmp/grpo*.log 2>/dev/null | head -1)
SERVE_LOG=$(ls -t /tmp/scr_serve*.log 2>/dev/null | head -1)
API_LOG="/tmp/atropos_api.log"

# Fallback to placeholder if logs don't exist yet
[[ -z "$GRPO_LOG" ]] && GRPO_LOG="/tmp/grpo_placeholder.log" && touch "$GRPO_LOG"
[[ -z "$SERVE_LOG" ]] && SERVE_LOG="/tmp/serve_placeholder.log" && touch "$SERVE_LOG"
[[ ! -f "$API_LOG" ]] && touch "$API_LOG"

# Create new tmux session with first pane (GRPO log)
tmux new-session -d -s "$SESSION_NAME" -n "Training Monitor"

# Set pane border colors
tmux set-option -g pane-border-style "fg=colour240"
tmux set-option -g pane-active-border-style "fg=colour39"

# Rename first pane and tail GRPO log with color (removed |.* from grep)
tmux send-keys -t "$SESSION_NAME:0.0" "echo -e '\033[1;36m=== GRPO Training Log ===\033[0m' && tail -f '$GRPO_LOG' | grep --color=always -E 'Step|Loss|ETA|ERROR|✓|✗'" C-m

# Split horizontally (right pane) - GPU stats with watch (guard nvidia-smi)
tmux split-window -h -t "$SESSION_NAME:0"
if command -v nvidia-smi &> /dev/null; then
    tmux send-keys -t "$SESSION_NAME:0.1" "echo -e '\033[1;32m=== GPU Monitor ===\033[0m' && watch -n 2 -c 'nvidia-smi --color=always'" C-m
else
    tmux send-keys -t "$SESSION_NAME:0.1" "echo -e '\033[1;33m=== GPU Monitor ===\033[0m' && echo 'nvidia-smi not available' && sleep infinity" C-m
fi

# Split top-left pane vertically (bottom-left) - Serve log (removed |.* from grep)
tmux split-window -v -t "$SESSION_NAME:0.0"
tmux send-keys -t "$SESSION_NAME:0.2" "echo -e '\033[1;33m=== Serve Queue Log ===\033[0m' && tail -f '$SERVE_LOG' | grep --color=always -E 'rollout|batch|task|queue|ERROR'" C-m

# Split bottom-right pane vertically (bottom-right) - API log (removed |.* from grep)
tmux split-window -v -t "$SESSION_NAME:0.1"
tmux send-keys -t "$SESSION_NAME:0.3" "echo -e '\033[1;35m=== API Activity Log ===\033[0m' && tail -f '$API_LOG' | grep --color=always -E 'POST|GET|200|404|500|ERROR'" C-m

# Resize panes to be roughly equal
tmux select-layout -t "$SESSION_NAME:0" tiled

# Set status bar
tmux set-option -g status-style "bg=colour234,fg=colour39"
tmux set-option -g status-left-length 50
tmux set-option -g status-left "#[fg=colour39,bold] HYDRA Training Monitor #[fg=colour240]│ "
tmux set-option -g status-right "#[fg=colour240]│ #[fg=colour39]%Y-%m-%d %H:%M:%S "

# Add helpful key bindings info to status
tmux set-option -g status-right-length 80

# Select first pane
tmux select-pane -t "$SESSION_NAME:0.0"

echo "✓ Dashboard created!"
echo ""
echo "Tmux commands:"
echo "  Switch panes:    Ctrl+b then arrow keys"
echo "  Zoom pane:       Ctrl+b then z (toggle)"
echo "  Scroll mode:     Ctrl+b then [ (q to exit)"
echo "  Detach:          Ctrl+b then d"
echo "  Kill session:    Ctrl+b then : then type 'kill-session'"
echo ""
echo "Attaching to session..."
sleep 2

# Attach to the session
tmux attach-session -t "$SESSION_NAME"
