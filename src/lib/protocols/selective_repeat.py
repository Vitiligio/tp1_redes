import socket
import time
from lib.helpers.message import RDTPacket, RDTFlags, create_ack_packet, create_data_packet
from .base_protocol import BaseRDTProtocol

class SelectiveRepeatProtocol(BaseRDTProtocol):
    
    def __init__(self, socket: socket.socket, timeout: int = 5, max_retries: int = 3, 
                 window_size: int = 8, verbose: bool = False):
        super().__init__(socket, timeout)

        self.max_retries = max_retries
        self.window_size = window_size
        self.verbose = verbose
        self.current_seq = 0
        self.expected_seq = 0
        self.send_window = {}
        self.receive_window = {}
        self.ack_received = {}
        self.duplicate_ack_count = {}
    
    def send_packet(self, packet: RDTPacket, address: tuple) -> bool:
        if len(self.send_window) >= self.window_size:
            return False
        
        seq_num = self.current_seq
        packet.header.sequence_number = seq_num
        packet.header.ack_number = 0
        
        try:
            self.socket.sendto(packet.to_bytes(), address)
            self.send_window[seq_num] = {
                'packet': packet,
                'address': address,
                'timestamp': time.time(),
                'retries': 0
            }
            self.ack_received[seq_num] = False
            self.duplicate_ack_count[seq_num] = 0
            self.current_seq = (self.current_seq + 1) % 65536
            return True
        except Exception as e:
            if self.verbose: print(f"Error {e}")
            return False
    
    def receive_packet(self) -> RDTPacket:
        try:
            data, address = self.socket.recvfrom(1024)
            packet = RDTPacket.from_bytes(data)
            
            if packet.has_flag(RDTFlags.ACK):
                self._handle_ack(packet)
                return packet
            elif packet.has_flag(RDTFlags.DATA):
                return self._handle_data_packet(packet, address)
            else:
                return packet
                
        except socket.timeout:
            return None
        except Exception as e:
            if self.verbose: print(f"Error {e}")
            return None
    
    def _fast_retransmit(self, seq_num: int):
        """Immediate retransmission on 3 duplicate ACKs:cite[8]"""
        if seq_num in self.send_window:
            window_entry = self.send_window[seq_num]
            if window_entry['retries'] < self.max_retries:
                try:
                    self.socket.sendto(window_entry['packet'].to_bytes(), window_entry['address'])
                    window_entry['retries'] += 1
                    window_entry['timestamp'] = time.time()
                    if self.verbose: print(f"Fast retransmit packet {seq_num}")
                except Exception as e:
                    if self.verbose: print(f"Error in fast retransmit: {e}")
    
    def _check_timeouts(self):
        """Check for timed out packets and retransmit"""
        current_time = time.time()
        
        for seq_num, entry in list(self.send_window.items()):
            if not self.ack_received.get(seq_num, False):
                if current_time - entry['timestamp'] > self.timeout:
                    if self.verbose: print(f"Timeout for packet {seq_num}")
                    self.handle_timeout(seq_num)

    def handle_timeout(self, seq_num: int) -> bool:
        if seq_num not in self.send_window:
            return False
        
        window_entry = self.send_window[seq_num]
        if window_entry['retries'] >= self.max_retries:
            if self.verbose: print(f"Maximos reintentos en seq: {seq_num}")
            del self.send_window[seq_num]
            del self.ack_received[seq_num]
            return False
        
        try:
            if self.verbose: print(f"Reintentando paquete {seq_num}")
            self.socket.sendto(window_entry['packet'].to_bytes(), window_entry['address'])
            window_entry['retries'] += 1
            window_entry['timestamp'] = time.time()
            return True
        except Exception as e:
            if self.verbose: print(f"Error en seq {seq_num}: {e}")
            return False
    
    def handle_duplicate(self, packet: RDTPacket) -> bool:
        if packet.has_flag(RDTFlags.ACK):
            ack_num = packet.header.ack_number
            if ack_num in self.ack_received and self.ack_received[ack_num]:
                return True
        return False
    
    def send_file(self, file_path: str, address: tuple) -> bool:
        try:
            with open(file_path, 'rb') as file:
                eof_reached = False
                base_seq = self.current_seq
                
                while not eof_reached or len(self.send_window) > 0:
                    # Fill sending window
                    while not eof_reached and len(self.send_window) < self.window_size:
                        chunk = file.read(1024)
                        if not chunk:
                            eof_reached = True
                            break
                        packet = create_data_packet(0, chunk) 
                        if not self.send_packet(packet, address):
                            break
                    
                    self.socket.settimeout(0.01)
                    try:
                        pkt = self.receive_packet()
                    except socket.timeout:
                        pkt = None
                    
                    self._check_timeouts()
                    
                    # Small delay to prevent CPU spinning
                    if not pkt and len(self.send_window) > 0:
                        time.sleep(0.001)
                
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
                    
                    if (packet.has_flag(RDTFlags.DATA)):
                        if self._can_deliver_packet(packet):
                            file.write(packet.payload)
                            self._slide_receive_window()
                        else:
                            self.receive_window[packet.header.sequence_number] = packet
                    
                    elif packet.has_flag(RDTFlags.FIN):
                        break
                return True
        except Exception as e:
            if self.verbose: print(f"Error {e}")
            return False
    
    def slide_send_window(self):
        """Slide window to remove acknowledged packets from the beginning"""
        min_seq = min(self.send_window.keys()) if self.send_window else 0
        
        while min_seq in self.ack_received and self.ack_received.get(min_seq, False):
            if min_seq in self.send_window:
                del self.send_window[min_seq]
            if min_seq in self.ack_received:
                del self.ack_received[min_seq]
            if min_seq in self.duplicate_ack_count:
                del self.duplicate_ack_count[min_seq]
            min_seq = (min_seq + 1) % 65536
    
    def slide_receive_window(self):
        while self.expected_seq in self.receive_window:
            packet = self.receive_window[self.expected_seq]
            del self.receive_window[self.expected_seq]
            self.expected_seq = (self.expected_seq + 1) % 65536
    
    def _handle_ack(self, packet: RDTPacket):
        ack_num = packet.header.ack_number
        if self.verbose: print(f"ACK recibido: {ack_num}")
        
        if ack_num in self.ack_received:
            if self.ack_received[ack_num]:
                self.duplicate_ack_count[ack_num] = self.duplicate_ack_count.get(ack_num, 0) + 1
                if self.duplicate_ack_count[ack_num] >= 3:
                    if self.verbose: print(f"Fast retransmit triggered for packet {ack_num}")
                    self._fast_retransmit(ack_num)
            else:
                self.ack_received[ack_num] = True
                self.duplicate_ack_count[ack_num] = 0
                self.slide_send_window()
    
    def _handle_data_packet(self, packet: RDTPacket, address: tuple) -> RDTPacket:
        ack_packet = create_ack_packet(packet.header.sequence_number, 0)
        try:
            self.socket.sendto(ack_packet.to_bytes(), address)
        except Exception as e:
            if self.verbose: print(f"Error enviando ACK {e}")
        
        return packet
    
    def _can_deliver_packet(self, packet: RDTPacket) -> bool:
        return packet.header.sequence_number == self.expected_seq
    
    def _fast_retransmit(self, seq_num: int):
        if seq_num in self.send_window:
            if self.verbose: print(f"Fast retransmit paquete {seq_num}")
            self.handle_timeout(seq_num)
    
    def _check_timeouts(self):
        current_time = time.time()
        to_remove: list[int] = []
        
        for seq_num, entry in list(self.send_window.items()):
            if current_time - entry['timestamp'] > self.timeout:
                if not self.handle_timeout(seq_num):
                    to_remove.append(seq_num)
        
        for seq_num in to_remove:
            if seq_num in self.send_window:
                del self.send_window[seq_num]
            if seq_num in self.ack_received:
                del self.ack_received[seq_num]

    def on_data(self, packet: RDTPacket):
        seq = packet.header.sequence_number
        base = self.expected_seq
        if (seq - base) % 65536 < self.window_size:
            self.receive_window[seq] = packet
        ack_num = seq
        data_to_write = b""
        while self.expected_seq in self.receive_window:
            p = self.receive_window.pop(self.expected_seq)
            data_to_write += p.payload
            self.expected_seq = (self.expected_seq + 1) % 65536
        return ack_num, data_to_write, self.expected_seq

    def on_ack(self, packet: RDTPacket) -> bool:
        if not packet.has_flag(RDTFlags.ACK):
            return False
        ack_num = packet.header.ack_number
        if ack_num in self.ack_received:
            if self.ack_received[ack_num]:
                self.duplicate_ack_count[ack_num] = self.duplicate_ack_count.get(ack_num, 0) + 1
                if self.duplicate_ack_count[ack_num] >= 3:
                    self._fast_retransmit(ack_num)
            else:
                self.ack_received[ack_num] = True
                self.duplicate_ack_count[ack_num] = 0
                self.slide_send_window()
            return True
        return False