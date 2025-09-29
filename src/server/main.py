import multiprocessing
import multiprocessing.pool
import random
import socket
import os
import threading
import tempfile
import argparse
import sys
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

from protocols.stop_and_wait import StopAndWaitProtocol
from protocols.selective_repeat import SelectiveRepeatProtocol

class RDTProtocol:
    def __init__(self, storage_dir="server_files", verbose: bool = False):
        self.states_lock = threading.Lock()
        self.client_states = {}
        self.file_lock_manager = FileLockManager()
        self.storage_dir = storage_dir
        self.verbose = verbose
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
                    'connected': False,
                    'temp_file_path': None  # For atomic uploads
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
    
    def _process_packet_for_client(self, packet, address, server_socket, client_state):
        """Process packet while holding client-specific lock"""
        if packet.has_flag(RDTFlags.SYN):
            self.handle_syn(address, server_socket, client_state)
        elif packet.has_flag(RDTFlags.DATA):
            self.handle_data(packet, address, server_socket, client_state)
        elif packet.has_flag(RDTFlags.FIN):
            self.handle_fin(packet, address, server_socket, client_state)
            # Clean up client state
            with self.states_lock:
                if address in self.client_states:
                    del self.client_states[address]
        elif packet.has_flag(RDTFlags.ACK):
            self.handle_ack(packet, address, client_state)
    
    def handle_syn(self, address, server_socket, client_state):
        print(f"SYN received from {address}")
        
        # Send SYN-ACK
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
                    client_state['proto'] = StopAndWaitProtocol(server_socket, verbose=self.verbose)
                elif protocol == "selective_repeat":
                    client_state['proto'] = SelectiveRepeatProtocol(server_socket, verbose=self.verbose)
                
                print(f"Operation received: {operation} for file: {filename} using {protocol}")
                
                if operation == "UPLOAD":
                    if not self._prepare_upload(filename, server_socket, client_state, address):
                        return
                elif operation == "DOWNLOAD":
                    if not self._prepare_download(filename, server_socket, client_state, address):
                        return
                    
        proto = client_state.get('proto')
        if proto is None:
            print("Error: no protocol instance for client")
            err_msg = create_error_packet(client_state['expected_seq'], 
                                        '002:OPERATION was not set correctly'.encode())
            server_socket.sendto(err_msg.to_bytes(), address)
            return
        
        proto.expected_seq = client_state['expected_seq']
        ack_num, data_to_write, new_expected = proto.on_data(packet)
        
        if client_state['current_operation'] == "UPLOAD" and data_to_write:
            self._handle_upload_data(data_to_write, client_state, address, server_socket)
        
        ack_packet = create_ack_packet(ack_num=ack_num)
        server_socket.sendto(ack_packet.to_bytes(), address)
        client_state['expected_seq'] = new_expected
    
    def _prepare_upload(self, filename, server_socket, client_state, address):
        """Prepare for file upload with safe locking"""
        try:
            # Create temporary file for upload (atomic operation)
            temp_file = tempfile.NamedTemporaryFile(dir=self.storage_dir, 
                                                   prefix=f".{filename}.upload.", 
                                                   delete=False)
            client_state['temp_file_path'] = temp_file.name
            client_state['file_handle'] = temp_file
            print(f"Ready to receive upload to temporary file: {temp_file.name}")
            return True
        except Exception as e:
            print(f"Error creating temporary file for upload: {e}")
            err_msg = create_error_packet(client_state['expected_seq'], 
                                        f'001:Could not create file with name {filename}'.encode())
            server_socket.sendto(err_msg.to_bytes(), address)
            return False
    
    def _prepare_download(self, filename, server_socket, client_state, address):
        """Prepare for file download with safe locking"""
        filepath = os.path.join(self.storage_dir, filename)
        
        try:
            # Use read lock for safe concurrent downloads
            with self.file_lock_manager.read_lock(filename):
                if not os.path.exists(filepath):
                    print(f"Requested file not found: {filepath}")
                    err_msg = create_error_packet(client_state['expected_seq'], 
                                                f'003:Could not find file with name {filename}'.encode())
                    server_socket.sendto(err_msg.to_bytes(), address)
                    return False
                
                # Send ACK for operation packet
                ack_packet = create_ack_packet(ack_num=1)
                server_socket.sendto(ack_packet.to_bytes(), address)
                
                if client_state['proto'] is not None:
                    client_state['proto'].current_seq = 2
                    print(f"Starting download of {filepath} to {address}")
                    
                    # Send file with read lock held (entire file transfer protected)
                    success = client_state['proto'].send_file(filepath, address)
                    
                    if success:
                        fin_ack = create_end_packet(0, seq_num=3)
                        server_socket.sendto(fin_ack.to_bytes(), address)
                        print(f"Download finished for: {filename}")
                    else:
                        print(f"Download failed for: {filename}")
                    
                    try:
                        server_socket.settimeout(None)
                    except Exception:
                        pass
                return True
                
        except Exception as e:
            print(f"Error during download preparation: {e}")
            err_msg = create_error_packet(client_state['expected_seq'], 
                                        f'004:Error accessing file {filename}'.encode())
            server_socket.sendto(err_msg.to_bytes(), address)
            return False
    
    def _handle_upload_data(self, data, client_state, address, server_socket):
        """Handle incoming upload data safely"""
        if client_state.get('file_handle'):
            try:
                client_state['file_handle'].write(data)
                print(f"Received file data, wrote {len(data)} bytes to temporary file")
            except Exception as e:
                print(f"Error writing upload data: {e}")
                err_msg = create_error_packet(client_state['expected_seq'], 
                                            f'005:Error writing file data'.encode())
                server_socket.sendto(err_msg.to_bytes(), address)
    
    def handle_fin(self, packet, address, server_socket, client_state):
        print(f"FIN received from {address}")
        
        # Handle upload completion with safe file replacement
        if (client_state.get('current_operation') == "UPLOAD" and 
            client_state.get('file_handle') and 
            client_state.get('current_filename')):
            
            self._finalize_upload(client_state)
        
        # Send FIN-ACK
        fin_ack = create_end_packet(0, seq_num=packet.header.sequence_number + 1)
        server_socket.sendto(fin_ack.to_bytes(), address)
        
        print(f"Connection with {address} closed")
    
    def _finalize_upload(self, client_state):
        """Finalize upload with atomic file replacement using write lock"""
        filename = client_state['current_filename']
        temp_path = client_state.get('temp_file_path')
        
        if not temp_path or not os.path.exists(temp_path):
            print(f"Upload error: temporary file not found for {filename}")
            return
        
        try:
            # Close the temporary file
            if client_state['file_handle']:
                client_state['file_handle'].close()
            
            # Use write lock for atomic file replacement
            with self.file_lock_manager.write_lock(filename):
                final_path = os.path.join(self.storage_dir, filename)
                
                # Remove existing file if it exists
                if os.path.exists(final_path):
                    os.remove(final_path)
                
                # Atomically move temporary file to final location
                os.rename(temp_path, final_path)
                
                print(f"Upload completed and finalized for: {filename}")
                
        except Exception as e:
            print(f"Error finalizing upload for {filename}: {e}")
            # Clean up temporary file on error
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except:
                pass
    
    def handle_ack(self, packet, address, client_state):
        print(f"ACK received from {address} for seq={packet.header.ack_number}")

def worker_logic(data, address, server_socket, rdt_protocol):
    try:
        rdt_protocol.handle_packet(data, address, server_socket)
    except Exception as e:
        print(f"Unexpected error: {e}")

def create_parser():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('-h', '--help', action='store_true')
    parser.add_argument('-v', '--verbose', action='store_true')
    parser.add_argument('-q', '--quiet', action='store_true')
    parser.add_argument('-H', '--host', type=str, default=SERVER_IP)
    parser.add_argument('-p', '--port', type=int, default=SERVER_PORT)
    parser.add_argument('-s', '--storage', type=str, default=STORAGE_DIR)
    return parser

def main():
    parser = create_parser()
    args = parser.parse_args()
    if args.help:
        parser.print_help()
        return
    host = args.host
    port = args.port
    storage = args.storage
    quiet = args.quiet
    os.makedirs(storage, exist_ok=True)
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.bind((host, port))
    rdt_protocol = RDTProtocol(storage_dir=storage, verbose=args.verbose and not args.quiet)
    if not quiet:
        print(f"RDT Server is running on {host}:{port}")
        print(f"Files will be stored in: {storage}/")
    pool = multiprocessing.pool.ThreadPool(processes=WORKERS)
    while True:
        try:
            data, address = server_socket.recvfrom(2048)
            pool.apply_async(worker_logic, (data, address, server_socket, rdt_protocol))
        except KeyboardInterrupt:
            if not quiet:
                print("\nServer shutting down...")
            pool.close()
            pool.join()
            break
        except socket.timeout:
            continue
        except Exception as e:
            if not quiet:
                print(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()