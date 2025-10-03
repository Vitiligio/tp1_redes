from abc import ABC, abstractmethod
from typing import Optional, Tuple, Any
import socket
from lib.helpers.message import RDTPacket

class BaseRDTProtocol(ABC):
    """Clase base abstracta para protocolos RDT"""
    
    def __init__(self, socket: socket.socket, timeout: int = 5, verbose: bool = False):
        self.socket = socket
        self.verbose = verbose
        self.timeout = timeout
        self.socket.settimeout(timeout)
    
    @abstractmethod
    def send_packet(self, packet: RDTPacket, address: Tuple[str, int]) -> bool:
        """Envía un paquete al destino especificado"""
        pass
    
    @abstractmethod
    def receive_packet(self) -> Optional[RDTPacket]:
        """
        Recibe un paquete del socket.
        Returns:
            RDTPacket si se recibe un paquete válido, None en caso de timeout o error
        """
        pass
    
    @abstractmethod
    def handle_timeout(self, seq_num: int) -> bool:
        """Maneja timeout para un paquete específico"""
        pass
    
    @abstractmethod
    def send_file(self, file_path: str, address: Tuple[str, int]) -> bool:
        """Envía un archivo usando el protocolo"""
        pass
    
    @abstractmethod
    def on_data(self, packet: RDTPacket) -> Tuple[int, bytes, int]:
        """
        Procesa un paquete de datos recibido
        
        Args:
            packet: Paquete de datos recibido
            
        Returns:
            Tuple (ack_number, data_to_write, new_expected_seq)
        """
        pass
    
    @abstractmethod
    def on_ack(self, packet: RDTPacket) -> bool:
        """
        Procesa un paquete ACK recibido
        
        Args:
            packet: Paquete ACK recibido
            
        Returns:
            True si el ACK fue válido y procesado, False en caso contrario
        """
        pass