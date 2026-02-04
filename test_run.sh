#!/bin/bash
#
# test_run.sh - Verification script for Ableton Live MCP Server
#
# This script:
# 1. Creates/activates a Python virtual environment
# 2. Installs dependencies
# 3. Starts the OSC daemon
# 4. Runs the test client
# 5. Reports PASS/FAIL status
#
# Prerequisites:
# - Python 3.9+ installed
# - Ableton Live running with AbletonOSC Remote Script enabled (for full tests)
#
# Usage:
#   ./test_run.sh              # Run all tests
#   ./test_run.sh --daemon-only # Only start the daemon (for manual testing)
#   ./test_run.sh --help       # Show help
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"
DAEMON_PID=""
DAEMON_LOG="${SCRIPT_DIR}/daemon.log"

# Cleanup function
cleanup() {
    if [ -n "$DAEMON_PID" ] && kill -0 "$DAEMON_PID" 2>/dev/null; then
        echo -e "\n${BLUE}Stopping OSC daemon (PID: $DAEMON_PID)...${NC}"
        kill "$DAEMON_PID" 2>/dev/null || true
        wait "$DAEMON_PID" 2>/dev/null || true
    fi
}

# Set trap for cleanup
trap cleanup EXIT INT TERM

# Print header
print_header() {
    echo -e "\n${BOLD}${BLUE}============================================================${NC}"
    echo -e "${BOLD}${BLUE}$1${NC}"
    echo -e "${BOLD}${BLUE}============================================================${NC}"
}

# Print status
print_status() {
    local status=$1
    local message=$2
    if [ "$status" = "ok" ]; then
        echo -e "  ${GREEN}✓${NC} $message"
    elif [ "$status" = "warn" ]; then
        echo -e "  ${YELLOW}⚠${NC} $message"
    elif [ "$status" = "fail" ]; then
        echo -e "  ${RED}✗${NC} $message"
    else
        echo -e "  ${BLUE}ℹ${NC} $message"
    fi
}

# Show help
show_help() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Verification script for Ableton Live MCP Server"
    echo ""
    echo "Options:"
    echo "  --daemon-only    Only start the OSC daemon (for manual testing)"
    echo "  --skip-install   Skip dependency installation"
    echo "  --verbose        Enable verbose output"
    echo "  --help           Show this help message"
    echo ""
    echo "Prerequisites:"
    echo "  - Python 3.9+ installed"
    echo "  - For full tests: Ableton Live running with AbletonOSC enabled"
    echo ""
    echo "Examples:"
    echo "  $0                    # Run all tests"
    echo "  $0 --daemon-only      # Start daemon for manual testing"
    echo "  $0 --verbose          # Run tests with verbose output"
}

# Parse arguments
DAEMON_ONLY=false
SKIP_INSTALL=false
VERBOSE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --daemon-only)
            DAEMON_ONLY=true
            shift
            ;;
        --skip-install)
            SKIP_INSTALL=true
            shift
            ;;
        --verbose|-v)
            VERBOSE="--verbose"
            shift
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            show_help
            exit 1
            ;;
    esac
done

# Main script
echo -e "${BOLD}Ableton Live MCP Server - Verification Script${NC}"
echo -e "Script directory: ${SCRIPT_DIR}"

# =============================================================================
# Step 1: Check Python version
# =============================================================================
print_header "Step 1: Checking Python Installation"

# Try different Python commands
PYTHON_CMD=""
for cmd in python3.11 python3.10 python3.9 python3 python; do
    if command -v "$cmd" &> /dev/null; then
        version=$($cmd --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 9 ]; then
            PYTHON_CMD="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    print_status "fail" "Python 3.9+ not found"
    echo -e "${RED}Please install Python 3.9 or newer${NC}"
    exit 1
fi

print_status "ok" "Found Python: $PYTHON_CMD ($($PYTHON_CMD --version))"

# =============================================================================
# Step 2: Create/Activate Virtual Environment
# =============================================================================
print_header "Step 2: Setting Up Virtual Environment"

# Check if uv is available (preferred)
if command -v uv &> /dev/null; then
    print_status "info" "Using uv for package management"
    USE_UV=true
else
    print_status "info" "Using pip for package management"
    USE_UV=false
fi

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    print_status "info" "Creating virtual environment..."
    if [ "$USE_UV" = true ]; then
        uv venv "$VENV_DIR"
    else
        $PYTHON_CMD -m venv "$VENV_DIR"
    fi
    print_status "ok" "Virtual environment created at $VENV_DIR"
else
    print_status "ok" "Virtual environment exists at $VENV_DIR"
fi

# Activate virtual environment
source "$VENV_DIR/bin/activate"
print_status "ok" "Virtual environment activated"

# =============================================================================
# Step 3: Install Dependencies
# =============================================================================
print_header "Step 3: Installing Dependencies"

if [ "$SKIP_INSTALL" = false ]; then
    if [ "$USE_UV" = true ]; then
        print_status "info" "Installing dependencies with uv..."
        cd "$SCRIPT_DIR"
        uv pip install -e .
    else
        print_status "info" "Installing dependencies with pip..."
        pip install --upgrade pip
        pip install python-osc fastmcp
    fi
    print_status "ok" "Dependencies installed"
else
    print_status "info" "Skipping dependency installation (--skip-install)"
fi

# Verify imports
print_status "info" "Verifying Python imports..."
python -c "from pythonosc.udp_client import SimpleUDPClient; from mcp.server.fastmcp import FastMCP; print('Imports OK')" 2>/dev/null
if [ $? -eq 0 ]; then
    print_status "ok" "All required packages are available"
else
    print_status "fail" "Failed to import required packages"
    exit 1
fi

# =============================================================================
# Step 4: Start OSC Daemon
# =============================================================================
print_header "Step 4: Starting OSC Daemon"

# Check if daemon is already running
if lsof -i :65432 &> /dev/null; then
    print_status "warn" "Port 65432 is already in use"
    print_status "info" "Attempting to use existing daemon..."
else
    print_status "info" "Starting OSC daemon..."
    cd "$SCRIPT_DIR"
    python osc_daemon.py > "$DAEMON_LOG" 2>&1 &
    DAEMON_PID=$!
    
    # Wait for daemon to start
    sleep 2
    
    if kill -0 "$DAEMON_PID" 2>/dev/null; then
        print_status "ok" "OSC daemon started (PID: $DAEMON_PID)"
    else
        print_status "fail" "OSC daemon failed to start"
        echo -e "${RED}Daemon log:${NC}"
        cat "$DAEMON_LOG"
        exit 1
    fi
fi

# =============================================================================
# Step 5: Run Tests or Wait (daemon-only mode)
# =============================================================================

if [ "$DAEMON_ONLY" = true ]; then
    print_header "Daemon Running (Manual Testing Mode)"
    echo -e "${BLUE}OSC Daemon is running. You can now:${NC}"
    echo -e "  1. Start Ableton Live with AbletonOSC enabled"
    echo -e "  2. Run the MCP server: python mcp_ableton_server.py"
    echo -e "  3. Or run tests manually: python test_client.py"
    echo -e ""
    echo -e "${YELLOW}Press Ctrl+C to stop the daemon and exit${NC}"
    
    # Wait forever (until Ctrl+C)
    while true; do
        sleep 1
    done
else
    print_header "Step 5: Running Tests"
    
    echo -e "${YELLOW}Note: Full tests require Ableton Live to be running with AbletonOSC enabled.${NC}"
    echo -e "${YELLOW}Daemon-only tests will still pass if Ableton is not available.${NC}"
    echo ""
    
    # Run the test client
    cd "$SCRIPT_DIR"
    python test_client.py $VERBOSE
    TEST_RESULT=$?
    
    # =============================================================================
    # Final Summary
    # =============================================================================
    print_header "Test Results"
    
    if [ $TEST_RESULT -eq 0 ]; then
        echo -e "\n  ${GREEN}${BOLD}╔════════════════════════════════════════╗${NC}"
        echo -e "  ${GREEN}${BOLD}║              PASS                      ║${NC}"
        echo -e "  ${GREEN}${BOLD}╚════════════════════════════════════════╝${NC}"
        echo ""
        echo -e "  The MCP server is ready to use."
        echo -e "  Run: ${BOLD}python mcp_ableton_server.py${NC}"
    else
        echo -e "\n  ${RED}${BOLD}╔════════════════════════════════════════╗${NC}"
        echo -e "  ${RED}${BOLD}║              FAIL                      ║${NC}"
        echo -e "  ${RED}${BOLD}╚════════════════════════════════════════╝${NC}"
        echo ""
        echo -e "  Some tests failed. Check the output above for details."
        echo -e "  Make sure Ableton Live is running with AbletonOSC enabled."
    fi
    
    exit $TEST_RESULT
fi
