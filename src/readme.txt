ejecutar desde src con comandos
python3 -m server.main
python3 -m client.main

FUNCA - python3 -m client.main download -n test.txt

la logica

cliente manda sync
server manda sync + ack
cliente manda operation packet - agregar el stop&wait or selective repeat
server manda el ack

empieza el metodo que sea 

FALTA -

Server Multi thread

Conexion con servidor resulta mala desde el lado del cliente

If server could not create file, sends a package to the client with the error flag and the error description on the body


ERROR MESSAGES

SERVER - 001:Could not create file with name {filename}
SERVER - 002:OPERATION was not set correctly
SERVER - 003:Could not find file with name {filename}
