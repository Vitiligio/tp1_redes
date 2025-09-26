import socket
from helpers.message import RDTPacket, RDTFlags, create_ack_packet
from .base_protocol import BaseRDTProtocol

class StopAndWaitProtocol(BaseRDTProtocol):
    
    def __init__(self, socket: socket.socket, timeout: int = 5, max_retries: int = 3):
        super().__init__(socket, timeout)
        self.max_retries = max_retries
        self.current_seq = 0
        self.expected_seq = 0
    
    def send_packet(self, packet: RDTPacket, address):
        pass
    
    def receive_packet(self, expected_seq: int):
        pass
    
    def handle_timeout(self, seq_num: int) -> bool:
        pass
    
    def handle_duplicate(self, packet: RDTPacket) -> bool:
        pass
    
    def send_file(self, file_path: str, address):
        pass
    
    def receive_file(self, file_path: str) -> bool:
        pass
