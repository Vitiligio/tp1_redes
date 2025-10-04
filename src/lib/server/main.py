import multiprocessing
import multiprocessing.pool
import random
import socket
import os
import threading
import tempfile
import argparse
import sys
from lib.helpers.message import *
from lib.server_config import *
from contextlib import contextmanager
from lib.protocols.stop_and_wait import StopAndWaitProtocol
from lib.protocols.selective_repeat import SelectiveRepeatProtocol

class ReaderWriterLock:
    def __init__(self):
        self._read_ready = threading.Condition(threading.Lock())
        self._readers = 0
    
    def acquire_read(self):
        with self._read_ready:
            self._readers += 1
    
    def release_read(self):
        with self._read_ready:
            self._readers -= 1
            if self._readers == 0:
                self._read_ready.notify_all() 
    def acquire_write(self):
        self._read_ready.acquire()
        while self._readers > 0:
            self._read_ready.wait()
    
    def release_write(self):
        self._read_ready.release()

class FileLockManager:
    def __init__(self):
        self.file_locks = {}
        self.dict_lock = threading.Lock()
    
    @contextmanager
    def read_lock(self, filename):
        lock = self._get_lock(filename)
        lock.acquire_read()
        try:
            yield
        finally:
            lock.release_read()
    
    @contextmanager
    def write_lock(self, filename):
        lock = self._get_lock(filename)
        lock.acquire_write()
        try:
            yield
        finally:
            lock.release_write()
    
    def _get_lock(self, filename):
        with self.dict_lock:
            if filename not in self.file_locks:
                self.file_locks[filename] = ReaderWriterLock()
            return self.file_locks[filename]

class RDTProtocol:
    def __init__(self, storage_dir="server_files", verbose: bool = False):
        self.states_lock = threading.Lock()
        self.client_states = {}
        self.file_lock_manager = FileLockManager()
        self.storage_dir = storage_dir
        self.verbose = verbose
        os.makedirs(storage_dir, exist_ok=True)

    def _get_client_context(self, address):
        with self.states_lock:
            if address not in self.client_states:
                self.client_states[address] = {
                    'lock': threading.Lock(),
                    'expected_seq': 0,
                    'current_operation': None,
                    'current_filename': None,
                    'file_handle': None,
                    'connected': False,
                    'temp_file_path': None 
                }
            return self.client_states[address]

    def handle_packet(self, data, address, server_socket):
        try:
            print(f"Recibo paquete")
            
            packet = RDTPacket.from_bytes(data)
            if packet is None:
                print(f"ERROR")
                return 
            
            print(f"Paquete parseado. Flags: {packet.header.flags}, Seq: {packet.header.sequence_number}")
            
            client_context = self._get_client_context(address)
            
            with client_context['lock']:    
                print("Proceso paquete")
                self._process_packet_for_client(packet, address, server_socket, client_context)
            
        except Exception as e:
            print(f"ERROR: Excepcion procesando paquete: {e}")
    
    def _process_packet_for_client(self, packet, address, server_socket, client_state):
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
            self.handle_ack(packet, address, client_state, server_socket)
    
    def handle_syn(self, address, server_socket, client_state):
        print(f"SYN recibido desde {address}")
        
        syn_ack = create_sync_packet(0)
        syn_ack.set_flag(RDTFlags.ACK)
        server_socket.sendto(syn_ack.to_bytes(), address)
        
        client_state['connected'] = True
        client_state['expected_seq'] = 1
        print(f"Envio SYN-ACK a: {address}.")
    
    def handle_data(self, packet, address, server_socket, client_state):
        if not client_state['connected']:
            print(f"Error inesperado.")
            return

        expected_seq = client_state['expected_seq']
        seq_num = packet.header.sequence_number

        if client_state['current_operation'] is None:
            if expected_seq != 1 or seq_num != expected_seq:
                print(f"Error: esperado seq=1, recibi={seq_num}")
                return
            
            operation, filename, protocol = parse_operation_packet(packet)
            if operation and filename:
                client_state['current_operation'] = operation
                client_state['current_filename'] = filename
                client_state['protocol'] = protocol
                client_state['proto_name'] = protocol
                
                if protocol == "stop_and_wait":
                    client_state['proto'] = StopAndWaitProtocol(server_socket, verbose=self.verbose)
                    client_state['expected_seq'] = 0
                    client_state['proto'].external_ack_handling = True
                    client_state['proto'].current_seq = 0
                elif protocol == "selective_repeat":
                    client_state['proto'] = SelectiveRepeatProtocol(server_socket, verbose=self.verbose)
                    client_state['expected_seq'] = 2
                    client_state['proto'].current_seq = 2
                    client_state['proto'].external_ack_handling = True
                
                if self.verbose:
                    print(f"Operación {operation}. Archivo: {filename}. Protocolo: {protocol}")
                
                if operation == "UPLOAD":
                    if not self._prepare_upload(filename, server_socket, client_state, address):
                        return
                elif operation == "DOWNLOAD":
                    if not self._prepare_download(filename, server_socket, client_state, address):
                        return
        
            ack_packet = create_ack_packet(ack_num=seq_num)
            print(f"DEBUG SERVER: Proceso paquete. seq={seq_num}, expected_seq={expected_seq}, client_state_seq={client_state['expected_seq']}")
            server_socket.sendto(ack_packet.to_bytes(), address)
            return

        if client_state['proto_name'] == "stop_and_wait" and seq_num not in [0, 1]:
            print(f"Seq inesperado para Stop-and-Wait: {seq_num}")
            return
        elif client_state['proto_name'] == "selective_repeat" and seq_num < 2:
            print(f"Seq inesperado para Selective Repeat: {seq_num}")
            return
                    
        proto = client_state.get('proto')
        if proto is None:
            # no deberia pasar
            print("protocolo no encontrado")
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
        try:
            temp_file = tempfile.NamedTemporaryFile(dir=self.storage_dir, 
                                                   prefix=f".{filename}.upload.", 
                                                   delete=False)
            client_state['temp_file_path'] = temp_file.name
            client_state['file_handle'] = temp_file
            print(f"Guardando temporalmente en: {temp_file.name}")
            # ACK de la operación (seq=1)
            ack_packet = create_ack_packet(ack_num=1)
            server_socket.sendto(ack_packet.to_bytes(), address)
            return True
        except Exception as e:
            print(f"Error creando archivo temporal: {e}")
            err_msg = create_error_packet(client_state['expected_seq'], 
                                        f'001:Could not create file with name {filename}'.encode())
            server_socket.sendto(err_msg.to_bytes(), address)
            return False
    
    def _prepare_download(self, filename, server_socket, client_state, address):
        filepath = os.path.join(self.storage_dir, filename)
        
        try:
            with self.file_lock_manager.read_lock(filename):
                if not os.path.exists(filepath):
                    print(f"Archivo no encontrado: {filepath}")
                    err_msg = create_error_packet(client_state['expected_seq'], 
                                                f'003:Could not find file with name {filename}'.encode())
                    server_socket.sendto(err_msg.to_bytes(), address)
                    return False
                
                ack_packet = create_ack_packet(ack_num=1)
                server_socket.sendto(ack_packet.to_bytes(), address)
                print(f"Operación DOWNLOAD. Archivo: {filename}. Protocolo: {client_state['protocol']}")
                
                client_state['download_ready'] = True
                return True
                
        except Exception as e:
            print(f"Error inesperado: {e}")
            err_msg = create_error_packet(client_state['expected_seq'], 
                                        f'004:Error accessing file {filename}'.encode())
            server_socket.sendto(err_msg.to_bytes(), address)
            return False
    
    def _handle_upload_data(self, data, client_state, address, server_socket):
        if client_state.get('file_handle'):
            try:
                client_state['file_handle'].write(data)
            except Exception as e:
                print(f"Error: {e}")
                err_msg = create_error_packet(client_state['expected_seq'], 
                                            f'005:Error writing file data'.encode())
                server_socket.sendto(err_msg.to_bytes(), address)
    
    def handle_fin(self, packet, address, server_socket, client_state):
        print(f"FIN recibido")
        
        if (client_state.get('current_operation') == "UPLOAD" and 
            client_state.get('file_handle') and 
            client_state.get('current_filename')):
            
            self._finalize_upload(client_state)
        
        fin_ack = create_end_packet(0, seq_num=packet.header.sequence_number + 1)
        fin_ack.set_flag(RDTFlags.ACK)
        server_socket.sendto(fin_ack.to_bytes(), address)
        
        print(f"Conexión cerrada con {address}")
    
    def _finalize_upload(self, client_state):
        filename = client_state['current_filename']
        temp_path = client_state.get('temp_file_path')
        
        if not temp_path or not os.path.exists(temp_path):
            print(f"error: archivo temp no encontrado")
            return
        
        try:
            if client_state['file_handle']:
                client_state['file_handle'].close()
            
            with self.file_lock_manager.write_lock(filename):
                final_path = os.path.join(self.storage_dir, filename)
                
                if os.path.exists(final_path):
                    os.remove(final_path)
                
                os.rename(temp_path, final_path)
                
                print(f"Archivo subido: {filename}")
                
        except Exception as e:
            print(f"error inesperado")
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except:
                pass
    
    def handle_ack(self, packet, address, client_state, server_socket):
        print(f"ACK recibido desde: {address}, seq={packet.header.ack_number}")
        
        if (packet.header.ack_number == 1 and 
            client_state.get('download_ready') and 
            not client_state.get('download_started')):
            
            print(f"Cliente listo para DOWNLOAD. Iniciando envío de {client_state['current_filename']}")
            client_state['download_started'] = True
            
            def _send_job():
                try:
                    proto = client_state['proto']
                    filepath = os.path.join(self.storage_dir, client_state['current_filename'])
                    success = proto.send_file(filepath, address)
                    if success:
                        fin_ack = create_end_packet(0, seq_num=3)
                        server_socket.sendto(fin_ack.to_bytes(), address)
                        print(f"Descarga terminada. Archivo: {client_state['current_filename']}")
                    else:
                        print(f"Descarga de {client_state['current_filename']} fallida")
                except Exception as e:
                    print(f"Error en envio de descarga: {e}")
            
            t = threading.Thread(target=_send_job, daemon=True)
            t.start()
            return
        
        proto = client_state.get('proto')
        if proto is not None:
            try:
                proto.on_ack(packet)
            except Exception as e:
                print(f"Error procesando ACK en protocolo: {e}")

def worker_logic(data, address, server_socket, rdt_protocol):
    try:
        rdt_protocol.handle_packet(data, address, server_socket)
    except Exception as e:
        print(f"error: {e}")

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
        print(f"RDT Server corriendo en {host}:{port}")
        print(f"Destino: {storage}/")
    pool = multiprocessing.pool.ThreadPool(processes=WORKERS)
    while True:
        try:
            data, address = server_socket.recvfrom(2048)
            pool.apply_async(worker_logic, (data, address, server_socket, rdt_protocol))
        except KeyboardInterrupt:
            if not quiet:
                print("\nCerrando servidor")
            pool.close()
            pool.join()
            break
        except socket.timeout:
            continue
        except Exception as e:
            if not quiet:
                print(f"error: {e}")

if __name__ == "__main__":
    main()