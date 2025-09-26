import socket
from helpers.message import RDTPacket, RDTFlags, create_ack_packet
from .base_protocol import BaseRDTProtocol

class SelectiveRepeatProtocol(BaseRDTProtocol):
    
    def __init__(self, socket: socket.socket, timeout: int = 5, max_retries: int = 3, 
                 window_size: int = 4):
        super().__init__(socket, timeout)
        self.max_retries = max_retries
        self.window_size = window_size
        self.current_seq = 0
        self.expected_seq = 0
        self.send_window = {}  # {seq_num: packet}
        self.receive_window = {}  # {seq_num: packet}
        self.ack_received = {}  # {seq_num: bool}
    
    def send_packet(self, packet: RDTPacket, address: (str, int)) -> bool:
        # TODO: Implementar lógica de Selective Repeat
        # 1. Enviar paquete
        # 2. Agregar a send_window
        # 3. Iniciar timer si es necesario
        # 4. Retornar True si se puede enviar
        pass
    
    def receive_packet(self, expected_seq: int) -> RDTPacket:
        # TODO: Implementar lógica de recepción Selective Repeat
        # 1. Recibir paquete
        # 2. Verificar si está en ventana de recepción
        # 3. Enviar ACK selectivo
        # 4. Manejar reordenamiento
        pass
    
    def handle_timeout(self, seq_num: int) -> bool:
        # TODO: Implementar manejo de timeout
        # 1. Reenviar solo el paquete específico
        # 2. Reiniciar timer
        # 3. No afectar otros paquetes
        pass
    
    def handle_duplicate(self, packet: RDTPacket) -> bool:
        # TODO: Implementar manejo de duplicados
        # 1. Reenviar ACK
        # 2. Ignorar paquete
        pass
    
    def send_file(self, file_path: str, address: (str, int)) -> bool:
        # TODO: Implementar envío de archivo
        # 1. Leer archivo en chunks
        # 2. Enviar chunks hasta llenar ventana
        # 3. Manejar ACKs selectivos
        # 4. Deslizar ventana cuando sea posible
        pass
    
    def receive_file(self, file_path: str) -> bool:
        # TODO: Implementar recepción de archivo
        # 1. Recibir chunks en cualquier orden
        # 2. Almacenar en receive_window
        # 3. Escribir en orden cuando sea posible
        # 4. Enviar ACKs selectivos
        pass
    
    def slide_send_window(self):
        # TODO: Implementar deslizamiento de ventana
        # 1. Verificar ACKs recibidos
        # 2. Deslizar ventana
        # 3. Liberar espacio para nuevos paquetes
        pass
    
    def slide_receive_window(self):
        # TODO: Implementar deslizamiento de ventana de recepción
        # 1. Verificar paquetes en orden
        # 2. Deslizar ventana
        # 3. Liberar espacio para nuevos paquetes
        pass
