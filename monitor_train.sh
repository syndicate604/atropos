#!/usr/bin/env bash
# Consolidated training monitor - shows all important logs and stats in one view
# Usage: ./monitor_train.sh [refresh_seconds]

REFRESH="${1:-3}"  # Default 3 second refresh

# ANSI colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color
BOLD='\033[1m'

clear

while true; do
    # Save cursor position and clear screen
    clear
    echo -e "${BOLD}${CYAN}╔════════════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${CYAN}║                    HYDRA TRAINING MONITOR                                      ║${NC}"
    echo -e "${BOLD}${CYAN}║                    $(date '+%Y-%m-%d %H:%M:%S')                                           ║${NC}"
    echo -e "${BOLD}${CYAN}╚════════════════════════════════════════════════════════════════════════════════╝${NC}"
    echo ""

    # ==================== GPU STATUS ====================
    echo -e "${BOLD}${MAGENTA}[1] GPU STATUS${NC}"
    echo -e "${CYAN}────────────────────────────────────────────────────────────────────────────────${NC}"
    if command -v nvidia-smi &> /dev/null; then
        nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu \
            --format=csv,noheader,nounits | awk -F',' '{
            printf "  GPU %s: %s\n", $1, $2
            printf "    Utilization: %3d%%  Memory: %5d/%5d MB  Temp: %3d°C\n", $3, $4, $5, $6
        }'
    else
        echo -e "  ${YELLOW}nvidia-smi not available${NC}"
    fi
    echo ""

    # ==================== PROCESS STATUS ====================
    echo -e "${BOLD}${MAGENTA}[2] PROCESS STATUS${NC}"
    echo -e "${CYAN}────────────────────────────────────────────────────────────────────────────────${NC}"

    # Check GRPO (use newest PID if multiple)
    GRPO_COUNT=$(pgrep -f "example_trainer/grpo.py" | wc -l)
    if [[ $GRPO_COUNT -gt 0 ]]; then
        GRPO_PID=$(pgrep -n -f "example_trainer/grpo.py")
        GRPO_MEM=$(ps -p $GRPO_PID -o rss= 2>/dev/null | awk '{printf "%.1f", $1/1024/1024}')
        if [[ $GRPO_COUNT -gt 1 ]]; then
            echo -e "  ${YELLOW}⚠${NC} GRPO:   PID ${GRPO_PID} (${GRPO_MEM}GB RAM) ${YELLOW}[${GRPO_COUNT} processes running!]${NC}"
        else
            echo -e "  ${GREEN}✓${NC} GRPO:   PID ${GRPO_PID} (${GRPO_MEM}GB RAM)"
        fi
    else
        echo -e "  ${RED}✗${NC} GRPO:   Not running"
    fi

    # Check Serve (use newest PID if multiple)
    if pgrep -n -f "secure_code_review_env.py serve" > /dev/null; then
        SERVE_PID=$(pgrep -n -f "secure_code_review_env.py serve")
        SERVE_MEM=$(ps -p $SERVE_PID -o rss= 2>/dev/null | awk '{printf "%.1f", $1/1024/1024}')
        echo -e "  ${GREEN}✓${NC} Serve:  PID ${SERVE_PID} (${SERVE_MEM}GB RAM)"
    else
        echo -e "  ${YELLOW}○${NC} Serve:  Not running"
    fi

    # Check API (use newest PID if multiple)
    if pgrep -n -f "atroposlib.cli.run_api" > /dev/null; then
        API_PID=$(pgrep -n -f "atroposlib.cli.run_api")
        API_MEM=$(ps -p $API_PID -o rss= 2>/dev/null | awk '{printf "%.1f", $1/1024/1024}')
        echo -e "  ${GREEN}✓${NC} API:    PID ${API_PID} (${API_MEM}GB RAM)"

        # Try to get API status
        if command -v curl &> /dev/null && curl -s http://127.0.0.1:8000/status &> /dev/null; then
            echo -e "          ${GREEN}API responding on port 8000${NC}"
        fi
    else
        echo -e "  ${YELLOW}○${NC} API:    Not running"
    fi
    echo ""

    # ==================== GRPO TRAINING PROGRESS ====================
    echo -e "${BOLD}${MAGENTA}[3] GRPO TRAINING PROGRESS${NC}"
    echo -e "${CYAN}────────────────────────────────────────────────────────────────────────────────${NC}"

    GRPO_LOG=$(ls -t /tmp/grpo*.log 2>/dev/null | head -1)
    if [[ -f "$GRPO_LOG" ]]; then
        echo -e "  Log: ${GRPO_LOG}"
        echo ""

        # Extract latest step info (performance: tail first, then grep)
        LATEST_STEP=$(tail -2000 "$GRPO_LOG" | grep -E "^Step [0-9]+/" | tail -1)
        if [[ -n "$LATEST_STEP" ]]; then
            echo -e "  ${WHITE}${LATEST_STEP}${NC}"

            # Get step details from last 100 lines
            tail -150 "$GRPO_LOG" | grep -A 20 "Step Summary" | tail -20 | while read line; do
                if [[ $line =~ "Loss:" ]]; then
                    echo -e "  ${GREEN}$line${NC}"
                elif [[ $line =~ "ETA:" ]]; then
                    echo -e "  ${YELLOW}$line${NC}"
                elif [[ $line =~ "GPU:" ]]; then
                    echo -e "  ${CYAN}$line${NC}"
                else
                    echo "  $line"
                fi
            done
        else
            echo -e "  ${YELLOW}Waiting for training to start...${NC}"
            tail -5 "$GRPO_LOG" | sed 's/^/  /'
        fi
    else
        echo -e "  ${YELLOW}No GRPO log found in /tmp/grpo*.log${NC}"
    fi
    echo ""

    # ==================== SERVE QUEUE STATUS ====================
    echo -e "${BOLD}${MAGENTA}[4] SERVE QUEUE STATUS${NC}"
    echo -e "${CYAN}────────────────────────────────────────────────────────────────────────────────${NC}"

    SERVE_LOG=$(ls -t /tmp/scr_serve*.log 2>/dev/null | head -1)
    if [[ -f "$SERVE_LOG" ]]; then
        echo -e "  Log: ${SERVE_LOG}"
        echo ""

        # Look for queue/rollout info (performance: already tailing, no change needed)
        if tail -100 "$SERVE_LOG" | grep -q "rollout\|batch\|task\|queue"; then
            tail -100 "$SERVE_LOG" | grep -i "rollout\|batch\|task\|queue" | tail -8 | sed 's/^/  /'
        else
            echo -e "  ${YELLOW}No recent queue activity${NC}"
            tail -5 "$SERVE_LOG" | sed 's/^/  /'
        fi
    else
        echo -e "  ${YELLOW}No serve log found in /tmp/scr_serve*.log${NC}"
    fi
    echo ""

    # ==================== API STATUS ====================
    echo -e "${BOLD}${MAGENTA}[5] API RECENT ACTIVITY${NC}"
    echo -e "${CYAN}────────────────────────────────────────────────────────────────────────────────${NC}"

    API_LOG="/tmp/atropos_api.log"
    if [[ -f "$API_LOG" ]]; then
        # Show last 5 lines from API log
        tail -5 "$API_LOG" | sed 's/^/  /'
    else
        echo -e "  ${YELLOW}No API log found at ${API_LOG}${NC}"
    fi
    echo ""

    # ==================== FOOTER ====================
    echo -e "${CYAN}────────────────────────────────────────────────────────────────────────────────${NC}"
    echo -e "Refreshing every ${REFRESH}s | Press ${BOLD}Ctrl+C${NC} to exit"
    echo -e "Full logs: ${YELLOW}tail -f ${GRPO_LOG}${NC}"
    echo ""

    sleep "$REFRESH"
done
