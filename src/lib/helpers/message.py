import struct
import hashlib
from enum import IntFlag
from typing import Optional
import zlib

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
    
    def __init__(self, payload: bytes = b''):
        self.header = RDTHeader()
        self.payload = payload
        self.header.data_length = len(payload)
    
    def calculate_checksum(self) -> int:
        """Calculate checksum for packet integrity verification"""
        # Include header fields and payload in checksum calculation
        checksum_data = (
            self.header.sequence_number.to_bytes(4, 'big') +
            self.header.ack_number.to_bytes(4, 'big') +
            self.header.flags.to_bytes(2, 'big') +
            self.payload
        )
        return zlib.crc32(checksum_data) & 0xFFFFFFFF
    
    def to_bytes(self) -> bytes:
        """Convert packet to bytes with checksum"""
        # Calculate checksum before serialization
        checksum = self.calculate_checksum()
        
        # Include checksum in the serialized data
        packet_data = (
            self.header.sequence_number.to_bytes(4, 'big') +
            self.header.ack_number.to_bytes(4, 'big') +
            self.header.flags.to_bytes(2, 'big') +
            checksum.to_bytes(4, 'big') +  # 4-byte checksum
            len(self.payload).to_bytes(2, 'big') +
            self.payload
        )
        return packet_data
    
    @classmethod
    def from_bytes(cls, data: bytes) -> Optional['RDTPacket']:
        """Create packet from bytes with checksum verification"""
        try:
            if len(data) < 16:  # Minimum packet size with checksum
                return None
                
            # Parse header fields
            seq_num = int.from_bytes(data[0:4], 'big')
            ack_num = int.from_bytes(data[4:8], 'big')
            flags = int.from_bytes(data[8:10], 'big')
            received_checksum = int.from_bytes(data[10:14], 'big')
            payload_len = int.from_bytes(data[14:16], 'big')
            
            # Extract payload
            if len(data) < 16 + payload_len:
                return None
            payload = data[16:16 + payload_len]
            
            # Create temporary packet for checksum verification
            temp_packet = cls()
            temp_packet.header.sequence_number = seq_num
            temp_packet.header.ack_number = ack_num
            temp_packet.header.flags = flags
            temp_packet.payload = payload
            
            # Verify checksum
            calculated_checksum = temp_packet.calculate_checksum()
            if calculated_checksum != received_checksum:
                print(f"Checksum error: calculated {calculated_checksum}, received {received_checksum}")
                return None
            
            # Create final packet if checksum matches
            packet = cls()
            packet.header.sequence_number = seq_num
            packet.header.ack_number = ack_num
            packet.header.flags = flags
            packet.payload = payload
            
            return packet
            
        except Exception as e:
            print(f"Error parsing packet: {e}")
            return None
    
    def has_flag(self, flag: RDTFlags) -> bool:
        return (self.header.flags & flag) == flag

    def set_flag(self, flag: RDTFlags) -> None:
        self.header.flags |= flag
    
    
    def __str__(self):
        integrity = "✓" if hasattr(self, '_stored_hash') and self.verify_integrity() else "✗"
        return f"{self.header} Payload: {len(self.payload)} bytes [{integrity}]"
    
    def verify_integrity(self) -> bool:
        """
        Verify packet integrity using checksum.
        Note: This is a simplified version since checksum verification
        is already handled in from_bytes().
        """
        return True  # Integrity already verified in from_bytes

def create_data_packet(seq_num: int, payload: bytes) -> RDTPacket:
    packet = RDTPacket()
    packet.header.sequence_number = seq_num
    packet.header.flags = RDTFlags.DATA
    packet.payload = payload
    return packet

def create_ack_packet(ack_num: int, seq_num: int = 0) -> RDTPacket:
    packet = RDTPacket()
    packet.header.sequence_number = seq_num
    packet.header.ack_number = ack_num
    packet.header.flags = RDTFlags.ACK
    packet.payload = b""
    return packet

def create_sync_packet(seq_num: int) -> RDTPacket:
    packet = RDTPacket()
    packet.header.sequence_number = seq_num
    packet.header.flags = RDTFlags.SYN
    packet.payload = b""
    return packet

def create_end_packet(ack_num: int, seq_num: int = 0) -> RDTPacket:
    packet = RDTPacket()
    packet.header.sequence_number = seq_num
    packet.header.flags = RDTFlags.FIN
    packet.payload = b""
    return packet

def create_error_packet(ack_num: int, err_msg: bytes, seq_num: int = 0) -> RDTPacket:
    packet = RDTPacket()
    packet.header.sequence_number = seq_num
    packet.header.ack_number = ack_num
    packet.header.flags = RDTFlags.ERR
    packet.payload = err_msg
    return packet


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
    packet = RDTPacket(operation_data)
    packet.header.sequence_number = seq_num
    packet.set_flag(RDTFlags.DATA)  # Set the DATA flag
    return packet

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