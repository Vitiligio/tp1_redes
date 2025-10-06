#!/usr/bin/env python3
import time
import os
from mininet.net import Mininet
from mininet.link import TCLink
from mininet.node import OVSBridge

CLIENT_SCRIPT = "/home/lied/Desktop/redes/tp1/src/upload"
SERVER_SCRIPT = '/home/lied/Desktop/redes/tp1/src/start-server'
SRC_PATH = "/home/lied/Desktop/redes/tp1/src"

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
    env['PYTHONPATH'] = f"{SRC_PATH}:{env.get('PYTHONPATH', '')}"
    server_proc = server_host.popen(
        [
            'python3', SERVER_SCRIPT,
            '-H', '10.0.0.1',
            '-p', '12000',
            '-s', server_storage,
            '-v'
        ],
        env=env,
        cwd=SRC_PATH,
        stdout=None,
        stderr=None
    )

    # pongo sleep para esperar a que levante el server
    time.sleep(5)

    test_file1 = "/home/lied/Downloads/file1.pdf"
    test_file2 = "/home/lied/Downloads/file2.pdf"
    
    client1.cmd(f'dd if=/dev/urandom of={test_file1} bs=1024 count=50 2>/dev/null')
    client2.cmd(f'dd if=/dev/urandom of={test_file2} bs=1024 count=50 2>/dev/null')
    
    file1_size = client1.cmd(f'wc -c < {test_file1} 2>/dev/null').strip()
    file2_size = client2.cmd(f'wc -c < {test_file2} 2>/dev/null').strip()

    client1_args = [
        'python3', CLIENT_SCRIPT,
        '-H', '10.0.0.1',
        '-p', '12000',
        '-s', test_file1,
        '-n', 'uploaded_1.pdf',
        '-r', 'stop_and_wait',
        '-v'
    ]
    client2_args = [
        'python3', CLIENT_SCRIPT,
        '-H', '10.0.0.1',
        '-p', '12000',
        '-s', test_file2,
        '-n', 'uploaded_2.pdf',
        '-r', 'selective_repeat',
        '-v'
    ]

    client1_proc = client1.popen(
        client1_args,
        env=env,
        cwd=SRC_PATH,
        stdout=None,
        stderr=None
    )
 
    client2_proc = client2.popen(
        client2_args,
        env=env,
        cwd=SRC_PATH,
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