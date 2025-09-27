import random
import socket
import os
from helpers.message import *
from server_config import SERVER_IP, SERVER_PORT, STORAGE_DIR
from protocols.stop_and_wait import StopAndWaitProtocol
from protocols.selective_repeat import SelectiveRepeatProtocol

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
                    'connected': False,
                    'proto': None,
                    'proto_name': None
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
        
        syn_ack = create_sync_packet(0)
        syn_ack.set_flag(RDTFlags.ACK)
        server_socket.sendto(syn_ack.to_bytes(), address)
        
        client_state['connected'] = True
        client_state['expected_seq'] = 1
        print(f"Sent SYN-ACK to {address}, expecting operation packet (seq=1)")
    
    def handle_data(self, packet, address, server_socket, client_state):
        if not client_state['connected']:
            print(f"Data received but no connection")
            return
        
        expected_seq = client_state['expected_seq']
        seq_num = packet.header.sequence_number
        
        
        if client_state['current_operation'] is None:
            if expected_seq != 1 or seq_num != expected_seq:
                print(f"Error: expected operation at seq=1, got seq={seq_num} (expected_seq={expected_seq})")
                return
            operation, filename, protocol = parse_operation_packet(packet)
            if operation and filename:
                client_state['current_operation'] = operation
                client_state['current_filename'] = filename
                client_state['protocol'] = protocol
                client_state['proto_name'] = protocol
                if protocol == "stop_and_wait":
                    client_state['proto'] = StopAndWaitProtocol(server_socket)
                elif protocol == "selective_repeat":
                    client_state['proto'] = SelectiveRepeatProtocol(server_socket)
                print(f"Operation received: {operation} for file: {filename} using {protocol}")
                if operation == "UPLOAD":
                    filepath = os.path.join(self.storage_dir, filename)
                    try:
                        client_state['file_handle'] = open(filepath, 'wb')
                        print(f"Ready to receive upload: {filepath}")
                    except Exception as e:
                        print(f"Error creating file: {e}")
                        return
                    ack_packet = create_ack_packet(ack_num=1)
                    server_socket.sendto(ack_packet.to_bytes(), address)
                    client_state['expected_seq'] = 2
                    try:
                        server_socket.settimeout(None)
                    except Exception:
                        pass
                    return
                elif operation == "DOWNLOAD":
                    filepath = os.path.join(self.storage_dir, filename)
                    if not os.path.exists(filepath):
                        print(f"Requested file not found: {filepath}")
                        return
                    ack_packet = create_ack_packet(ack_num=1)
                    server_socket.sendto(ack_packet.to_bytes(), address)
                    if client_state['proto'] is not None:
                        client_state['proto'].current_seq = 2
                        print(f"Starting download of {filepath} to {address}")
                        client_state['proto'].send_file(filepath, address)
                        fin_ack = create_end_packet(0, seq_num=3)
                        server_socket.sendto(fin_ack.to_bytes(), address)
                        print(f"Download finished for: {filename}")
                        try:
                            server_socket.settimeout(None)
                        except Exception:
                            pass
                    return

        proto = client_state.get('proto')
        if proto is None:
            print("Error: no protocol instance for client")
            return
        proto.expected_seq = client_state['expected_seq']
        ack_num, data_to_write, new_expected = proto.on_data(packet)
        if client_state['current_operation'] == "UPLOAD" and client_state['file_handle']:
            if data_to_write:
                client_state['file_handle'].write(data_to_write)
                print(f"Received file data up to seq={ack_num}, wrote {len(data_to_write)} bytes")
        ack_packet = create_ack_packet(ack_num=ack_num)
        server_socket.sendto(ack_packet.to_bytes(), address)
        client_state['expected_seq'] = new_expected
    
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
        except socket.timeout:
            continue
        except Exception as e:
            print(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()