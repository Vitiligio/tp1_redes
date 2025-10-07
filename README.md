# TP1 Redes - File Transfer Application

## Alumnos
- **Martín Palazón** - Padrón 102679
- **Sebastián Martín Pagura** - Padrón 102649

## Comandos de Ejecución

### 1. Iniciar el Servidor
```bash
python3 start-server [-h] [-v | -q] [-H ADDR] [-p PORT] [-s DIRPATH]
```

**Parámetros:**
- `-h, --help`: Mostrar mensaje de ayuda
- `-v, --verbose`: Aumentar verbosidad de salida
- `-q, --quiet`: Disminuir verbosidad de salida
- `-H, --host`: Dirección IP del servidor (default: 127.0.0.1)
- `-p, --port`: Puerto del servidor (default: 12000)
- `-s, --storage`: Directorio de almacenamiento (default: server_files)

**Ejemplo:**
```bash
python3 start-server -H 127.0.0.1 -p 12000 -s ./server_files -v
```

### 2. Upload
```bash
python3 upload [-h] [-v | -q] [-H ADDR] [-p PORT] [-s FILEPATH] [-n FILENAME] [-r PROTOCOL]
```

**Parámetros:**
- `-h, --help`: Mostrar mensaje de ayuda
- `-v, --verbose`: Aumentar verbosidad de salida
- `-q, --quiet`: Silenciar la salida
- `-H, --host`: Dirección IP del servidor
- `-p, --port`: Puerto del servidor
- `-s, --src`: Ruta del archivo fuente (requerido)
- `-n, --name`: Nombre del archivo en el servidor (requerido)
- `-r, --protocol`: Protocolo (stop_and_wait | selective_repeat)

**Ejemplo:**
```bash
python3 upload -H 127.0.0.1 -p 12000 -s ./video.mp4 -n video.mp4 -r stop_and_wait -v

python3 upload -H 127.0.0.1 -p 12000 -s ./documento.pdf -n doc.pdf -r selective_repeat
```

### 3. Descarga
```bash
python3 download [-h] [-v | -q] [-H ADDR] [-p PORT] [-d FILEPATH] [-n FILENAME] [-r PROTOCOL]
```

**Parámetros:**
- `-h, --help`: Mostrar mensaje de ayuda
- `-v, --verbose`: Aumentar verbosidad de salida
- `-q, --quiet`: Silenciar la salida
- `-H, --host`: Dirección IP del servidor
- `-p, --port`: Puerto del servidor
- `-d, --dst`: Ruta de destino del archivo (opcional)
- `-n, --name`: Nombre del archivo en el servidor (requerido)
- `-r, --protocol`: Protocolo (stop_and_wait | selective_repeat)

**Ejemplos:**
```bash
python3 download -H 127.0.0.1 -p 12000 -n video.mp4 -r stop_and_wait -v

python3 download -H 127.0.0.1 -p 12000 -d ./downloads/ -n doc.pdf -r selective_repeat
```


## Configuraciones

### Configuración del cliente (`client_config.py`)
```python
SERVER_IP = "127.0.0.1"   
SERVER_PORT = 12000       
SOCKET_TIMEOUT = 0.08     
PACKET_SIZE = 1400
```

### Configuración del servidor (`server_config.py`)
```python
SERVER_IP = "127.0.0.1"
SERVER_PORT = 12000
WORKERS = 3
SOCKET_TIMEOUT = 0.08
STORAGE_DIR = "server_files"
PACKET_SIZE = 1400
```

## Estructura de Paquetes

### Header del Paquete RDT
El protocolo utiliza un header fijo de **16 bytes** con la siguiente estructura:

| Campo | Bytes | Descripción |
|-------|-------|-------------|
| `sequence_number` | 4 | Número de secuencia del paquete |
| `ack_number` | 4 | Número de ACK |
| `flags` | 2 | Flags del protocolo |
| `checksum` | 4 | Verificación de integridad |
| `payload_length` | 2 | Longitud del payload en bytes |

### Flags Disponibles
- `SYN (0x01)`: Sincronización de conexión
- `ACK (0x02)`: Confirmación de recepción
- `FIN (0x04)`: Finalización de conexión
- `DATA (0x08)`: Datos del archivo
- `ERR (0x10)`: Mensaje de error

### Tamaños de Paquete
- **Tamaño del header**: 16 bytes
- **Tamaño del payload**: Hasta 1024 bytes
- **Tamaño del paquete**: Hasta 1040 bytes (16 + 1024).

