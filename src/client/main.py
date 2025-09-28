import time
import socket
import os
import argparse
import sys
import tempfile
import shutil
from helpers.message import *
from client_config import SERVER_IP, SERVER_PORT, SOCKET_TIMEOUT, PACKET_SIZE
from protocols.stop_and_wait import StopAndWaitProtocol
from protocols.selective_repeat import SelectiveRepeatProtocol

def connect_server(addr):
    """Establish connection with server using SYN handshake"""
    connection_made = False
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client_socket.settimeout(SOCKET_TIMEOUT)

    # Send SYN packet
    sync_message = create_sync_packet(0)
    
    print(f"Attempting to connect to server at {addr}")
    start = time.time()
    client_socket.sendto(sync_message.to_bytes(), addr)
    
    try:
        data, server = client_socket.recvfrom(1024)
        response_packet = RDTPacket.from_bytes(data)
        
        if response_packet.has_flag(RDTFlags.SYN) and response_packet.has_flag(RDTFlags.ACK):
            print("Connection established!")
            connection_made = True
        else:
            print("Invalid response from server")
            
    except socket.timeout:
        print('Connection request timed out')

    return connection_made, client_socket

def send_operation_request(client_socket, addr, operation: str, filename: str, protocol: str = "stop_and_wait"):
    """Send operation specification (UPLOAD/DOWNLOAD + filename + protocol) with seq=1"""
    operation_packet = create_operation_packet(seq_num=1, operation=operation, filename=filename, protocol=protocol)
    
    print(f"Sending operation request: {operation}:{filename} using {protocol}")
    client_socket.sendto(operation_packet.to_bytes(), addr)
    
    # Wait for ACK
    try:
        data, server = client_socket.recvfrom(1024)
        ack_packet = RDTPacket.from_bytes(data)
        
        if ack_packet.verify_integrity() and ack_packet.has_flag(RDTFlags.ACK):
            if ack_packet.header.ack_number == 1:
                print("Operation request acknowledged by server")
                return True
            else:
                print(f"Unexpected ACK number: {ack_packet.header.ack_number}")
        else:
            print("Invalid ACK received")
    except socket.timeout:
        print('Operation request timeout')
    
    return False

def upload_file(client_socket, addr, filename: str, protocol: str):
    """Upload file to server using specified protocol"""
    if protocol == "stop_and_wait":
        proto = StopAndWaitProtocol(client_socket, timeout=SOCKET_TIMEOUT)
    elif protocol == "selective_repeat":
        proto = SelectiveRepeatProtocol(client_socket, timeout=SOCKET_TIMEOUT)
    else:
        print(f"Unknown protocol: {protocol}, using stop_and_wait")
        proto = StopAndWaitProtocol(client_socket, timeout=SOCKET_TIMEOUT)
    
    proto.current_seq = 2
    return proto.send_file(filename, addr)

def download_file(client_socket, addr, filename: str, protocol: str, verbose: bool = False):
    """Download file from server using specified protocol with safe temporary file handling"""
    if protocol == "stop_and_wait":
        proto = StopAndWaitProtocol(client_socket, timeout=SOCKET_TIMEOUT)
    elif protocol == "selective_repeat":
        proto = SelectiveRepeatProtocol(client_socket, timeout=SOCKET_TIMEOUT)
    else:
        print(f"Unknown protocol: {protocol}, using stop_and_wait")
        proto = StopAndWaitProtocol(client_socket, timeout=SOCKET_TIMEOUT)
    
    print(f"Starting download of: {filename} using {protocol}")
    
    # Create temporary file for download
    try:
        # Create a temporary file in the current directory
        temp_file = tempfile.NamedTemporaryFile(prefix=f".{filename}.download.", 
                                               delete=False, 
                                               dir=".")
        temp_file_path = temp_file.name
        if verbose:
            print(f"Created temporary file: {temp_file_path}")
    except Exception as e:
        print(f"Error creating temporary file: {e}")
        return False
    
    download_success = False
    file_handle = None
    
    try:
        # Open the temporary file for writing
        file_handle = open(temp_file_path, 'wb')
        
        # Set up protocol for receiving
        proto.expected_seq = 2  # Server will start sending data at seq=2
        proto.current_seq = 2
        
        if verbose:
            print("Waiting for file data from server...")
        
        # Receive file data
        bytes_received = 0
        start_time = time.time()
        
        while True:
            try:
                # Receive packet with timeout
                client_socket.settimeout(5.0)  # 5 second timeout for receiving data
                data, server_addr = client_socket.recvfrom(2048)
                packet = RDTPacket.from_bytes(data)
                
                if packet.verify_integrity():
                    if packet.has_flag(RDTFlags.DATA):
                        # Process data packet
                        ack_num, data_to_write, new_expected = proto.on_data(packet)
                        
                        if data_to_write:
                            file_handle.write(data_to_write)
                            bytes_received += len(data_to_write)
                            if verbose:
                                print(f"Received {len(data_to_write)} bytes, total: {bytes_received}")
                        
                        # Send ACK for received data
                        ack_packet = create_ack_packet(ack_num=ack_num)
                        client_socket.sendto(ack_packet.to_bytes(), addr)
                        proto.expected_seq = new_expected
                        
                    elif packet.has_flag(RDTFlags.FIN):
                        # End of file transfer
                        if verbose:
                            print("Received FIN packet, download complete")
                        
                        # Send FIN-ACK
                        fin_ack = create_ack_packet(ack_num=packet.header.sequence_number)
                        client_socket.sendto(fin_ack.to_bytes(), addr)
                        download_success = True
                        break
                    
                    elif packet.has_flag(RDTFlags.ERROR):
                        # Server sent an error
                        error_msg = packet.payload.decode('utf-8', errors='ignore')
                        print(f"Server error: {error_msg}")
                        break
                
            except socket.timeout:
                print("Timeout waiting for data from server")
                break
            except Exception as e:
                print(f"Error receiving data: {e}")
                break
        
        # Calculate transfer stats
        transfer_time = time.time() - start_time
        if transfer_time > 0:
            speed = bytes_received / transfer_time / 1024  # KB/s
            if verbose:
                print(f"Download completed: {bytes_received} bytes in {transfer_time:.2f}s ({speed:.2f} KB/s)")
        
    except Exception as e:
        print(f"Error during download: {e}")
    finally:
        # Always close the file handle
        if file_handle:
            file_handle.close()
        
        # Handle the temporary file based on success/failure
        if download_success:
            # Download successful - move temp file to final location
            try:
                # Remove existing file if it exists
                if os.path.exists(filename):
                    if verbose:
                        print(f"Removing existing file: {filename}")
                    os.remove(filename)
                
                # Move temporary file to final location
                shutil.move(temp_file_path, filename)
                
                # Verify the file was created
                if os.path.exists(filename):
                    file_size = os.path.getsize(filename)
                    print(f"Download successful: {filename} ({file_size} bytes)")
                    return True
                else:
                    print("Error: Final file was not created")
                    return False
                    
            except Exception as e:
                print(f"Error finalizing download: {e}")
                # Clean up temporary file on error
                try:
                    if os.path.exists(temp_file_path):
                        os.remove(temp_file_path)
                except:
                    pass
                return False
        else:
            # Download failed - clean up temporary file
            try:
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
                    if verbose:
                        print("Download failed, temporary file removed")
            except Exception as e:
                print(f"Error cleaning up temporary file: {e}")
            
            return False

def wait_for_fin_ack(client_socket, addr, timeout=5):
    """Wait for FIN-ACK from server after sending FIN"""
    try:
        client_socket.settimeout(timeout)
        data, server = client_socket.recvfrom(1024)
        fin_ack_packet = RDTPacket.from_bytes(data)
        
        if (fin_ack_packet.has_flag(RDTFlags.FIN) and 
            fin_ack_packet.has_flag(RDTFlags.ACK)):
            return True
    except socket.timeout:
        print("Timeout waiting for FIN-ACK")
    except Exception as e:
        print(f"Error waiting for FIN-ACK: {e}")
    
    return False

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='File transfer client for reliable data transfer protocol',
        add_help=False
    )
    
    # Optional arguments
    parser.add_argument('-h', '--help', action='store_true', help='show this help message and exit')
    parser.add_argument('-v', '--verbose', action='store_true', help='increase output verbosity')
    parser.add_argument('-q', '--quiet', action='store_true', help='decrease output verbosity')
    parser.add_argument('-H', '--host', type=str, default=SERVER_IP, help='server IP address')
    parser.add_argument('-p', '--port', type=int, default=SERVER_PORT, help='server port')
    parser.add_argument('-s', '--src', type=str, help='source file path')
    parser.add_argument('-n', '--name', type=str, required=True, help='file name')
    parser.add_argument('-r', '--protocol', type=str, choices=['stop_and_wait', 'selective_repeat'], 
                       default='stop_and_wait', help='error recovery protocol')
    
    # Positional argument for command (upload/download)
    parser.add_argument('command', type=str, choices=['upload', 'download'], nargs='?', 
                       help='command to execute (upload or download)')
    
    return parser

def main():
    # Parse command line arguments
    parser = parse_arguments()
    
    # Handle the case where no arguments are provided
    if len(sys.argv) == 1:
        parser.print_help()
        return
    
    args = parser.parse_args()
    
    # Handle help flag
    if args.help:
        parser.print_help()
        return
    
    # Validate command is provided
    if not args.command:
        print("Error: command (upload/download) is required")
        parser.print_usage()
        return
    
    # Set verbosity level
    verbose = args.verbose
    quiet = args.quiet
    
    # Validate source file for upload
    if args.command == 'upload':
        if not args.src:
            print("Error: source file path (-s/--src) is required for upload")
            return
        if not os.path.exists(args.src):
            print(f"Error: source file '{args.src}' does not exist")
            return
    
    # Set operation and filename
    operation = args.command.upper()
    filename = args.name
    protocol = args.protocol
    
    # Use provided host and port, or defaults from client_config
    addr = (args.host, args.port)
    
    if not quiet:
        print(f"Operation: {operation}")
        print(f"Filename: {filename}")
        print(f"Protocol: {protocol}")
        print(f"Server: {addr}")
        if args.command == 'upload':
            print(f"Source file: {args.src}")
    
    # Connect to server
    connection_made, client_socket = connect_server(addr)
    
    if connection_made:
        # Send operation specification
        if send_operation_request(client_socket, addr, operation, filename, protocol):
            if operation == "UPLOAD":
                # For upload, use the source file path
                success = upload_file(client_socket, addr, args.src, protocol)
                if success:
                    if not quiet:
                        print("Upload completed successfully")
                else:
                    print("Upload failed")
            elif operation == "DOWNLOAD":
                # For download, save to current directory
                success = download_file(client_socket, addr, filename, protocol, verbose)
                if not success and not quiet:
                    print("Download failed")
        
        # Close connection gracefully
        if not quiet:
            print("Closing connection...")
        
        # Send FIN packet
        fin_packet = create_end_packet(ack_num=0, seq_num=100)
        client_socket.sendto(fin_packet.to_bytes(), addr)
        
        # Wait for FIN-ACK with short timeout
        if wait_for_fin_ack(client_socket, addr, timeout=2):
            if verbose:
                print("Connection closed gracefully")
        else:
            if verbose:
                print("Server didn't respond to FIN, closing anyway")
    
    client_socket.close()

if __name__ == "__main__":
    main()