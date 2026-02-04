# Running the Ableton Live MCP Server

This document provides instructions for setting up and running the Ableton Live MCP Server on macOS. The server allows you to control Ableton Live using natural language through any MCP-compatible client.

## 1. Requirements

Before you begin, ensure you have the following installed and configured:

- **macOS**: Ventura (13.0) or newer.
- **Python**: Version 3.9 or newer. You can check your version by running `python3 --version`.
- **Ableton Live**: Version 11 or newer.
- **Git**: For cloning the repository.

## 2. Installation

Follow these steps to set up the project environment.

### Step 2.1: Clone the Repository

Open your terminal and clone the GitHub repository to your local machine:

```bash
git clone https://github.com/Simon-Kansara/ableton-live-mcp-server.git
cd ableton-live-mcp-server
```

### Step 2.2: Install AbletonOSC Remote Script

The server communicates with Ableton Live using the **AbletonOSC** remote script. You must install it in Ableton Live's User Library.

1.  **Download AbletonOSC**: Go to the [AbletonOSC GitHub repository](https://github.com/ideoforms/AbletonOSC) and download the project as a ZIP file.
2.  **Unzip and Rename**: Unzip the downloaded file and rename the resulting folder from `AbletonOSC-master` to `AbletonOSC`.
3.  **Copy to User Library**: Move the `AbletonOSC` folder to your Ableton User Library's `Remote Scripts` directory. The path is typically:

    ```
    ~/Music/Ableton/User Library/Remote Scripts/
    ```

    If the `Remote Scripts` folder does not exist, you can create it.

4.  **Restart Ableton Live**: If Ableton Live is running, restart it.

5.  **Enable the Control Surface**: In Ableton Live, go to **Preferences > Link/Tempo/MIDI**. In the **Control Surface** section, select **AbletonOSC** from one of the dropdown menus. A message should appear in Live's status bar confirming that AbletonOSC is active (e.g., "AbletonOSC: Listening for OSC on port 11000").

### Step 2.3: Set Up the Python Environment

The project uses a Python virtual environment to manage dependencies. The included `test_run.sh` script can set this up for you automatically.

From the project's root directory, run:

```bash
./test_run.sh --skip-install
```

This command will:
1.  Create a virtual environment in a `.venv` directory.
2.  Activate it.
3.  Install all required Python packages (`fastmcp`, `python-osc`) using `uv` if available, or `pip` otherwise.

## 3. Running the Server

The system consists of two main components that must be running simultaneously: the **OSC Daemon** and the **MCP Server**.

### Step 3.1: Start the OSC Daemon

The OSC daemon (`osc_daemon.py`) is the bridge between the MCP server and Ableton Live. It listens for commands from the MCP server and translates them into OSC messages for Ableton.

To start it, open a new terminal window, navigate to the project directory, and run:

```bash
source .venv/bin/activate
python osc_daemon.py
```

You should see output confirming that the daemon is running and listening on the correct ports.

### Step 3.2: Start the MCP Server

The MCP server (`mcp_ableton_server.py`) exposes the tools that an MCP client can use. It communicates with the OSC daemon.

Open a **second** terminal window, navigate to the project directory, and run:

```bash
source .venv/bin/activate
python mcp_ableton_server.py
```

The server will start and register itself, ready to accept connections from MCP clients.

## 4. Verification

To ensure everything is set up correctly, you can use the `test_run.sh` script. This script automates the process of starting the daemon and running a series of tests.

**Important**: For the full test suite to pass, **Ableton Live must be running** with the AbletonOSC remote script enabled as described in Step 2.2.

In your terminal, from the project's root directory, run:

```bash
./test_run.sh
```

The script will perform the following checks:
- Python environment setup
- Dependency installation
- OSC daemon startup
- Connection to the daemon
- Connection to Ableton Live
- Basic OSC commands (get tempo, list tracks, etc.)

A `PASS` or `FAIL` summary will be printed at the end. If all tests pass, your server is ready.

## 5. Configuration

The default port configuration is suitable for most local setups.

| Component | Host | Port | Configurable In |
| :--- | :--- | :--- | :--- |
| OSC Daemon (for MCP) | `127.0.0.1` | `65432` | `osc_daemon.py` (or via args) |
| Ableton OSC (Receive) | `127.0.0.1` | `11000` | `osc_daemon.py` (or via args) |
| Ableton OSC (Send) | `127.0.0.1` | `11001` | `osc_daemon.py` (or via args) |

You can modify these ports by editing the `osc_daemon.py` file or by passing command-line arguments when starting the daemon. Run `python osc_daemon.py --help` for more details.

## 6. Troubleshooting

Here are some common issues and their solutions:

- **Error: "Connection refused" when running `test_run.sh`**
  - **Cause**: The OSC daemon is not running or is not accessible.
  - **Solution**: Make sure you start `osc_daemon.py` in a separate terminal window before running the tests or the MCP server.

- **Error: "Timeout waiting for response to /live/test"**
  - **Cause**: The OSC daemon is running, but it cannot communicate with Ableton Live.
  - **Solution**:
    1.  Ensure Ableton Live is running.
    2.  In Ableton Live's preferences, verify that **AbletonOSC** is selected as a Control Surface.
    3.  Check for any firewall software that might be blocking communication on ports `11000` or `11001`.

- **Error: "Port 65432 is already in use"**
  - **Cause**: Another process (or a previous instance of the daemon) is already using the default socket port.
  - **Solution**: Find and stop the existing process, or configure the daemon to use a different port by running `python osc_daemon.py --socket-port <new_port>`.
