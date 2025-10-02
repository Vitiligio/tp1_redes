import socket
import time
import os
from lib.helpers.message import RDTPacket, RDTFlags, create_ack_packet, create_data_packet
from .base_protocol import BaseRDTProtocol

class StopAndWaitProtocol(BaseRDTProtocol):
    
    def __init__(self, socket: socket.socket, timeout: int = 5, max_retries: int = 3, verbose: bool = False):
        super().__init__(socket, timeout)
        self.max_retries = max_retries
        self.verbose = verbose
        self.current_seq = 0
        self.expected_seq = 0
        self.last_sent_packet = None
        self.last_sent_address = None
        self.retries = 0

    def send_packet(self, packet: RDTPacket, address: (str, int)) -> bool:
        packet.header.sequence_number = self.current_seq
        packet.header.ack_number = 0
        
        try:
            self.socket.sendto(packet.to_bytes(), address)
            self.last_sent_packet = packet
            self.last_sent_address = address
            return True
        except Exception as e:
            if self.verbose: print(f"Error enviando paquete {e}")
            return False

    def receive_packet(self, expected_seq: int = None) -> RDTPacket:
        try:
            data, address = self.socket.recvfrom(1024)
            packet = RDTPacket.from_bytes(data)

            if not packet.verify_integrity():
                if self.verbose: print(f"Paquete fallo integridad. {address}")
                return None
            
            # esto puede traer problemas con perdida de paquetes
            if packet.has_flag(RDTFlags.ACK):
                if packet.header.ack_number == self.current_seq:
                    self.current_seq = (self.current_seq + 1) % 65536
                    self.retries = 0
                    self.last_sent_packet = None
                    self.last_sent_address = None
                return packet
            elif packet.has_flag(RDTFlags.DATA):
                if packet.header.sequence_number == self.expected_seq:
                    ack_packet = create_ack_packet(packet.header.sequence_number, 0)
                    self.socket.sendto(ack_packet.to_bytes(), address)
                    self.expected_seq = (self.expected_seq + 1) % 65536
                else:
                    ack_packet = create_ack_packet(self.expected_seq - 1, 0)
                    self.socket.sendto(ack_packet.to_bytes(), address)
                return packet
            else:
                return packet
                
        except socket.timeout:
            return None
        except Exception as e:
            if self.verbose: print(f"Error {e}")
            return None
    
    def handle_timeout(self, seq_num: int) -> bool:
        if self.last_sent_packet is None or self.last_sent_address is None:
            return False
        
        if self.retries >= self.max_retries:
            if self.verbose: print(f"Maximos reintentos en seq: {seq_num}")
            return False
        
        try:
            self.socket.sendto(self.last_sent_packet.to_bytes(), self.last_sent_address)
            self.retries += 1
            return True
        except Exception as e:
            if self.verbose: print(f"Error de paquete: {e}")
            return False
    
    def handle_duplicate(self, packet: RDTPacket) -> bool:
        if packet.has_flag(RDTFlags.ACK):
            return packet.header.ack_number == self.current_seq - 1
        return False
    
    def send_file(self, file_path: str, address: (str, int)) -> bool:
        if not os.path.exists(file_path):
            if self.verbose: print(f"Archivo {file_path} no encontrado")
            return False
        
        if self.verbose: print(f"Empiezo upload de {file_path}")

        try:
            with open(file_path, 'rb') as file:
                while True:
                    chunk = file.read(1024)
                    if not chunk:
                        break
                    
                    packet = create_data_packet(0, chunk)
                    
                    while True:
                        if self.send_packet(packet, address):
                            ack_received = False
                            start_time = time.time()
                            
                            while not ack_received and (time.time() - start_time) < self.timeout:
                                received_packet = self.receive_packet()
                                if received_packet and received_packet.has_flag(RDTFlags.ACK):
                                    if received_packet.header.ack_number == self.current_seq -1:
                                        if self.verbose: print(f"Recibido ACK={self.current_seq -1}")
                                        ack_received = True
                                    else:
                                        if self.verbose: print(f"ACK inesperado. Esperado: {self.current_seq}, got {received_packet.header.ack_number}")
                                        self.handle_duplicate(received_packet)
                            
                            if ack_received:
                                break
                            else:
                                if not self.handle_timeout(self.current_seq - 1):
                                    return False
                        else:
                            return False
                
                return True
        except Exception as e:
            if self.verbose: print(f"Error {e}")
            return False
    
    def receive_file(self, file_path: str) -> bool:
        try:
            with open(file_path, 'wb') as file:
                while True:
                    packet = self.receive_packet()
                    if packet is None:
                        continue
                    
                    if packet.has_flag(RDTFlags.DATA):
                        if packet.header.sequence_number == self.expected_seq:
                            file.write(packet.payload)
                        else:
                            self.handle_duplicate(packet)
                    
                    elif packet.has_flag(RDTFlags.FIN):
                        break
                
                return True
        except Exception as e:
            if self.verbose: print(f"Error recibiendo archivo. {e}")
            return False

    def on_data(self, packet: RDTPacket):
        if packet.header.sequence_number == self.expected_seq:
            ack_num = packet.header.sequence_number
            data_to_write = packet.payload
            self.expected_seq = (self.expected_seq + 1) % 65536
            return ack_num, data_to_write, self.expected_seq
        prev_seq = self.expected_seq - 1 if self.expected_seq > 0 else 0
        return prev_seq, b"", self.expected_seq

    def on_ack(self, packet: RDTPacket) -> bool:
        if not packet.has_flag(RDTFlags.ACK):
            return False
        if packet.header.ack_number == self.current_seq:
            self.current_seq = (self.current_seq + 1) % 65536
            return True
        return packet.header.ack_number == (self.current_seq - 1)
