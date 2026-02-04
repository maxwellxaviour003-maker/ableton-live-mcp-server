#!/usr/bin/env python3
"""
MCP Server for Ableton Live Control

This server implements the Model Context Protocol (MCP) to provide LLM-accessible
tools for controlling Ableton Live via OSC through the OSC daemon.

The server communicates with the OSC daemon via TCP socket, which in turn
communicates with Ableton Live via OSC using the AbletonOSC Remote Script.
"""

import asyncio
import json
import logging
import os
import socket
import sys
from typing import List, Optional, Dict, Any, Tuple

from mcp.server.fastmcp import FastMCP

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class AbletonClient:
    """
    Client for communicating with the OSC daemon.
    
    This client sends commands to the OSC daemon via TCP socket,
    which then forwards them to Ableton Live via OSC.
    """
    
    def __init__(self, host: str = '127.0.0.1', port: int = 65432, timeout: float = 10.0):
        """
        Initialize the Ableton client.
        
        Args:
            host: Host address of the OSC daemon
            port: Port of the OSC daemon
            timeout: Socket timeout in seconds
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self.connected = False
        self._lock = asyncio.Lock()
        
        logger.info(f"AbletonClient initialized (daemon: {host}:{port})")
    
    def connect(self) -> bool:
        """
        Connect to the OSC daemon.
        
        Returns:
            True if connection successful, False otherwise
        """
        if self.connected and self.sock:
            return True
        
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect((self.host, self.port))
            self.connected = True
            logger.info(f"Connected to OSC daemon at {self.host}:{self.port}")
            return True
        except socket.error as e:
            logger.error(f"Failed to connect to OSC daemon: {e}")
            self.connected = False
            self.sock = None
            return False
    
    def disconnect(self) -> None:
        """Disconnect from the OSC daemon."""
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self.connected = False
        logger.info("Disconnected from OSC daemon")
    
    def _ensure_connected(self) -> bool:
        """Ensure we have a valid connection, reconnecting if necessary."""
        if not self.connected or not self.sock:
            return self.connect()
        return True
    
    async def send_command(self, command: str, **kwargs) -> Dict[str, Any]:
        """
        Send a command to the OSC daemon.
        
        Args:
            command: The command type (e.g., 'send_message', 'get_status')
            **kwargs: Additional parameters for the command
            
        Returns:
            The response from the daemon
        """
        async with self._lock:
            if not self._ensure_connected():
                return {
                    'status': 'error',
                    'message': 'Not connected to OSC daemon. Is osc_daemon.py running?'
                }
            
            # Build the request
            request = {'command': command}
            request.update(kwargs)
            
            try:
                # Send the request
                request_data = json.dumps(request).encode('utf-8')
                self.sock.sendall(request_data)
                
                # Receive the response
                response_data = self.sock.recv(8192)
                if not response_data:
                    self.connected = False
                    return {
                        'status': 'error',
                        'message': 'Connection closed by daemon'
                    }
                
                response = json.loads(response_data.decode('utf-8'))
                return response
                
            except socket.timeout:
                logger.error("Socket timeout waiting for response")
                return {
                    'status': 'error',
                    'message': 'Timeout waiting for response from daemon'
                }
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON response: {e}")
                return {
                    'status': 'error',
                    'message': f'Invalid response from daemon: {e}'
                }
            except socket.error as e:
                logger.error(f"Socket error: {e}")
                self.connected = False
                return {
                    'status': 'error',
                    'message': f'Communication error: {e}'
                }
    
    async def send_osc(self, address: str, args: List[Any] = None) -> Dict[str, Any]:
        """
        Send an OSC message to Ableton Live.
        
        Args:
            address: The OSC address (e.g., '/live/song/get/tempo')
            args: Optional list of arguments
            
        Returns:
            The response from Ableton (via daemon)
        """
        return await self.send_command('send_message', address=address, args=args or [])
    
    async def get_daemon_status(self) -> Dict[str, Any]:
        """Get the status of the OSC daemon."""
        return await self.send_command('get_status')
    
    async def ping(self) -> Dict[str, Any]:
        """Ping the OSC daemon."""
        return await self.send_command('ping')


# Initialize the MCP server
mcp = FastMCP(
    "Ableton Live Controller",
    dependencies=["python-osc"]
)

# Create the Ableton client (will connect on first use)
# Configuration can be overridden via environment variables
daemon_host = os.environ.get('ABLETON_DAEMON_HOST', '127.0.0.1')
daemon_port = int(os.environ.get('ABLETON_DAEMON_PORT', '65432'))
ableton_client = AbletonClient(host=daemon_host, port=daemon_port)


# =============================================================================
# Helper Functions
# =============================================================================

def format_response(response: Dict[str, Any], success_key: str = 'data') -> str:
    """
    Format a response from the daemon into a human-readable string.
    
    Args:
        response: The response dictionary
        success_key: The key to look for in successful responses
        
    Returns:
        A formatted string representation
    """
    if response.get('status') == 'success':
        data = response.get(success_key, response.get('data'))
        if isinstance(data, (list, tuple)):
            if len(data) == 1:
                return str(data[0])
            return ', '.join(str(item) for item in data)
        return str(data)
    elif response.get('status') == 'sent':
        return "Command sent successfully"
    elif response.get('status') == 'error':
        return f"Error: {response.get('message', 'Unknown error')}"
    else:
        return str(response)


# =============================================================================
# Song Control Tools
# =============================================================================

@mcp.tool()
async def play() -> str:
    """
    Start playback in Ableton Live.
    
    Returns:
        Status message indicating if playback started
    """
    response = await ableton_client.send_osc('/live/song/start_playing')
    return format_response(response)


@mcp.tool()
async def stop() -> str:
    """
    Stop playback in Ableton Live.
    
    Returns:
        Status message indicating if playback stopped
    """
    response = await ableton_client.send_osc('/live/song/stop_playing')
    return format_response(response)


@mcp.tool()
async def continue_playing() -> str:
    """
    Continue playback from the current position in Ableton Live.
    
    Returns:
        Status message
    """
    response = await ableton_client.send_osc('/live/song/continue_playing')
    return format_response(response)


@mcp.tool()
async def stop_all_clips() -> str:
    """
    Stop all playing clips in Ableton Live.
    
    Returns:
        Status message
    """
    response = await ableton_client.send_osc('/live/song/stop_all_clips')
    return format_response(response)


@mcp.tool()
async def get_tempo() -> str:
    """
    Get the current tempo (BPM) of the Ableton Live session.
    
    Returns:
        The current tempo in BPM
    """
    response = await ableton_client.send_osc('/live/song/get/tempo')
    if response.get('status') == 'success':
        data = response.get('data', ())
        if data:
            return f"Current tempo: {data[0]} BPM"
        return "Could not retrieve tempo"
    return format_response(response)


@mcp.tool()
async def set_tempo(bpm: float) -> str:
    """
    Set the tempo (BPM) of the Ableton Live session.
    
    Args:
        bpm: The desired tempo in beats per minute (20.0 - 999.0)
    
    Returns:
        Status message confirming the tempo change
    """
    if not 20.0 <= bpm <= 999.0:
        return "Error: Tempo must be between 20.0 and 999.0 BPM"
    
    response = await ableton_client.send_osc('/live/song/set/tempo', [bpm])
    if response.get('status') == 'sent':
        return f"Tempo set to {bpm} BPM"
    return format_response(response)


@mcp.tool()
async def get_is_playing() -> str:
    """
    Check if Ableton Live is currently playing.
    
    Returns:
        Whether playback is active
    """
    response = await ableton_client.send_osc('/live/song/get/is_playing')
    if response.get('status') == 'success':
        data = response.get('data', ())
        if data:
            is_playing = bool(data[0])
            return f"Playback is {'active' if is_playing else 'stopped'}"
        return "Could not determine playback state"
    return format_response(response)


@mcp.tool()
async def get_metronome() -> str:
    """
    Get the metronome (click) state in Ableton Live.
    
    Returns:
        Whether the metronome is enabled
    """
    response = await ableton_client.send_osc('/live/song/get/metronome')
    if response.get('status') == 'success':
        data = response.get('data', ())
        if data:
            enabled = bool(data[0])
            return f"Metronome is {'enabled' if enabled else 'disabled'}"
        return "Could not retrieve metronome state"
    return format_response(response)


@mcp.tool()
async def set_metronome(enabled: bool) -> str:
    """
    Enable or disable the metronome (click) in Ableton Live.
    
    Args:
        enabled: True to enable, False to disable
    
    Returns:
        Status message confirming the change
    """
    response = await ableton_client.send_osc('/live/song/set/metronome', [int(enabled)])
    if response.get('status') == 'sent':
        return f"Metronome {'enabled' if enabled else 'disabled'}"
    return format_response(response)


@mcp.tool()
async def get_loop() -> str:
    """
    Get the loop state in Ableton Live.
    
    Returns:
        Whether loop is enabled
    """
    response = await ableton_client.send_osc('/live/song/get/loop')
    if response.get('status') == 'success':
        data = response.get('data', ())
        if data:
            enabled = bool(data[0])
            return f"Loop is {'enabled' if enabled else 'disabled'}"
        return "Could not retrieve loop state"
    return format_response(response)


@mcp.tool()
async def set_loop(enabled: bool) -> str:
    """
    Enable or disable loop in Ableton Live.
    
    Args:
        enabled: True to enable loop, False to disable
    
    Returns:
        Status message confirming the change
    """
    response = await ableton_client.send_osc('/live/song/set/loop', [int(enabled)])
    if response.get('status') == 'sent':
        return f"Loop {'enabled' if enabled else 'disabled'}"
    return format_response(response)


@mcp.tool()
async def undo() -> str:
    """
    Undo the last action in Ableton Live.
    
    Returns:
        Status message
    """
    response = await ableton_client.send_osc('/live/song/undo')
    return format_response(response)


@mcp.tool()
async def redo() -> str:
    """
    Redo the last undone action in Ableton Live.
    
    Returns:
        Status message
    """
    response = await ableton_client.send_osc('/live/song/redo')
    return format_response(response)


@mcp.tool()
async def tap_tempo() -> str:
    """
    Tap tempo in Ableton Live.
    Call this repeatedly to set tempo by tapping.
    
    Returns:
        Status message
    """
    response = await ableton_client.send_osc('/live/song/tap_tempo')
    return format_response(response)


# =============================================================================
# Track Tools
# =============================================================================

@mcp.tool()
async def get_num_tracks() -> str:
    """
    Get the number of tracks in the Ableton Live session.
    
    Returns:
        The number of tracks
    """
    response = await ableton_client.send_osc('/live/song/get/num_tracks')
    if response.get('status') == 'success':
        data = response.get('data', ())
        if data:
            return f"Number of tracks: {data[0]}"
        return "Could not retrieve track count"
    return format_response(response)


@mcp.tool()
async def get_track_names(index_min: Optional[int] = None, index_max: Optional[int] = None) -> str:
    """
    Get the names of tracks in Ableton Live.
    
    Args:
        index_min: Optional minimum track index (0-based)
        index_max: Optional maximum track index (exclusive)
    
    Returns:
        A list of track names
    """
    args = []
    if index_min is not None and index_max is not None:
        args = [index_min, index_max]
    
    response = await ableton_client.send_osc('/live/song/get/track_names', args)
    if response.get('status') == 'success':
        data = response.get('data', ())
        if data:
            tracks = list(data)
            result = "Tracks:\n"
            for i, name in enumerate(tracks):
                idx = (index_min or 0) + i
                result += f"  [{idx}] {name}\n"
            return result.strip()
        return "No tracks found"
    return format_response(response)


@mcp.tool()
async def get_track_name(track_index: int) -> str:
    """
    Get the name of a specific track.
    
    Args:
        track_index: The index of the track (0-based)
    
    Returns:
        The track name
    """
    response = await ableton_client.send_osc('/live/track/get/name', [track_index])
    if response.get('status') == 'success':
        data = response.get('data', ())
        if len(data) >= 2:  # Returns [track_index, name]
            return f"Track {track_index}: {data[1]}"
        elif data:
            return f"Track {track_index}: {data[0]}"
        return f"Could not get name for track {track_index}"
    return format_response(response)


@mcp.tool()
async def set_track_name(track_index: int, name: str) -> str:
    """
    Set the name of a specific track.
    
    Args:
        track_index: The index of the track (0-based)
        name: The new name for the track
    
    Returns:
        Status message confirming the change
    """
    response = await ableton_client.send_osc('/live/track/set/name', [track_index, name])
    if response.get('status') == 'sent':
        return f"Track {track_index} renamed to '{name}'"
    return format_response(response)


@mcp.tool()
async def get_track_volume(track_index: int) -> str:
    """
    Get the volume of a specific track.
    
    Args:
        track_index: The index of the track (0-based)
    
    Returns:
        The track volume (0.0 to 1.0)
    """
    response = await ableton_client.send_osc('/live/track/get/volume', [track_index])
    if response.get('status') == 'success':
        data = response.get('data', ())
        if len(data) >= 2:
            return f"Track {track_index} volume: {data[1]:.2f}"
        elif data:
            return f"Track {track_index} volume: {data[0]:.2f}"
        return f"Could not get volume for track {track_index}"
    return format_response(response)


@mcp.tool()
async def set_track_volume(track_index: int, volume: float) -> str:
    """
    Set the volume of a specific track.
    
    Args:
        track_index: The index of the track (0-based)
        volume: The volume level (0.0 to 1.0, where 0.85 ≈ 0dB)
    
    Returns:
        Status message confirming the change
    """
    if not 0.0 <= volume <= 1.0:
        return "Error: Volume must be between 0.0 and 1.0"
    
    response = await ableton_client.send_osc('/live/track/set/volume', [track_index, volume])
    if response.get('status') == 'sent':
        return f"Track {track_index} volume set to {volume:.2f}"
    return format_response(response)


@mcp.tool()
async def get_track_mute(track_index: int) -> str:
    """
    Get the mute state of a specific track.
    
    Args:
        track_index: The index of the track (0-based)
    
    Returns:
        Whether the track is muted
    """
    response = await ableton_client.send_osc('/live/track/get/mute', [track_index])
    if response.get('status') == 'success':
        data = response.get('data', ())
        if len(data) >= 2:
            muted = bool(data[1])
            return f"Track {track_index} is {'muted' if muted else 'not muted'}"
        return f"Could not get mute state for track {track_index}"
    return format_response(response)


@mcp.tool()
async def set_track_mute(track_index: int, muted: bool) -> str:
    """
    Mute or unmute a specific track.
    
    Args:
        track_index: The index of the track (0-based)
        muted: True to mute, False to unmute
    
    Returns:
        Status message confirming the change
    """
    response = await ableton_client.send_osc('/live/track/set/mute', [track_index, int(muted)])
    if response.get('status') == 'sent':
        return f"Track {track_index} {'muted' if muted else 'unmuted'}"
    return format_response(response)


@mcp.tool()
async def get_track_solo(track_index: int) -> str:
    """
    Get the solo state of a specific track.
    
    Args:
        track_index: The index of the track (0-based)
    
    Returns:
        Whether the track is soloed
    """
    response = await ableton_client.send_osc('/live/track/get/solo', [track_index])
    if response.get('status') == 'success':
        data = response.get('data', ())
        if len(data) >= 2:
            soloed = bool(data[1])
            return f"Track {track_index} is {'soloed' if soloed else 'not soloed'}"
        return f"Could not get solo state for track {track_index}"
    return format_response(response)


@mcp.tool()
async def set_track_solo(track_index: int, soloed: bool) -> str:
    """
    Solo or unsolo a specific track.
    
    Args:
        track_index: The index of the track (0-based)
        soloed: True to solo, False to unsolo
    
    Returns:
        Status message confirming the change
    """
    response = await ableton_client.send_osc('/live/track/set/solo', [track_index, int(soloed)])
    if response.get('status') == 'sent':
        return f"Track {track_index} {'soloed' if soloed else 'unsoloed'}"
    return format_response(response)


@mcp.tool()
async def get_track_arm(track_index: int) -> str:
    """
    Get the arm (record-enable) state of a specific track.
    
    Args:
        track_index: The index of the track (0-based)
    
    Returns:
        Whether the track is armed for recording
    """
    response = await ableton_client.send_osc('/live/track/get/arm', [track_index])
    if response.get('status') == 'success':
        data = response.get('data', ())
        if len(data) >= 2:
            armed = bool(data[1])
            return f"Track {track_index} is {'armed' if armed else 'not armed'}"
        return f"Could not get arm state for track {track_index}"
    return format_response(response)


@mcp.tool()
async def set_track_arm(track_index: int, armed: bool) -> str:
    """
    Arm or disarm a specific track for recording.
    
    Args:
        track_index: The index of the track (0-based)
        armed: True to arm, False to disarm
    
    Returns:
        Status message confirming the change
    """
    response = await ableton_client.send_osc('/live/track/set/arm', [track_index, int(armed)])
    if response.get('status') == 'sent':
        return f"Track {track_index} {'armed' if armed else 'disarmed'}"
    return format_response(response)


@mcp.tool()
async def create_midi_track(index: int = -1) -> str:
    """
    Create a new MIDI track in Ableton Live.
    
    Args:
        index: Position to insert the track (-1 for end)
    
    Returns:
        Status message
    """
    response = await ableton_client.send_osc('/live/song/create_midi_track', [index])
    return format_response(response)


@mcp.tool()
async def create_audio_track(index: int = -1) -> str:
    """
    Create a new audio track in Ableton Live.
    
    Args:
        index: Position to insert the track (-1 for end)
    
    Returns:
        Status message
    """
    response = await ableton_client.send_osc('/live/song/create_audio_track', [index])
    return format_response(response)


@mcp.tool()
async def delete_track(track_index: int) -> str:
    """
    Delete a track from Ableton Live.
    
    Args:
        track_index: The index of the track to delete (0-based)
    
    Returns:
        Status message
    """
    response = await ableton_client.send_osc('/live/song/delete_track', [track_index])
    return format_response(response)


# =============================================================================
# Device Tools
# =============================================================================

@mcp.tool()
async def get_track_devices(track_index: int) -> str:
    """
    Get the list of devices on a specific track.
    
    Args:
        track_index: The index of the track (0-based)
    
    Returns:
        List of device names on the track
    """
    # First get the number of devices
    response = await ableton_client.send_osc('/live/track/get/num_devices', [track_index])
    if response.get('status') != 'success':
        return format_response(response)
    
    data = response.get('data', ())
    if len(data) < 2:
        return f"Could not get device count for track {track_index}"
    
    num_devices = int(data[1])
    if num_devices == 0:
        return f"Track {track_index} has no devices"
    
    # Get device names
    result = f"Track {track_index} devices ({num_devices}):\n"
    for device_index in range(num_devices):
        name_response = await ableton_client.send_osc('/live/device/get/name', [track_index, device_index])
        if name_response.get('status') == 'success':
            device_data = name_response.get('data', ())
            if len(device_data) >= 3:
                result += f"  [{device_index}] {device_data[2]}\n"
            elif device_data:
                result += f"  [{device_index}] {device_data[-1]}\n"
    
    return result.strip()


@mcp.tool()
async def get_device_parameters(track_index: int, device_index: int) -> str:
    """
    Get the parameters of a specific device.
    
    Args:
        track_index: The index of the track (0-based)
        device_index: The index of the device on the track (0-based)
    
    Returns:
        List of parameter names and values
    """
    # Get parameter names
    names_response = await ableton_client.send_osc('/live/device/get/parameters/name', [track_index, device_index])
    if names_response.get('status') != 'success':
        return format_response(names_response)
    
    names_data = names_response.get('data', ())
    if len(names_data) < 3:
        return f"Could not get parameters for device {device_index} on track {track_index}"
    
    # Skip track_index and device_index in response
    param_names = names_data[2:]
    
    # Get parameter values
    values_response = await ableton_client.send_osc('/live/device/get/parameters/value', [track_index, device_index])
    param_values = []
    if values_response.get('status') == 'success':
        values_data = values_response.get('data', ())
        if len(values_data) >= 3:
            param_values = values_data[2:]
    
    result = f"Device {device_index} on Track {track_index} parameters:\n"
    for i, name in enumerate(param_names):
        value = param_values[i] if i < len(param_values) else "N/A"
        if isinstance(value, float):
            result += f"  [{i}] {name}: {value:.3f}\n"
        else:
            result += f"  [{i}] {name}: {value}\n"
    
    return result.strip()


@mcp.tool()
async def set_device_parameter(track_index: int, device_index: int, param_index: int, value: float) -> str:
    """
    Set a parameter value on a specific device.
    
    Args:
        track_index: The index of the track (0-based)
        device_index: The index of the device on the track (0-based)
        param_index: The index of the parameter (0-based)
        value: The new value for the parameter
    
    Returns:
        Status message confirming the change
    """
    response = await ableton_client.send_osc(
        '/live/device/set/parameter/value',
        [track_index, device_index, param_index, value]
    )
    if response.get('status') == 'sent':
        return f"Parameter {param_index} on device {device_index} (track {track_index}) set to {value}"
    return format_response(response)


# =============================================================================
# Scene Tools
# =============================================================================

@mcp.tool()
async def get_num_scenes() -> str:
    """
    Get the number of scenes in the Ableton Live session.
    
    Returns:
        The number of scenes
    """
    response = await ableton_client.send_osc('/live/song/get/num_scenes')
    if response.get('status') == 'success':
        data = response.get('data', ())
        if data:
            return f"Number of scenes: {data[0]}"
        return "Could not retrieve scene count"
    return format_response(response)


@mcp.tool()
async def fire_scene(scene_index: int) -> str:
    """
    Fire (trigger) a specific scene.
    
    Args:
        scene_index: The index of the scene to fire (0-based)
    
    Returns:
        Status message
    """
    response = await ableton_client.send_osc('/live/scene/fire', [scene_index])
    if response.get('status') == 'sent':
        return f"Scene {scene_index} fired"
    return format_response(response)


@mcp.tool()
async def get_scene_name(scene_index: int) -> str:
    """
    Get the name of a specific scene.
    
    Args:
        scene_index: The index of the scene (0-based)
    
    Returns:
        The scene name
    """
    response = await ableton_client.send_osc('/live/scene/get/name', [scene_index])
    if response.get('status') == 'success':
        data = response.get('data', ())
        if len(data) >= 2:
            return f"Scene {scene_index}: {data[1]}"
        elif data:
            return f"Scene {scene_index}: {data[0]}"
        return f"Could not get name for scene {scene_index}"
    return format_response(response)


@mcp.tool()
async def set_scene_name(scene_index: int, name: str) -> str:
    """
    Set the name of a specific scene.
    
    Args:
        scene_index: The index of the scene (0-based)
        name: The new name for the scene
    
    Returns:
        Status message confirming the change
    """
    response = await ableton_client.send_osc('/live/scene/set/name', [scene_index, name])
    if response.get('status') == 'sent':
        return f"Scene {scene_index} renamed to '{name}'"
    return format_response(response)


@mcp.tool()
async def create_scene(index: int = -1) -> str:
    """
    Create a new scene in Ableton Live.
    
    Args:
        index: Position to insert the scene (-1 for end)
    
    Returns:
        Status message
    """
    response = await ableton_client.send_osc('/live/song/create_scene', [index])
    return format_response(response)


@mcp.tool()
async def delete_scene(scene_index: int) -> str:
    """
    Delete a scene from Ableton Live.
    
    Args:
        scene_index: The index of the scene to delete (0-based)
    
    Returns:
        Status message
    """
    response = await ableton_client.send_osc('/live/song/delete_scene', [scene_index])
    return format_response(response)


# =============================================================================
# Clip Tools
# =============================================================================

@mcp.tool()
async def fire_clip(track_index: int, clip_index: int) -> str:
    """
    Fire (trigger) a specific clip.
    
    Args:
        track_index: The index of the track (0-based)
        clip_index: The index of the clip slot (0-based)
    
    Returns:
        Status message
    """
    response = await ableton_client.send_osc('/live/clip/fire', [track_index, clip_index])
    if response.get('status') == 'sent':
        return f"Clip at track {track_index}, slot {clip_index} fired"
    return format_response(response)


@mcp.tool()
async def stop_clip(track_index: int, clip_index: int) -> str:
    """
    Stop a specific clip.
    
    Args:
        track_index: The index of the track (0-based)
        clip_index: The index of the clip slot (0-based)
    
    Returns:
        Status message
    """
    response = await ableton_client.send_osc('/live/clip/stop', [track_index, clip_index])
    if response.get('status') == 'sent':
        return f"Clip at track {track_index}, slot {clip_index} stopped"
    return format_response(response)


@mcp.tool()
async def get_clip_name(track_index: int, clip_index: int) -> str:
    """
    Get the name of a specific clip.
    
    Args:
        track_index: The index of the track (0-based)
        clip_index: The index of the clip slot (0-based)
    
    Returns:
        The clip name
    """
    response = await ableton_client.send_osc('/live/clip/get/name', [track_index, clip_index])
    if response.get('status') == 'success':
        data = response.get('data', ())
        if len(data) >= 3:
            return f"Clip at track {track_index}, slot {clip_index}: {data[2]}"
        return f"Could not get clip name"
    return format_response(response)


@mcp.tool()
async def set_clip_name(track_index: int, clip_index: int, name: str) -> str:
    """
    Set the name of a specific clip.
    
    Args:
        track_index: The index of the track (0-based)
        clip_index: The index of the clip slot (0-based)
        name: The new name for the clip
    
    Returns:
        Status message confirming the change
    """
    response = await ableton_client.send_osc('/live/clip/set/name', [track_index, clip_index, name])
    if response.get('status') == 'sent':
        return f"Clip at track {track_index}, slot {clip_index} renamed to '{name}'"
    return format_response(response)


# =============================================================================
# View Tools
# =============================================================================

@mcp.tool()
async def get_selected_track() -> str:
    """
    Get the currently selected track index.
    
    Returns:
        The index of the selected track
    """
    response = await ableton_client.send_osc('/live/view/get/selected_track')
    if response.get('status') == 'success':
        data = response.get('data', ())
        if data:
            return f"Selected track index: {data[0]}"
        return "Could not determine selected track"
    return format_response(response)


@mcp.tool()
async def set_selected_track(track_index: int) -> str:
    """
    Select a specific track.
    
    Args:
        track_index: The index of the track to select (0-based)
    
    Returns:
        Status message confirming the selection
    """
    response = await ableton_client.send_osc('/live/view/set/selected_track', [track_index])
    if response.get('status') == 'sent':
        return f"Track {track_index} selected"
    return format_response(response)


@mcp.tool()
async def get_selected_scene() -> str:
    """
    Get the currently selected scene index.
    
    Returns:
        The index of the selected scene
    """
    response = await ableton_client.send_osc('/live/view/get/selected_scene')
    if response.get('status') == 'success':
        data = response.get('data', ())
        if data:
            return f"Selected scene index: {data[0]}"
        return "Could not determine selected scene"
    return format_response(response)


@mcp.tool()
async def set_selected_scene(scene_index: int) -> str:
    """
    Select a specific scene.
    
    Args:
        scene_index: The index of the scene to select (0-based)
    
    Returns:
        Status message confirming the selection
    """
    response = await ableton_client.send_osc('/live/view/set/selected_scene', [scene_index])
    if response.get('status') == 'sent':
        return f"Scene {scene_index} selected"
    return format_response(response)


# =============================================================================
# Application/Utility Tools
# =============================================================================

@mcp.tool()
async def get_application_version() -> str:
    """
    Get the version of Ableton Live.
    
    Returns:
        The Ableton Live version string
    """
    response = await ableton_client.send_osc('/live/application/get/version')
    if response.get('status') == 'success':
        data = response.get('data', ())
        if data:
            return f"Ableton Live version: {'.'.join(str(x) for x in data)}"
        return "Could not retrieve version"
    return format_response(response)


@mcp.tool()
async def test_connection() -> str:
    """
    Test the connection to Ableton Live via the OSC daemon.
    
    Returns:
        Connection status and details
    """
    # First check daemon connection
    daemon_status = await ableton_client.get_daemon_status()
    if daemon_status.get('status') != 'ok':
        return f"OSC Daemon not responding. Is osc_daemon.py running?\nError: {daemon_status.get('message', 'Unknown error')}"
    
    # Then test Ableton connection
    response = await ableton_client.send_osc('/live/test')
    if response.get('status') == 'success':
        return "Connection successful! Ableton Live is responding via AbletonOSC."
    elif response.get('status') == 'error' and 'Timeout' in response.get('message', ''):
        return "OSC Daemon is running, but Ableton Live is not responding.\nMake sure:\n1. Ableton Live is running\n2. AbletonOSC is selected as a Control Surface in Preferences > Link/Tempo/MIDI"
    else:
        return f"Connection test result: {format_response(response)}"


@mcp.tool()
async def get_daemon_status() -> str:
    """
    Get the status of the OSC daemon.
    
    Returns:
        Daemon status information
    """
    response = await ableton_client.get_daemon_status()
    if response.get('status') == 'ok':
        return (
            f"OSC Daemon Status: Running\n"
            f"  Ableton Host: {response.get('ableton_host', 'N/A')}\n"
            f"  Ableton Port: {response.get('ableton_port', 'N/A')}\n"
            f"  Receive Port: {response.get('receive_port', 'N/A')}\n"
            f"  Socket Port: {response.get('socket_port', 'N/A')}"
        )
    return f"OSC Daemon not responding: {response.get('message', 'Unknown error')}"


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    logger.info("Starting Ableton Live MCP Server")
    logger.info(f"Connecting to OSC daemon at {daemon_host}:{daemon_port}")
    
    try:
        mcp.run()
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        sys.exit(1)
    finally:
        ableton_client.disconnect()
