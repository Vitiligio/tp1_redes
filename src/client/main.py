import time
import socket
import os
from helpers.message import *

CLIENT_SOCKET_TIMEOUT = 5
SERVER_IP = "127.0.0.1"
SERVER_PORT = 12000

def connect_server(addr):
    """Establish connection with server using SYN handshake"""
    connection_made = False
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client_socket.settimeout(CLIENT_SOCKET_TIMEOUT)

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

def send_operation_request(client_socket, addr, operation: str, filename: str):
    """Send operation specification (UPLOAD/DOWNLOAD + filename) with seq=1"""
    operation_packet = create_operation_packet(seq_num=1, operation=operation, filename=filename)
    
    print(f"Sending operation request: {operation}:{filename}")
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

def upload_file(client_socket, addr, filename: str):
    """Upload file to server"""
    if not os.path.exists(filename):
        print(f"File {filename} not found")
        return False
    
    print(f"Starting upload of {filename}")
    
    # Read and send file in chunks
    seq_num = 2  # Start after operation packet (seq=1)
    
    try:
        with open(filename, 'rb') as file:
            while True:
                chunk = file.read(1024)  # Read 1KB chunks
                if not chunk:
                    break
                
                data_packet = create_data_packet(seq_num=seq_num, data=chunk)
                client_socket.sendto(data_packet.to_bytes(), addr)
                print(f"Sent data chunk seq={seq_num}, size={len(chunk)} bytes")
                
                # Wait for ACK
                try:
                    data, server = client_socket.recvfrom(1024)
                    ack_packet = RDTPacket.from_bytes(data)
                    
                    if ack_packet.verify_integrity() and ack_packet.has_flag(RDTFlags.ACK):
                        if ack_packet.header.ack_number == seq_num:
                            print(f"ACK received for seq={seq_num}")
                            seq_num += 1
                        else:
                            print(f"Unexpected ACK, expected {seq_num}, got {ack_packet.header.ack_number}")
                    else:
                        print("Invalid ACK packet")
                        
                except socket.timeout:
                    print(f"Timeout waiting for ACK seq={seq_num}, retrying...")
                    # In real implementation, you'd retransmit here
                    continue
                    
    except Exception as e:
        print(f"Error reading file: {e}")
        return False
    
    return True

def download_file(client_socket, addr, filename: str):
    """Download file from server"""
    # This would be implemented similarly but with server sending data
    # For now, just a placeholder
    print(f"Download operation requested for: {filename}")
    print("Download functionality to be implemented")
    return True

def main():
    operation = "UPLOAD"  # or "DOWNLOAD"
    filename = "test.txt"
    
    addr = (SERVER_IP, SERVER_PORT)
    connection_made, client_socket = connect_server(addr)
    
    if connection_made:
        # Send operation specification
        if send_operation_request(client_socket, addr, operation, filename):
            if operation.upper() == "UPLOAD":
                upload_file(client_socket, addr, filename)
            elif operation.upper() == "DOWNLOAD":
                download_file(client_socket, addr, filename)
        
        # Close connection
        fin_packet = create_end_packet(seq_num=100)  # Use high seq number for FIN
        client_socket.sendto(fin_packet.to_bytes(), addr)
        print("Sent FIN packet")
    
    client_socket.close()

if __name__ == "__main__":
    main()