import time
import socket
import os
import argparse
import sys
import tempfile
import shutil
from lib.helpers.message import *
from lib.client_config import SERVER_IP, SERVER_PORT, SOCKET_TIMEOUT, PACKET_SIZE
from lib.protocols.stop_and_wait import StopAndWaitProtocol
from lib.protocols.selective_repeat import SelectiveRepeatProtocol

def connect_server(addr):
    connection_made = False
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client_socket.settimeout(SOCKET_TIMEOUT)

    sync_message = create_sync_packet(0)
    print(f"Conectando con servidor: {addr}")

    max_attempts = 10

    for attempt in range(1, max_attempts + 1):
        try:
            client_socket.sendto(sync_message.to_bytes(), addr)
            data, server = client_socket.recvfrom(1024)
            response_packet = RDTPacket.from_bytes(data)
            if response_packet.has_flag(RDTFlags.SYN) and response_packet.has_flag(RDTFlags.ACK):
                print("Conexión establecida")
                connection_made = True
                break
            else:
                print("Respuesta invalida")
        except socket.timeout:
            if attempt < max_attempts:
                print(f"Timeout - intento {attempt}/{max_attempts})")
            else:
                print('Timeout.')

    return connection_made, client_socket

def send_operation_request(client_socket, addr, operation: str, filename: str, protocol: str = "stop_and_wait"):
    operation_packet = create_operation_packet(seq_num=1, operation=operation, filename=filename, protocol=protocol)
    print(f"Enviando operacion: {operation}. Archivo: {filename}. Protocolo: {protocol}")

    max_attempts = 10

    for attempt in range(1, max_attempts + 1):
        try:
            client_socket.sendto(operation_packet.to_bytes(), addr)
            data, server = client_socket.recvfrom(1024)
            ack_packet = RDTPacket.from_bytes(data)
            if ack_packet.verify_integrity() and ack_packet.has_flag(RDTFlags.ACK):
                if ack_packet.header.ack_number == 1:
                    print("Operación ACKeada por servidor")
                    confirm_ack = create_ack_packet(ack_num=1)
                    client_socket.sendto(confirm_ack.to_bytes(), addr)
                    client_socket.settimeout(SOCKET_TIMEOUT)
                    return True
                else:
                    print(f"ACK inesperado: {ack_packet.header.ack_number}")
            else:
                print("ACK invalido")
        except socket.timeout:
            if attempt < max_attempts:
                print(f"Timeout - intento {attempt}/{max_attempts})")
            else:
                print('Timeout')
    return False

def upload_file(client_socket, addr, filename: str, protocol: str, verbose: bool = False):
    if protocol == "stop_and_wait":
        proto = StopAndWaitProtocol(client_socket, timeout=SOCKET_TIMEOUT, verbose=verbose)
        # For Stop-and-Wait, start file data at sequence 0
        proto.current_seq = 0
    elif protocol == "selective_repeat":
        proto = SelectiveRepeatProtocol(client_socket, timeout=SOCKET_TIMEOUT, verbose=verbose)
        proto.current_seq = 2
        # Selective Repeat manages its own sequence numbers internally
    else:
        if verbose: print(f"Protocolo no reconocido: {protocol}. Usando default stop_and_wait")
        proto = StopAndWaitProtocol(client_socket, timeout=SOCKET_TIMEOUT, verbose=verbose)
        proto.current_seq = 0
    
    return proto.send_file(filename, addr)

def download_file(client_socket, addr, filename: str, protocol: str, verbose: bool = False):
    if protocol == "stop_and_wait":
        proto = StopAndWaitProtocol(client_socket, timeout=SOCKET_TIMEOUT)
        proto.expected_seq = 0  # For Stop-and-Wait, expect file data to start at sequence 0
    elif protocol == "selective_repeat":
        proto = SelectiveRepeatProtocol(client_socket, timeout=SOCKET_TIMEOUT)
        proto.expected_seq = 2  # For Selective Repeat, keep expecting sequence 2
    else:
        if verbose: print(f"Pootocolo no reconocido: {protocol}. Usando default stop_and_wait")
        proto = StopAndWaitProtocol(client_socket, timeout=SOCKET_TIMEOUT)
        proto.expected_seq = 0
    
    print(f"Descargando: {filename} usando protocolo {protocol}")
    
    try:
        temp_file = tempfile.NamedTemporaryFile(prefix=f".{filename}.download.", 
                                               delete=False, 
                                               dir=".")
        temp_file_path = temp_file.name
        if verbose: print(f"Archivo tepmoral creado: {temp_file_path}")
    except Exception as e:
        print(f"Error creando archivo temporal: {e}")
        return False
    
    download_success = False
    file_handle = None
    
    try:
        file_handle = open(temp_file_path, 'wb')
        
        if verbose: print("Esperando data del server")
        
        bytes_received = 0
        start_time = time.time()
        
        while True:
            try:
                client_socket.settimeout(5.0)
                data, server_addr = client_socket.recvfrom(2048)
                packet = RDTPacket.from_bytes(data)
                
                if packet.verify_integrity():
                    if packet.has_flag(RDTFlags.DATA):
                        ack_num, data_to_write, new_expected = proto.on_data(packet)
                        
                        if data_to_write:
                            file_handle.write(data_to_write)
                            bytes_received += len(data_to_write)
                            if verbose:
                                print(f"Received {len(data_to_write)} bytes, total: {bytes_received}")
                        
                        ack_packet = create_ack_packet(ack_num=ack_num)
                        client_socket.sendto(ack_packet.to_bytes(), addr)
                        # proto.expected_seq = new_expected  # REMOVED - Protocol manages this internally
                        
                    elif packet.has_flag(RDTFlags.FIN):
                        if verbose:
                            print("Received FIN packet, download complete")
                        
                        fin_ack = create_ack_packet(ack_num=packet.header.sequence_number)
                        client_socket.sendto(fin_ack.to_bytes(), addr)
                        download_success = True
                        break
                    
                    elif packet.has_flag(RDTFlags.ERR):
                        error_msg = packet.payload.decode('utf-8', errors='ignore')
                        print(f"Error del serrver: {error_msg}")
                        break
                
            except socket.timeout:
                print("Timeout esperando data del servidor")
                break
            except Exception as e:
                print(f"Error recibiendo data: {e}")
                break
        
        transfer_time = time.time() - start_time
        if transfer_time > 0:
            if verbose:
                print(f"Descargados {bytes_received} bytes en {transfer_time:.2f}s")
        
    except Exception as e:
        print(f"Error {e}")
    finally:
        if file_handle:
            file_handle.close()
        
        if download_success:
            try:
                if os.path.exists(filename):
                    if verbose:
                        print(f"borro temp file: {filename}")
                    os.remove(filename)
                
                shutil.move(temp_file_path, filename)
                
                if os.path.exists(filename):
                    file_size = os.path.getsize(filename)
                    print(f"Descarga exitosa: {filename} - {file_size} bytes")
                    return True
                else:
                    print("Error")
                    return False
                    
            except Exception as e:
                print(f"Error {e}")
                try:
                    if os.path.exists(temp_file_path):
                        os.remove(temp_file_path)
                except:
                    pass
                return False
        else:
            try:
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
            except Exception as e:
                print(f"error: {e}")
            
            return False

def wait_for_fin_ack(client_socket, addr, timeout=3):
    max_attempts = 10
    for attempt in range(1, max_attempts + 1):
        try:
            client_socket.settimeout(timeout)
            data, server = client_socket.recvfrom(1024)
            fin_ack_packet = RDTPacket.from_bytes(data)
            if (fin_ack_packet.has_flag(RDTFlags.FIN) and fin_ack_packet.has_flag(RDTFlags.ACK)):
                return True
        except socket.timeout:
            if attempt < max_attempts:
                print(f"Timeout esperando FIN-ACK (intento{attempt}/{max_attempts})")
            else:
                print("Timeout esperando paquete FIN-ACK")
        except Exception as e:
            print(f"Error esperando FIN-ACK: {e}")
            break
    return False

def create_upload_parser():
    parser = argparse.ArgumentParser(
        description='Upload a file to the server',
        add_help=False
    )
    
    parser.add_argument('-h', '--help', action='store_true', 
                       help='show this help message and exit')
    parser.add_argument('-v', '--verbose', action='store_true', 
                       help='increase output verbosity')
    parser.add_argument('-q', '--quiet', action='store_true', 
                       help='decrease output verbosity')
    parser.add_argument('-H', '--host', type=str, default=SERVER_IP, 
                       help='server IP address')
    parser.add_argument('-p', '--port', type=int, default=SERVER_PORT, 
                       help='server port')
    parser.add_argument('-s', '--src', type=str, required=True,
                       help='source file path')
    parser.add_argument('-n', '--name', type=str, required=True,
                       help='file name on server')
    parser.add_argument('-r', '--protocol', type=str, 
                       choices=['stop_and_wait', 'selective_repeat'], 
                       default='stop_and_wait', 
                       help='error recovery protocol')
    
    return parser

def create_download_parser():
    parser = argparse.ArgumentParser(
        description='Download a file from the server',
        add_help=False
    )
    parser.add_argument('-h', '--help', action='store_true', 
                       help='show this help message and exit')
    parser.add_argument('-v', '--verbose', action='store_true', 
                       help='increase output verbosity')
    parser.add_argument('-q', '--quiet', action='store_true', 
                       help='decrease output verbosity')
    parser.add_argument('-H', '--host', type=str, default=SERVER_IP, 
                       help='server IP address')
    parser.add_argument('-p', '--port', type=int, default=SERVER_PORT, 
                       help='server port')
    parser.add_argument('-d', '--dst', type=str, 
                       help='destination file path')
    parser.add_argument('-n', '--name', type=str, required=True,
                       help='file name on server')
    parser.add_argument('-r', '--protocol', type=str, 
                       choices=['stop_and_wait', 'selective_repeat'], 
                       default='stop_and_wait', 
                       help='error recovery protocol')
    return parser

def validate_upload_args(args):
    if not os.path.exists(args.src):
        print(f"Error: el archivo '{args.src}' no existe")
        return False
    
    return True

def upload_main():
    parser = create_upload_parser()
    args = parser.parse_args()
    
    if args.help:
        parser.print_help()
        return
    
    if not validate_upload_args(args):
        return
    
    verbose = args.verbose
    quiet = args.quiet
    filename = args.name
    protocol = args.protocol
    
    host = args.host
    port = args.port
    addr = (host, port)
    
    if not quiet:
        print(f"Operacion: UPLOAD")
        print(f"Archivo: {filename}")
        print(f"Protocolo: {protocol}")
        print(f"Server: {addr}")
        print(f"Source: {args.src}")
    
    connection_made, client_socket = connect_server(addr)
    
    if connection_made:
        if send_operation_request(client_socket, addr, "UPLOAD", filename, protocol):
            success = upload_file(client_socket, addr, args.src, protocol, verbose)
            if success:
                if not quiet:
                    print("Upload completed successfully")
            else:
                print("Upload fallido")
        
        if not quiet:
            print("Cerrando conexión")
        
        max_fin_attempts = 5
        fin_packet = create_end_packet(ack_num=0, seq_num=100)
        fin_closed = False
        for attempt in range(1, max_fin_attempts + 1):
            client_socket.sendto(fin_packet.to_bytes(), addr)
            if wait_for_fin_ack(client_socket, addr, timeout=2):
                fin_closed = True
                if verbose:
                    print("Conexion cerrada correctamente")
                break
            else:
                if verbose:
                    if attempt < max_fin_attempts:
                        print(f"Timeout esperando FIN-ACK - intento {attempt}/{max_fin_attempts})")
                    else:
                        print("Servidor no respondio a FIN.")
    
    client_socket.close()

def download_main():
    parser = create_download_parser()
    args = parser.parse_args()
    

    if args.help:
        parser.print_help()
        return
    
    verbose = args.verbose
    quiet = args.quiet
    filename = args.name
    protocol = args.protocol
    dest_path = args.dst
    
    host = args.host
    port = args.port
    addr = (host, port)
    
    if not quiet:
        print(f"Operacion: DOWNLOAD")
        print(f"Archivo: {filename}")
        print(f"Protocolo: {protocol}")
        print(f"Server: {addr}")
        if dest_path:
            print(f"Destino: {dest_path}")
    
    connection_made, client_socket = connect_server(addr)
    
    if connection_made:
        if send_operation_request(client_socket, addr, "DOWNLOAD", filename, protocol):
            success = download_file(client_socket, addr, filename, protocol, verbose)
            if not success and not quiet:
                print("Descarga fallida")
        
        if not quiet:
            print("Conexión cerrada")
        
        fin_packet = create_end_packet(ack_num=0, seq_num=100)
        client_socket.sendto(fin_packet.to_bytes(), addr)
        
        if wait_for_fin_ack(client_socket, addr, timeout=2):
            if verbose:
                print("Conexión cerrada")
        else:
            if verbose:
                print("Servidor no respondio a FIN.")
    
    client_socket.close()