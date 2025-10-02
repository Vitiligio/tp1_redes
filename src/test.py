#!/usr/bin/env python3
import time
import os
from mininet.net import Mininet
from mininet.link import TCLink
from mininet.node import OVSBridge

CLIENT_SCRIPT = "/home/vboxuser/Desktop/facultad/redes/tp1_redes/src/upload"
SERVER_SCRIPT = '/home/vboxuser/Desktop/facultad/redes/tp1_redes/src/start-server'

def setup_concurrency_test():
    
    net = Mininet(link=TCLink, autoSetMacs=True, autoStaticArp=True, switch=OVSBridge, controller=None)

    server_host = net.addHost('server', ip='10.0.0.1')
    client1 = net.addHost('client1', ip='10.0.0.2')
    client2 = net.addHost('client2', ip='10.0.0.3')

    s1 = net.addSwitch('s1')
    net.addLink(server_host, s1, cls=TCLink, loss=10, delay='1ms', bw=100)
    net.addLink(client1, s1, cls=TCLink, loss=10, delay='1ms', bw=100)
    net.addLink(client2, s1, cls=TCLink, loss=10, delay='1ms', bw=100)

    net.start()

    server_storage = "/tmp/server_storage"
    server_host.cmd(f'mkdir -p {server_storage}')

    env = os.environ.copy()
    env['PYTHONPATH'] = f"/home/vboxuser/Desktop/facultad/redes/tp1_redes/src:{env.get('PYTHONPATH', '')}"
    server_proc = server_host.popen(
        [
            'python3', SERVER_SCRIPT,
            '-H', '10.0.0.1',
            '-p', '12000',
            '-s', server_storage,
            '-v'
        ],
        env=env,
        cwd='/home/vboxuser/Desktop/facultad/redes/tp1_redes/src',
        stdout=None,
        stderr=None
    )

    # pongo sleep para esperar a que levante el server
    time.sleep(5)

    test_file1 = "COMPLETAR ARCHIVO1"
    test_file2 = "COMPLETAR ARCHIVO2"
    
    client1.cmd(f'dd if=/dev/urandom of={test_file1} bs=1024 count=50 2>/dev/null')
    client2.cmd(f'dd if=/dev/urandom of={test_file2} bs=1024 count=50 2>/dev/null')
    
    file1_size = client1.cmd(f'wc -c < {test_file1} 2>/dev/null').strip()
    file2_size = client2.cmd(f'wc -c < {test_file2} 2>/dev/null').strip()

    client1_args = [
        'python3', CLIENT_SCRIPT,
        '-H', '10.0.0.1',
        '-p', '12000',
        '-s', test_file1,
        '-n', 'uploaded_1.bin',
        '-r', 'stop_and_wait',
        '-v'
    ]
    client2_args = [
        'python3', CLIENT_SCRIPT,
        '-H', '10.0.0.1',
        '-p', '12000',
        '-s', test_file2,
        '-n', 'uploaded_2.bin',
        '-r', 'selective_repeat',
        '-v'
    ]

    client1_proc = client1.popen(
        client1_args,
        env=env,
        cwd='/home/vboxuser/Desktop/facultad/redes/tp1_redes/src',
        stdout=None,
        stderr=None
    )
 
    client2_proc = client2.popen(
        client2_args,
        env=env,
        cwd='/home/vboxuser/Desktop/facultad/redes/tp1_redes/src',
        stdout=None,
        stderr=None
    )

    timeout_s = 120
    start = time.time()
    while time.time() - start < timeout_s:
        c1 = client1_proc.poll()
        c2 = client2_proc.poll()
        if c1 is not None and c2 is not None:
            break
        time.sleep(1)
 
    net.stop()

if __name__ == '__main__':
    setup_concurrency_test()