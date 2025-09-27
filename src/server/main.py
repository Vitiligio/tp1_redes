import random
import socket
import os
from helpers.message import *
from server_config import SERVER_IP, SERVER_PORT, STORAGE_DIR

class RDTProtocol:
    def __init__(self, storage_dir="server_files"):
        self.client_states = {}
        self.storage_dir = storage_dir
        os.makedirs(storage_dir, exist_ok=True)
    
    def handle_packet(self, data, address, server_socket):
        try:
            packet = RDTPacket.from_bytes(data)
            
            if not packet.verify_integrity():
                print(f"Packet from {address} failed integrity check")
                return
            
            if address not in self.client_states:
                self.client_states[address] = {
                    'expected_seq': 0,
                    'current_operation': None,
                    'current_filename': None,
                    'file_handle': None,
                    'connected': False
                }
            
            client_state = self.client_states[address]
            seq_num = packet.header.sequence_number
            
            if packet.has_flag(RDTFlags.SYN):
                self.handle_syn(packet, address, server_socket, client_state)
            elif packet.has_flag(RDTFlags.DATA):
                self.handle_data(packet, address, server_socket, client_state)
            elif packet.has_flag(RDTFlags.FIN):
                self.handle_fin(packet, address, server_socket, client_state)
            elif packet.has_flag(RDTFlags.ACK):
                self.handle_ack(packet, address, client_state)
                
        except Exception as e:
            print(f"Error processing packet from {address}: {e}")
    
    def handle_syn(self, packet, address, server_socket, client_state):
        print(f"SYN received from {address}")
        
        # Send SYN-ACK
        syn_ack = create_sync_packet(0)  # Create with SYN flag
        syn_ack.set_flag(RDTFlags.ACK)   # Add ACK flag
        server_socket.sendto(syn_ack.to_bytes(), address)
        
        client_state['connected'] = True
        client_state['expected_seq'] = 1  # Expect operation packet next
        print(f"Sent SYN-ACK to {address}, expecting operation packet (seq=1)")
    
    def handle_data(self, packet, address, server_socket, client_state):
        if not client_state['connected']:
            print(f"Data received but no connection")
            return
        
        expected_seq = client_state['expected_seq']
        seq_num = packet.header.sequence_number
        
        # Simulate 10% packet loss
        if random.randint(0, 100) < 10:
            print(f"Simulating packet loss for seq={seq_num}")
            return
        
        if seq_num == expected_seq:
            if seq_num == 1:
                # This is the operation specification packet
                operation, filename, protocol = parse_operation_packet(packet)
                if operation and filename:
                    client_state['current_operation'] = operation
                    client_state['current_filename'] = filename
                    client_state['protocol'] = protocol
                    print(f"Operation received: {operation} for file: {filename} using {protocol}")
                    
                    # Prepare for file transfer
                    if operation == "UPLOAD":
                        filepath = os.path.join(self.storage_dir, filename)
                        try:
                            client_state['file_handle'] = open(filepath, 'wb')
                            print(f"Ready to receive upload: {filepath}")
                        except Exception as e:
                            print(f"Error creating file: {e}")
                            # Send error response
                            return
                    
                    # Send ACK for operation packet
                    ack_packet = create_ack_packet(ack_num=1)
                    server_socket.sendto(ack_packet.to_bytes(), address)
                    client_state['expected_seq'] = 2  # Expect first data packet next
                    
            else:
                # This is a file data packet
                if client_state['current_operation'] == "UPLOAD" and client_state['file_handle']:
                    # Save file data
                    client_state['file_handle'].write(packet.payload)
                    print(f"Received file data seq={seq_num}, size={len(packet.payload)} bytes")
                
                # Send ACK
                ack_packet = create_ack_packet(ack_num=seq_num)
                server_socket.sendto(ack_packet.to_bytes(), address)
                client_state['expected_seq'] = seq_num + 1
                
        elif seq_num < expected_seq:
            # Duplicate packet - resend ACK
            print(f"Duplicate packet seq={seq_num}")
            ack_packet = create_ack_packet(ack_num=seq_num)
            server_socket.sendto(ack_packet.to_bytes(), address)
        else:
            print(f"Out-of-order packet seq={seq_num}, expected={expected_seq}")
    
    def handle_fin(self, packet, address, server_socket, client_state):
        print(f"FIN received from {address}")
        
        # Clean up file handle if upload was in progress
        if client_state.get('file_handle'):
            client_state['file_handle'].close()
            print(f"Upload completed for: {client_state['current_filename']}")
        
        # Send FIN-ACK
        fin_ack = create_end_packet(0, seq_num=packet.header.sequence_number + 1)
        server_socket.sendto(fin_ack.to_bytes(), address)
        
        # Clean up client state
        if address in self.client_states:
            del self.client_states[address]
        
        print(f"Connection with {address} closed")
    
    def handle_ack(self, packet, address, client_state):
        print(f"ACK received from {address} for seq={packet.header.ack_number}")

def main():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.bind((SERVER_IP, SERVER_PORT))
    
    rdt_protocol = RDTProtocol(storage_dir=STORAGE_DIR)
    
    print(f"RDT Server is running on {SERVER_IP}:{SERVER_PORT}")
    print(f"Files will be stored in: {STORAGE_DIR}/")
    
    while True:
        try:
            data, address = server_socket.recvfrom(2048)
            rdt_protocol.handle_packet(data, address, server_socket)
            
        except KeyboardInterrupt:
            print("\nServer shutting down...")
            break
        except Exception as e:
            print(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()