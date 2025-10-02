import struct
import hashlib
from enum import IntFlag
from typing import Optional

class RDTFlags(IntFlag):
    """Flags del protocolo RDT"""
    SYN = 0x01
    ACK = 0x02
    FIN = 0x04
    DATA = 0x08
    ERR = 0x10

class RDTHeader:
    """
    0-3: sequence_number 
    4-7: ack_number 
    8-9: flags 
    10-11: data_length 
    """
    
    FORMAT = '!IIHH'
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
    MAX_PAYLOAD_SIZE = 1024
    
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
        if len(data) < RDTHeader.SIZE + 32:
            raise ValueError("Datos insuficientes para formar paquete")
        
        header = RDTHeader.from_bytes(data)
        payload_end = RDTHeader.SIZE + header.data_length
        payload = data[RDTHeader.SIZE:payload_end]
        
        expected_hash = data[-32:]
        actual_hash = cls._calculate_payload_hash(payload)
        
        packet = cls(header, payload)
        packet._stored_hash = expected_hash
        
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

def create_error_packet(ack_num: int, err_msg: bytes, seq_num: int = 0) -> RDTPacket:
    header = RDTHeader(sequence_number=seq_num, ack_number=ack_num, flags=RDTFlags.ERR)
    return RDTPacket(header, err_msg)

def parse_error_packet(packet: RDTPacket) -> tuple:
    if packet.payload:
        data_str = packet.payload.decode('utf-8')
        if ':' in data_str:
            parts = data_str.split(':', 2)
            code = parts[0]
            msg = parts[1]
            return code, msg
    return None, None, None

def create_operation_packet(seq_num: int, operation: str, filename: str, protocol: str = "stop_and_wait") -> RDTPacket:
    operation_data = f"{operation}:{filename}:{protocol}".encode('utf-8')
    header = RDTHeader(sequence_number=seq_num, flags=RDTFlags.DATA)
    return RDTPacket(header, operation_data)

def parse_operation_packet(packet: RDTPacket) -> tuple:
    if packet.payload:
        data_str = packet.payload.decode('utf-8')
        if ':' in data_str:
            parts = data_str.split(':', 2)
            if len(parts) >= 2:
                operation = parts[0].upper()
                filename = parts[1]
                protocol = parts[2] if len(parts) > 2 else "stop_and_wait"
                return operation, filename, protocol
    return None, None, None
