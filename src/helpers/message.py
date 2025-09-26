import struct
import hashlib
from enum import IntFlag
from typing import Optional

class RDTFlags(IntFlag):
    """Flags del protocolo RDT"""
    SYN = 0x01      # Sincronización
    ACK = 0x02      # Acuse de recibo  
    FIN = 0x04      # Finalización
    DATA = 0x08     # Datos
    ERR = 0x10      # Error

class RDTHeader:
    """
    Improved RDT Header (12 bytes - more efficient)
    0-3: sequence_number (uint32)
    4-7: ack_number (uint32) 
    8-9: flags (uint16)
    10-11: data_length (uint16)
    """
    
    FORMAT = '!IIHH'  # 4+4+2+2 = 12 bytes (more efficient)
    SIZE = struct.calcsize(FORMAT)
    
    def __init__(self, 
                 sequence_number: int = 0,
                 ack_number: int = 0,
                 flags: int = 0,
                 data_length: int = 0):
        self.sequence_number = sequence_number
        self.ack_number = ack_number
        self.flags = flags
        self.data_length = data_length
    
    def to_bytes(self) -> bytes:
        return struct.pack(self.FORMAT,
                          self.sequence_number,
                          self.ack_number,
                          self.flags,
                          self.data_length)
    
    @classmethod
    def from_bytes(cls, data: bytes) -> 'RDTHeader':
        if len(data) < cls.SIZE:
            raise ValueError(f"Header incompleto: {len(data)} bytes < {cls.SIZE}")
        return cls(*struct.unpack(cls.FORMAT, data[:cls.SIZE]))

class RDTPacket:
    MAX_PAYLOAD_SIZE = 1024  # 1KB por paquete
    
    def __init__(self, header: RDTHeader, payload: bytes = b''):
        self.header = header
        self.payload = payload
        self.header.data_length = len(payload)
    
    def to_bytes(self) -> bytes:
        """Serializa: header + payload + checksum (hash del payload)"""
        payload_hash = self._calculate_payload_hash(self.payload)
        return self.header.to_bytes() + self.payload + payload_hash
    
    @classmethod
    def from_bytes(cls, data: bytes) -> 'RDTPacket':
        """Deserializa verificando integridad"""
        if len(data) < RDTHeader.SIZE + 32:  # header + MD5 hash (32 chars hex)
            raise ValueError("Datos insuficientes para formar paquete")
        
        header = RDTHeader.from_bytes(data)
        payload_end = RDTHeader.SIZE + header.data_length
        payload = data[RDTHeader.SIZE:payload_end]
        
        # Verificar checksum (últimos 32 bytes son el hash MD5)
        expected_hash = data[-32:]  # Los últimos 32 bytes del paquete completo
        actual_hash = cls._calculate_payload_hash(payload)
        
        packet = cls(header, payload)
        packet._stored_hash = expected_hash  # Guardar para verificación
        
        return packet
    
    def has_flag(self, flag: RDTFlags) -> bool:
        return (self.header.flags & flag) == flag

    def set_flag(self, flag: RDTFlags) -> None:
        self.header.flags |= flag
    
    @staticmethod
    def _calculate_payload_hash(payload: bytes = None) -> bytes:
        """Calcula MD5 hash del payload y lo convierte a hex ASCII"""
        if payload is None:
            payload = b''
        return hashlib.md5(payload).hexdigest().encode('ascii')
    
    def verify_integrity(self) -> bool:
        """Verifica que el payload no fue corrupto durante transmisión"""
        if not hasattr(self, '_stored_hash'):
            return False
        
        actual_hash = self._calculate_payload_hash(self.payload)
        return self._stored_hash == actual_hash
    
    def __str__(self):
        integrity = "✓" if hasattr(self, '_stored_hash') and self.verify_integrity() else "✗"
        return f"{self.header} Payload: {len(self.payload)} bytes [{integrity}]"

def create_data_packet(seq_num: int, data: bytes) -> RDTPacket:
    header = RDTHeader(sequence_number=seq_num, flags=RDTFlags.DATA)
    return RDTPacket(header, data)

def create_ack_packet(ack_num: int, seq_num: int = 0) -> RDTPacket:
    header = RDTHeader(sequence_number=seq_num, ack_number=ack_num, flags=RDTFlags.ACK)
    return RDTPacket(header)

def create_sync_packet(ack_num: int, seq_num: int = 0) -> RDTPacket:
    header = RDTHeader(sequence_number=seq_num, ack_number=ack_num, flags=RDTFlags.SYN)
    return RDTPacket(header)

def create_end_packet(ack_num: int, seq_num: int = 0) -> RDTPacket:
    header = RDTHeader(sequence_number=seq_num, ack_number=ack_num, flags=RDTFlags.FIN)
    return RDTPacket(header)

def create_operation_packet(seq_num: int, operation: str, filename: str) -> RDTPacket:
    """Create packet for operation specification (UPLOAD/DOWNLOAD + filename)"""
    operation_data = f"{operation}:{filename}".encode('utf-8')
    header = RDTHeader(sequence_number=seq_num, flags=RDTFlags.DATA)
    return RDTPacket(header, operation_data)

def parse_operation_packet(packet: RDTPacket) -> tuple:
    """Parse operation packet into (operation, filename)"""
    if packet.payload:
        data_str = packet.payload.decode('utf-8')
        if ':' in data_str:
            operation, filename = data_str.split(':', 1)
            return operation.upper(), filename
    return None, None
