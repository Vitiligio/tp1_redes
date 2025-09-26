ejecutar desde src con comandos
python3 -m server.main
python3 -m client.main

la logica

cliente manda sync
server manda sync + ack
cliente manda operation packet - agregar el stop&wait or selective repeat
server manda el ack

empieza el metodo que sea 

FALTA -

Server Multi thread

Conexion con servidor resulta mala desde el lado del cliente