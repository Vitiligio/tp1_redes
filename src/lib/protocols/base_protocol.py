from abc import ABC, abstractmethod
from typing import Optional, Tuple
import socket
from lib.helpers.message import RDTPacket

class BaseRDTProtocol:
    """Clase base abstracta para protocolos RDT"""
    
    def __init__(self, socket: socket.socket, timeout: int = 5, verbose: bool = False):
        self.socket = socket
        self.verbose = verbose
        self.timeout = timeout
        self.socket.settimeout(timeout)
    
    @abstractmethod
    def send_packet(self, packet: RDTPacket, address: Tuple[str, int]) -> bool:
        pass
    
    @abstractmethod
    def receive_packet(self, expected_seq: int) -> Optional[RDTPacket]:
        pass
    
    @abstractmethod
    def handle_timeout(self, seq_num: int) -> bool:
        pass
    
    @abstractmethod
    def handle_duplicate(self, packet: RDTPacket) -> bool:
        pass
