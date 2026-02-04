#!/usr/bin/env python3
"""
Test Client for Ableton Live MCP Server

This script tests the connection and basic functionality of the MCP server
by communicating directly with the OSC daemon.

Usage:
    python test_client.py [--host HOST] [--port PORT] [--verbose]
"""

import argparse
import json
import socket
import sys
import time
from typing import Dict, Any, List, Tuple

# ANSI color codes for output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'


def print_header(text: str) -> None:
    """Print a formatted header."""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'=' * 60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'=' * 60}{Colors.END}")


def print_test(name: str, passed: bool, details: str = "") -> None:
    """Print a test result."""
    status = f"{Colors.GREEN}PASS{Colors.END}" if passed else f"{Colors.RED}FAIL{Colors.END}"
    print(f"  [{status}] {name}")
    if details and not passed:
        print(f"         {Colors.YELLOW}{details}{Colors.END}")


def print_info(text: str) -> None:
    """Print an info message."""
    print(f"  {Colors.BLUE}ℹ{Colors.END} {text}")


class TestClient:
    """Test client for communicating with the OSC daemon."""
    
    def __init__(self, host: str = '127.0.0.1', port: int = 65432, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None
        self.connected = False
    
    def connect(self) -> bool:
        """Connect to the OSC daemon."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect((self.host, self.port))
            self.connected = True
            return True
        except socket.error as e:
            self.connected = False
            return False
    
    def disconnect(self) -> None:
        """Disconnect from the daemon."""
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self.connected = False
    
    def send_command(self, command: str, **kwargs) -> Dict[str, Any]:
        """Send a command and receive response."""
        if not self.connected:
            return {'status': 'error', 'message': 'Not connected'}
        
        request = {'command': command}
        request.update(kwargs)
        
        try:
            self.sock.sendall(json.dumps(request).encode('utf-8'))
            response_data = self.sock.recv(8192)
            if not response_data:
                return {'status': 'error', 'message': 'No response'}
            return json.loads(response_data.decode('utf-8'))
        except socket.timeout:
            return {'status': 'error', 'message': 'Timeout'}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}
    
    def send_osc(self, address: str, args: List[Any] = None) -> Dict[str, Any]:
        """Send an OSC message."""
        return self.send_command('send_message', address=address, args=args or [])


def run_tests(host: str, port: int, verbose: bool = False) -> Tuple[int, int]:
    """
    Run all tests and return (passed, failed) counts.
    """
    passed = 0
    failed = 0
    results = []
    
    client = TestClient(host, port)
    
    # ==========================================================================
    # Test 1: Connect to OSC Daemon
    # ==========================================================================
    print_header("Test 1: OSC Daemon Connection")
    
    test_name = "Connect to OSC daemon"
    if client.connect():
        print_test(test_name, True)
        passed += 1
        results.append((test_name, True, ""))
    else:
        print_test(test_name, False, f"Could not connect to {host}:{port}")
        failed += 1
        results.append((test_name, False, f"Could not connect to {host}:{port}"))
        print(f"\n{Colors.RED}Cannot continue tests without daemon connection.{Colors.END}")
        print(f"Make sure osc_daemon.py is running: python osc_daemon.py")
        return passed, failed
    
    # ==========================================================================
    # Test 2: Daemon Status
    # ==========================================================================
    print_header("Test 2: Daemon Status")
    
    test_name = "Get daemon status"
    response = client.send_command('get_status')
    if response.get('status') == 'ok':
        print_test(test_name, True)
        passed += 1
        results.append((test_name, True, ""))
        if verbose:
            print_info(f"Daemon config: {response}")
    else:
        print_test(test_name, False, response.get('message', 'Unknown error'))
        failed += 1
        results.append((test_name, False, response.get('message', '')))
    
    # ==========================================================================
    # Test 3: Ping Daemon
    # ==========================================================================
    print_header("Test 3: Ping Daemon")
    
    test_name = "Ping daemon"
    response = client.send_command('ping')
    if response.get('status') == 'ok' and response.get('message') == 'pong':
        print_test(test_name, True)
        passed += 1
        results.append((test_name, True, ""))
    else:
        print_test(test_name, False, f"Unexpected response: {response}")
        failed += 1
        results.append((test_name, False, str(response)))
    
    # ==========================================================================
    # Test 4: Ableton Connection Test
    # ==========================================================================
    print_header("Test 4: Ableton Live Connection")
    print_info("This test requires Ableton Live to be running with AbletonOSC enabled.")
    
    test_name = "Test Ableton connection (/live/test)"
    response = client.send_osc('/live/test')
    if response.get('status') == 'success':
        print_test(test_name, True)
        passed += 1
        results.append((test_name, True, ""))
        ableton_connected = True
    else:
        print_test(test_name, False, response.get('message', 'No response from Ableton'))
        failed += 1
        results.append((test_name, False, response.get('message', '')))
        ableton_connected = False
        print_info("Ableton Live may not be running or AbletonOSC is not enabled.")
    
    # ==========================================================================
    # Test 5: Get Tempo (requires Ableton)
    # ==========================================================================
    print_header("Test 5: Get Tempo")
    
    test_name = "Get tempo (/live/song/get/tempo)"
    response = client.send_osc('/live/song/get/tempo')
    if response.get('status') == 'success':
        data = response.get('data', ())
        if data:
            print_test(test_name, True)
            print_info(f"Current tempo: {data[0]} BPM")
            passed += 1
            results.append((test_name, True, ""))
        else:
            print_test(test_name, False, "No tempo data returned")
            failed += 1
            results.append((test_name, False, "No tempo data"))
    else:
        print_test(test_name, False, response.get('message', 'Unknown error'))
        failed += 1
        results.append((test_name, False, response.get('message', '')))
    
    # ==========================================================================
    # Test 6: Get Track Names (requires Ableton)
    # ==========================================================================
    print_header("Test 6: Get Track Names")
    
    test_name = "Get track names (/live/song/get/track_names)"
    response = client.send_osc('/live/song/get/track_names')
    if response.get('status') == 'success':
        data = response.get('data', ())
        if data:
            print_test(test_name, True)
            print_info(f"Found {len(data)} tracks: {list(data)[:5]}{'...' if len(data) > 5 else ''}")
            passed += 1
            results.append((test_name, True, ""))
        else:
            print_test(test_name, False, "No track data returned")
            failed += 1
            results.append((test_name, False, "No track data"))
    else:
        print_test(test_name, False, response.get('message', 'Unknown error'))
        failed += 1
        results.append((test_name, False, response.get('message', '')))
    
    # ==========================================================================
    # Test 7: Get Is Playing (requires Ableton)
    # ==========================================================================
    print_header("Test 7: Get Playback State")
    
    test_name = "Get is_playing (/live/song/get/is_playing)"
    response = client.send_osc('/live/song/get/is_playing')
    if response.get('status') == 'success':
        data = response.get('data', ())
        if data is not None:
            print_test(test_name, True)
            is_playing = bool(data[0]) if data else False
            print_info(f"Playback state: {'Playing' if is_playing else 'Stopped'}")
            passed += 1
            results.append((test_name, True, ""))
        else:
            print_test(test_name, False, "No playback state returned")
            failed += 1
            results.append((test_name, False, "No state data"))
    else:
        print_test(test_name, False, response.get('message', 'Unknown error'))
        failed += 1
        results.append((test_name, False, response.get('message', '')))
    
    # ==========================================================================
    # Test 8: Fire-and-Forget Command (Play/Stop)
    # ==========================================================================
    print_header("Test 8: Fire-and-Forget Commands")
    
    # Test stop command (safe to run)
    test_name = "Send stop command (/live/song/stop_playing)"
    response = client.send_osc('/live/song/stop_playing')
    if response.get('status') == 'sent':
        print_test(test_name, True)
        passed += 1
        results.append((test_name, True, ""))
    else:
        print_test(test_name, False, response.get('message', 'Unknown error'))
        failed += 1
        results.append((test_name, False, response.get('message', '')))
    
    # ==========================================================================
    # Test 9: Get Number of Scenes
    # ==========================================================================
    print_header("Test 9: Get Number of Scenes")
    
    test_name = "Get num_scenes (/live/song/get/num_scenes)"
    response = client.send_osc('/live/song/get/num_scenes')
    if response.get('status') == 'success':
        data = response.get('data', ())
        if data:
            print_test(test_name, True)
            print_info(f"Number of scenes: {data[0]}")
            passed += 1
            results.append((test_name, True, ""))
        else:
            print_test(test_name, False, "No scene count returned")
            failed += 1
            results.append((test_name, False, "No scene data"))
    else:
        print_test(test_name, False, response.get('message', 'Unknown error'))
        failed += 1
        results.append((test_name, False, response.get('message', '')))
    
    # ==========================================================================
    # Test 10: Get Application Version
    # ==========================================================================
    print_header("Test 10: Get Application Version")
    
    test_name = "Get version (/live/application/get/version)"
    response = client.send_osc('/live/application/get/version')
    if response.get('status') == 'success':
        data = response.get('data', ())
        if data:
            print_test(test_name, True)
            version = '.'.join(str(x) for x in data)
            print_info(f"Ableton Live version: {version}")
            passed += 1
            results.append((test_name, True, ""))
        else:
            print_test(test_name, False, "No version data returned")
            failed += 1
            results.append((test_name, False, "No version data"))
    else:
        print_test(test_name, False, response.get('message', 'Unknown error'))
        failed += 1
        results.append((test_name, False, response.get('message', '')))
    
    # Cleanup
    client.disconnect()
    
    return passed, failed


def main():
    parser = argparse.ArgumentParser(
        description='Test client for Ableton Live MCP Server',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python test_client.py
    python test_client.py --verbose
    python test_client.py --host 127.0.0.1 --port 65432

Prerequisites:
    1. Start the OSC daemon: python osc_daemon.py
    2. Have Ableton Live running with AbletonOSC enabled
        """
    )
    
    parser.add_argument('--host', type=str, default='127.0.0.1',
                        help='OSC daemon host (default: 127.0.0.1)')
    parser.add_argument('--port', type=int, default=65432,
                        help='OSC daemon port (default: 65432)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose output')
    
    args = parser.parse_args()
    
    print(f"\n{Colors.BOLD}Ableton Live MCP Server - Test Suite{Colors.END}")
    print(f"Testing connection to OSC daemon at {args.host}:{args.port}")
    
    passed, failed = run_tests(args.host, args.port, args.verbose)
    
    # Print summary
    print_header("Test Summary")
    total = passed + failed
    
    if failed == 0:
        print(f"\n  {Colors.GREEN}{Colors.BOLD}ALL TESTS PASSED{Colors.END}")
    else:
        print(f"\n  {Colors.YELLOW}Some tests failed{Colors.END}")
    
    print(f"\n  Total:  {total}")
    print(f"  Passed: {Colors.GREEN}{passed}{Colors.END}")
    print(f"  Failed: {Colors.RED}{failed}{Colors.END}")
    
    # Overall result
    print()
    if failed == 0:
        print(f"  {Colors.GREEN}{Colors.BOLD}✓ PASS{Colors.END}")
        return 0
    elif passed > 0:
        print(f"  {Colors.YELLOW}{Colors.BOLD}⚠ PARTIAL PASS{Colors.END}")
        print(f"\n  Note: Some tests require Ableton Live to be running.")
        return 0 if passed >= 3 else 1  # Pass if at least daemon tests work
    else:
        print(f"  {Colors.RED}{Colors.BOLD}✗ FAIL{Colors.END}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
