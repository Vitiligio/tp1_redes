import multiprocessing
import multiprocessing.pool
import random
import socket
import os
import threading
from helpers.message import *
from server_config import *
from contextlib import contextmanager

class ReaderWriterLock:
    """A reader-writer lock that allows multiple readers or one writer"""
    def __init__(self):
        self._read_ready = threading.Condition(threading.Lock())
        self._readers = 0  # Number of active readers
    
    def acquire_read(self):
        """Acquire a read lock. Multiple readers can enter."""
        with self._read_ready:
            self._readers += 1
    
    def release_read(self):
        """Release a read lock."""
        with self._read_ready:
            self._readers -= 1
            if self._readers == 0:
                self._read_ready.notify_all()  # Notify waiting writers
    
    def acquire_write(self):
        """Acquire a write lock. Exclusive access."""
        self._read_ready.acquire()  # Acquire the underlying condition lock
        # Wait until there are no readers
        while self._readers > 0:
            self._read_ready.wait()
        # Now we have exclusive access
    
    def release_write(self):
        """Release a write lock."""
        self._read_ready.release()  # Release the underlying condition lock

class FileLockManager:
    def __init__(self):
        self.file_locks = {}  # filename -> ReaderWriterLock
        self.dict_lock = threading.Lock()  # Protects the file_locks dictionary
    
    @contextmanager
    def read_lock(self, filename):
        """Context manager for read operations"""
        lock = self._get_lock(filename)
        lock.acquire_read()
        try:
            yield  # Execute the read operation
        finally:
            lock.release_read()
    
    @contextmanager
    def write_lock(self, filename):
        """Context manager for write operations"""
        lock = self._get_lock(filename)
        lock.acquire_write()
        try:
            yield  # Execute the write operation
        finally:
            lock.release_write()
    
    def _get_lock(self, filename):
        """Get or create a lock for a specific file"""
        with self.dict_lock:
            if filename not in self.file_locks:
                self.file_locks[filename] = ReaderWriterLock()
            return self.file_locks[filename]
    
    def cleanup_file_lock(self, filename):
        """Clean up a file lock when it's no longer needed"""
        with self.dict_lock:
            if filename in self.file_locks:
                del self.file_locks[filename]


class RDTProtocol:
    def __init__(self, storage_dir="server_files"):
        self.states_lock = threading.Lock()
        self.client_states = {}
        self.storage_dir = storage_dir
        os.makedirs(storage_dir, exist_ok=True)
    
    def _get_client_context(self, address):
        """Get or create client state with its own lock"""
        with self.states_lock:
            if address not in self.client_states:
                self.client_states[address] = {
                    'lock': threading.Lock(),
                    'expected_seq': 0,
                    'current_operation': None,
                    'current_filename': None,
                    'file_handle': None,
                    'connected': False
                }
            return self.client_states[address]
    
    def handle_packet(self, data, address, server_socket):
        try:
            packet = RDTPacket.from_bytes(data)
            
            if not packet.verify_integrity():
                print(f"Packet from {address} failed integrity check")
                return
            
            # Get client context (which includes its lock)
            client_context = self._get_client_context(address)
            
            with client_context['lock']:
                self._process_packet_for_client(packet, address, server_socket, client_context)
                
        except Exception as e:
            print(f"Error processing packet from {address}: {e}")
    
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
            
            if packet.has_flag(RDTFlags.SYN):
                self.handle_syn(address, server_socket, client_state)
            elif packet.has_flag(RDTFlags.DATA):
                self.handle_data(packet, address, server_socket, client_state)
            elif packet.has_flag(RDTFlags.FIN):
                self.handle_fin(packet, address, server_socket, client_state)
                with self.states_lock:
                    if address in self.client_states:
                        del self.client_states[address]
            elif packet.has_flag(RDTFlags.ACK):
                self.handle_ack(packet, address, client_state)
                
        except Exception as e:
            print(f"Error processing packet from {address}: {e}")
    
    def handle_syn(self, address, server_socket, client_state):
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
                        if not prepare_upload_to_server(filepath, filename, server_socket, client_state, address):
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
                else: 
                    err_msg = create_error_packet(client_state.expected_seq, (f'002:OPERATION was not set correctly').encode())
                    # Send error response
                    server_socket.sendto(err_msg.to_bytes(), address)
                
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

def worker_logic(data, address, server_socket, rdt_protocol):
    try:
        rdt_protocol.handle_packet(data, address, server_socket)
    except Exception as e:
        print(f"Unexpected error: {e}")


def prepare_upload_to_server(filepath, filename, server_socket, client_state, address):
    try:
        client_state['file_handle'] = open(filepath, 'wb')
        print(f"Ready to receive upload: {filepath}")
        return True
    except Exception as e:
        print(f"Error creating file: {e}")
        err_msg = create_error_packet(client_state.expected_seq, (f'001:Could not create file with name {filename}').encode())
        # Send error response
        server_socket.sendto(err_msg.to_bytes(), address)
        return False

def main():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.bind((SERVER_IP, SERVER_PORT))
    
    rdt_protocol = RDTProtocol(storage_dir=STORAGE_DIR)
    
    print(f"RDT Server is running on {SERVER_IP}:{SERVER_PORT}")
    print(f"Files will be stored in: {STORAGE_DIR}/")
    
    pool = multiprocessing.pool.ThreadPool(processes=WORKERS)

    while True:
        try:
            data, address = server_socket.recvfrom(2048)
            pool.apply_async(worker_logic, (data, address, server_socket, rdt_protocol))
        except KeyboardInterrupt:
            print("\nServer shutting down...")
            pool.close()
            pool.join()
            break

if __name__ == "__main__":
    main()