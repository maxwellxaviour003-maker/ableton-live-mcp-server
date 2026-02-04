#!/usr/bin/env python3
"""
OSC Daemon for Ableton Live MCP Server

This daemon acts as a bridge between the MCP server and Ableton Live via OSC.
It handles bidirectional communication using the AbletonOSC Remote Script.

Default ports:
- Socket server (MCP communication): 65432
- Ableton OSC receive: 11000
- Ableton OSC send: 11001
"""

import asyncio
import json
import logging
import signal
import sys
import os
from typing import Dict, Any, Optional, Tuple
from pythonosc.udp_client import SimpleUDPClient
from pythonosc.osc_server import AsyncIOOSCUDPServer
from pythonosc.dispatcher import Dispatcher

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class AbletonOSCDaemon:
    """
    OSC Daemon that bridges MCP server communication with Ableton Live.
    
    The daemon:
    1. Listens for TCP connections from the MCP server on socket_port
    2. Sends OSC messages to Ableton Live on ableton_port
    3. Receives OSC responses from Ableton Live on receive_port
    """
    
    # OSC address prefixes that expect responses from Ableton
    RESPONSE_PREFIXES = (
        '/live/device/get',
        '/live/scene/get',
        '/live/view/get',
        '/live/clip/get',
        '/live/clip_slot/get',
        '/live/track/get',
        '/live/song/get',
        '/live/api/get',
        '/live/application/get',
        '/live/test',
        '/live/error'
    )
    
    def __init__(self, 
                 socket_host: str = '127.0.0.1',
                 socket_port: int = 65432,
                 ableton_host: str = '127.0.0.1',
                 ableton_port: int = 11000,
                 receive_port: int = 11001,
                 response_timeout: float = 5.0):
        """
        Initialize the OSC daemon.
        
        Args:
            socket_host: Host address for the TCP socket server
            socket_port: Port for MCP server connections
            ableton_host: Host address where Ableton Live is running
            ableton_port: Port where Ableton Live receives OSC messages
            receive_port: Port where this daemon receives OSC responses
            response_timeout: Timeout in seconds for waiting for OSC responses
        """
        self.socket_host = socket_host
        self.socket_port = socket_port
        self.ableton_host = ableton_host
        self.ableton_port = ableton_port
        self.receive_port = receive_port
        self.response_timeout = response_timeout
        
        # Initialize OSC client for sending messages to Ableton
        self.osc_client = SimpleUDPClient(ableton_host, ableton_port)
        
        # Store pending responses keyed by OSC address
        # Using a dict with address as key and a list of futures to handle multiple requests
        self.pending_responses: Dict[str, asyncio.Future] = {}
        self._response_lock = asyncio.Lock()
        
        # Initialize OSC server dispatcher
        self.dispatcher = Dispatcher()
        self.dispatcher.set_default_handler(self._handle_ableton_message)
        
        # Server references
        self.osc_server: Optional[AsyncIOOSCUDPServer] = None
        self.tcp_server: Optional[asyncio.Server] = None
        self._running = False
        
        logger.info("OSC Daemon initialized")
        logger.info(f"  Socket server: {socket_host}:{socket_port}")
        logger.info(f"  Ableton OSC send: {ableton_host}:{ableton_port}")
        logger.info(f"  Ableton OSC receive: {socket_host}:{receive_port}")
    
    def _handle_ableton_message(self, address: str, *args) -> None:
        """
        Handle incoming OSC messages from Ableton Live.
        
        This method is called by the OSC server when a message is received.
        It resolves any pending futures waiting for this address.
        
        Args:
            address: The OSC address of the message
            *args: The arguments of the OSC message
        """
        logger.debug(f"Received OSC: {address} {args}")
        
        # Check if there's a pending request for this address
        if address in self.pending_responses:
            future = self.pending_responses.get(address)
            if future and not future.done():
                future.set_result({
                    'status': 'success',
                    'address': address,
                    'data': args
                })
                logger.debug(f"Resolved pending response for {address}")
            # Clean up
            if address in self.pending_responses:
                del self.pending_responses[address]
        else:
            # Log unsolicited messages (could be listener notifications)
            logger.debug(f"Unsolicited OSC message: {address} {args}")
    
    async def _send_osc_with_response(self, address: str, args: list) -> Dict[str, Any]:
        """
        Send an OSC message and wait for a response.
        
        Args:
            address: The OSC address to send to
            args: The arguments to send
            
        Returns:
            A dictionary containing the response or error
        """
        async with self._response_lock:
            # Create a future for the response
            future = asyncio.Future()
            self.pending_responses[address] = future
        
        try:
            # Send the OSC message
            self.osc_client.send_message(address, args)
            logger.debug(f"Sent OSC: {address} {args}")
            
            # Wait for response with timeout
            response = await asyncio.wait_for(future, timeout=self.response_timeout)
            logger.debug(f"Got response for {address}: {response}")
            return response
            
        except asyncio.TimeoutError:
            # Clean up the pending response
            async with self._response_lock:
                if address in self.pending_responses:
                    del self.pending_responses[address]
            
            error_msg = f"Timeout waiting for response to {address}"
            logger.warning(error_msg)
            return {
                'status': 'error',
                'message': error_msg,
                'address': address
            }
        except Exception as e:
            # Clean up on any error
            async with self._response_lock:
                if address in self.pending_responses:
                    del self.pending_responses[address]
            
            error_msg = f"Error sending OSC message: {str(e)}"
            logger.error(error_msg)
            return {
                'status': 'error',
                'message': error_msg,
                'address': address
            }
    
    def _send_osc_fire_and_forget(self, address: str, args: list) -> Dict[str, Any]:
        """
        Send an OSC message without waiting for a response.
        
        Args:
            address: The OSC address to send to
            args: The arguments to send
            
        Returns:
            A dictionary indicating the message was sent
        """
        try:
            self.osc_client.send_message(address, args)
            logger.debug(f"Sent OSC (fire-and-forget): {address} {args}")
            return {
                'status': 'sent',
                'address': address
            }
        except Exception as e:
            error_msg = f"Error sending OSC message: {str(e)}"
            logger.error(error_msg)
            return {
                'status': 'error',
                'message': error_msg,
                'address': address
            }
    
    def _expects_response(self, address: str) -> bool:
        """
        Determine if an OSC address expects a response from Ableton.
        
        Args:
            address: The OSC address to check
            
        Returns:
            True if the address expects a response
        """
        return address.startswith(self.RESPONSE_PREFIXES)
    
    async def _handle_socket_client(self, reader: asyncio.StreamReader, 
                                     writer: asyncio.StreamWriter) -> None:
        """
        Handle an incoming TCP connection from the MCP server.
        
        Args:
            reader: The stream reader for the connection
            writer: The stream writer for the connection
        """
        client_address = writer.get_extra_info('peername')
        logger.info(f"Client connected: {client_address}")
        
        try:
            while True:
                # Read data from the client
                data = await reader.read(4096)
                if not data:
                    break
                
                try:
                    # Parse the JSON message
                    message = json.loads(data.decode('utf-8'))
                    logger.debug(f"Received from {client_address}: {message}")
                    
                    # Process the command
                    response = await self._process_command(message)
                    
                    # Send the response
                    response_data = json.dumps(response).encode('utf-8')
                    writer.write(response_data)
                    await writer.drain()
                    
                except json.JSONDecodeError as e:
                    logger.error(f"JSON decode error: {e}")
                    response = {
                        'status': 'error',
                        'message': f'Invalid JSON: {str(e)}'
                    }
                    writer.write(json.dumps(response).encode('utf-8'))
                    await writer.drain()
                    
        except asyncio.CancelledError:
            logger.info(f"Connection cancelled: {client_address}")
        except ConnectionResetError:
            logger.info(f"Connection reset by client: {client_address}")
        except Exception as e:
            logger.error(f"Error handling client {client_address}: {e}")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            logger.info(f"Client disconnected: {client_address}")
    
    async def _process_command(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a command received from the MCP server.
        
        Args:
            message: The command message dictionary
            
        Returns:
            A response dictionary
        """
        command = message.get('command')
        
        if command == 'send_message':
            # Extract OSC message details
            address = message.get('address')
            args = message.get('args', [])
            
            if not address:
                return {
                    'status': 'error',
                    'message': 'Missing OSC address'
                }
            
            # Determine if we should wait for a response
            if self._expects_response(address):
                return await self._send_osc_with_response(address, args)
            else:
                return self._send_osc_fire_and_forget(address, args)
        
        elif command == 'get_status':
            return {
                'status': 'ok',
                'daemon': 'running',
                'ableton_host': self.ableton_host,
                'ableton_port': self.ableton_port,
                'receive_port': self.receive_port,
                'socket_port': self.socket_port
            }
        
        elif command == 'ping':
            return {
                'status': 'ok',
                'message': 'pong'
            }
        
        else:
            return {
                'status': 'error',
                'message': f'Unknown command: {command}'
            }
    
    async def start(self) -> None:
        """
        Start the OSC daemon.
        
        This starts both the OSC server (for receiving from Ableton)
        and the TCP server (for receiving from MCP server).
        """
        self._running = True
        
        # Start OSC server to receive messages from Ableton
        try:
            self.osc_server = AsyncIOOSCUDPServer(
                (self.socket_host, self.receive_port),
                self.dispatcher,
                asyncio.get_event_loop()
            )
            transport, protocol = await self.osc_server.create_serve_endpoint()
            logger.info(f"OSC server listening on {self.socket_host}:{self.receive_port}")
        except Exception as e:
            logger.error(f"Failed to start OSC server: {e}")
            raise
        
        # Start TCP server for MCP communication
        try:
            self.tcp_server = await asyncio.start_server(
                self._handle_socket_client,
                self.socket_host,
                self.socket_port
            )
            logger.info(f"TCP server listening on {self.socket_host}:{self.socket_port}")
        except Exception as e:
            logger.error(f"Failed to start TCP server: {e}")
            raise
        
        logger.info("=" * 60)
        logger.info("Ableton OSC Daemon started successfully")
        logger.info("=" * 60)
        logger.info(f"  MCP Server should connect to: {self.socket_host}:{self.socket_port}")
        logger.info(f"  Sending OSC to Ableton on: {self.ableton_host}:{self.ableton_port}")
        logger.info(f"  Receiving OSC from Ableton on: {self.socket_host}:{self.receive_port}")
        logger.info("")
        logger.info("Make sure Ableton Live is running with AbletonOSC Remote Script enabled.")
        logger.info("=" * 60)
        
        # Serve forever
        async with self.tcp_server:
            await self.tcp_server.serve_forever()
    
    async def stop(self) -> None:
        """Stop the OSC daemon gracefully."""
        self._running = False
        
        if self.tcp_server:
            self.tcp_server.close()
            await self.tcp_server.wait_closed()
            logger.info("TCP server stopped")
        
        logger.info("OSC Daemon stopped")


def main():
    """Main entry point for the OSC daemon."""
    # Parse command line arguments for configuration
    import argparse
    
    parser = argparse.ArgumentParser(
        description='OSC Daemon for Ableton Live MCP Server',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python osc_daemon.py
  python osc_daemon.py --socket-port 65432 --ableton-port 11000
  python osc_daemon.py --verbose

Environment variables:
  OSC_SOCKET_HOST     Socket server host (default: 127.0.0.1)
  OSC_SOCKET_PORT     Socket server port (default: 65432)
  OSC_ABLETON_HOST    Ableton host (default: 127.0.0.1)
  OSC_ABLETON_PORT    Ableton OSC receive port (default: 11000)
  OSC_RECEIVE_PORT    OSC response receive port (default: 11001)
        """
    )
    
    parser.add_argument('--socket-host', type=str, 
                        default=os.environ.get('OSC_SOCKET_HOST', '127.0.0.1'),
                        help='Host for TCP socket server')
    parser.add_argument('--socket-port', type=int,
                        default=int(os.environ.get('OSC_SOCKET_PORT', '65432')),
                        help='Port for TCP socket server')
    parser.add_argument('--ableton-host', type=str,
                        default=os.environ.get('OSC_ABLETON_HOST', '127.0.0.1'),
                        help='Host where Ableton Live is running')
    parser.add_argument('--ableton-port', type=int,
                        default=int(os.environ.get('OSC_ABLETON_PORT', '11000')),
                        help='Port where Ableton Live receives OSC')
    parser.add_argument('--receive-port', type=int,
                        default=int(os.environ.get('OSC_RECEIVE_PORT', '11001')),
                        help='Port to receive OSC responses from Ableton')
    parser.add_argument('--timeout', type=float, default=5.0,
                        help='Response timeout in seconds')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose logging')
    
    args = parser.parse_args()
    
    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Create and start the daemon
    daemon = AbletonOSCDaemon(
        socket_host=args.socket_host,
        socket_port=args.socket_port,
        ableton_host=args.ableton_host,
        ableton_port=args.ableton_port,
        receive_port=args.receive_port,
        response_timeout=args.timeout
    )
    
    # Handle shutdown signals
    def signal_handler(sig, frame):
        logger.info("Shutdown signal received")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Run the daemon
    try:
        asyncio.run(daemon.start())
    except KeyboardInterrupt:
        logger.info("Daemon stopped by user")
    except Exception as e:
        logger.error(f"Daemon error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
