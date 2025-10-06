import socket
import time
import os
from lib.helpers.message import RDTPacket, RDTFlags, create_ack_packet, create_data_packet
from .base_protocol import BaseRDTProtocol

class StopAndWaitProtocol(BaseRDTProtocol):
    
    def __init__(self, socket: socket.socket, timeout: int = 0.3, max_retries: int = 60, verbose: bool = False):
        super().__init__(socket, timeout)
        self.max_retries = max_retries
        self.verbose = verbose
        self.current_seq = 0
        self.expected_seq = 0
        self.last_sent_packet = None
        self.last_sent_address = None
        self.retries = 0
        self._pending_ack_for_current = False
        self.external_ack_handling = False

    def send_packet(self, packet: RDTPacket, address: (str, int)) -> bool:
        packet.header.ack_number = 0
        try:
            print(f"DEBUG CLIENT: Actually sending packet seq={packet.header.sequence_number}")
            self.socket.sendto(packet.to_bytes(), address)
            self.last_sent_packet = packet
            self.last_sent_address = address
            return True
        except Exception as e:
            if self.verbose: print(f"Error enviando paquete {e}")
            return False

    def receive_packet(self) -> RDTPacket:
        try:
            data, address = self.socket.recvfrom(1024)
            packet = RDTPacket.from_bytes(data)

            if not packet.verify_integrity():
                if self.verbose: print(f"Paquete fallo integridad. {address}")
                return None
            
            if packet.has_flag(RDTFlags.ACK):
                if self.verbose: print(f"DEBUG CLIENT: Received ACK={packet.header.ack_number}, current_seq={self.current_seq}")
                return packet
            elif packet.has_flag(RDTFlags.DATA):
                print(f"DEBUG CLIENT: Received seq={packet.header.sequence_number}, current_seq={self.current_seq}, will become {(self.current_seq + 1) % 2}")
                if packet.header.sequence_number == self.expected_seq:
                    ack_packet = create_ack_packet(packet.header.sequence_number, 0)
                    self.socket.sendto(ack_packet.to_bytes(), address)
                    self.expected_seq = (self.expected_seq + 1) % 2
                    if self.verbose: print(f"DATA aceptado, seq: {packet.header.sequence_number}, nuevo expected_seq: {self.expected_seq}")
                else:
                    ack_packet = create_ack_packet((self.expected_seq - 1) % 2, 0)
                    self.socket.sendto(ack_packet.to_bytes(), address)
                    if self.verbose: print(f"DATA fuera de secuencia. Esperado: {self.expected_seq}, Recibido: {packet.header.sequence_number}")
                return packet
            else:
                if self.verbose: print(f"DEBUG CLIENT: QUE ONDA NO TENGO NINGUN FLAG")

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
            if self.verbose: print(f"Reintento {self.retries} para seq: {seq_num}")
            return True
        except Exception as e:
            if self.verbose: print(f"Error de paquete: {e}")
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
                    if self.verbose: print(f"DEBUG CLIENT: Sending chunk with seq={self.current_seq}, file_pos={file.tell()}")
                    packet = create_data_packet(self.current_seq, chunk)
                    
                    while True:
                        if self.send_packet(packet, address):
                            ack_received = False
                            start_time = time.time()
                            
                            while not ack_received and (time.time() - start_time) < self.timeout:
                                if self.external_ack_handling:
                                    if self._pending_ack_for_current:
                                        ack_received = True
                                        break
                                    time.sleep(0.001)
                                    continue
                                received_packet = self.receive_packet()
                                if received_packet and received_packet.has_flag(RDTFlags.ACK):
                                    if received_packet.header.ack_number == self.current_seq:
                                        if self.verbose: print(f"Recibido ACK correcto para seq={self.current_seq}")
                                        self._pending_ack_for_current = True
                                        ack_received = True
                                        break
                                    else:
                                        if self.verbose: print(f"ACK inesperado. Esperado: {self.current_seq}, recibido: {received_packet.header.ack_number}")
                            
                            if ack_received:
                                self._pending_ack_for_current = False
                                self.current_seq = (self.current_seq + 1) % 2
                                self.retries = 0
                                self.last_sent_packet = None
                                self.last_sent_address = None
                                break
                            else:
                                if not self.handle_timeout(self.current_seq):
                                    if self.verbose: print(f"Fallo max reintentos para seq: {self.current_seq}")
                                    return False
                        else:
                            return False
                
                return True
        except Exception as e:
            if self.verbose: print(f"Error {e}")
            return False
        
    def on_data(self, packet: RDTPacket):
        if packet.header.sequence_number == self.expected_seq:
            ack_num = packet.header.sequence_number
            data_to_write = packet.payload
            self.expected_seq = (self.expected_seq + 1) % 2
            if self.verbose: print(f"DATA aceptado, seq: {packet.header.sequence_number}, nuevo expected_seq: {self.expected_seq}")
            return ack_num, data_to_write, self.expected_seq
        else:
            prev_seq = (self.expected_seq - 1) % 2
            if self.verbose: print(f"DATA rechazado - fuera de secuencia. Esperado: {self.expected_seq}, Recibido: {packet.header.sequence_number}")
            return prev_seq, b"", self.expected_seq

    def on_ack(self, packet: RDTPacket) -> bool:
        """Process an incoming ACK packet"""
        if not packet.has_flag(RDTFlags.ACK):
            return False
            
        if packet.header.ack_number == self.current_seq:
            if self.verbose: 
                print(f"ACK correcto recibido para seq: {self.current_seq}")
            self._pending_ack_for_current = True
            self.retries = 0
            return True
        else:
            if self.verbose: 
                print(f"ACK duplicado o fuera de secuencia. Esperado: {self.current_seq}, Recibido: {packet.header.ack_number}")
            return False