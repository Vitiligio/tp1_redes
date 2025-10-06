#!/usr/bin/env python3
import time
import os
from mininet.net import Mininet
from mininet.link import TCLink
from mininet.node import OVSBridge

CLIENT_SCRIPT = "/home/lied/Desktop/redes/tp1/src/upload"
SERVER_SCRIPT = '/home/lied/Desktop/redes/tp1/src/start-server'
SRC_PATH = "/home/lied/Desktop/redes/tp1/src"
SERVER_STORAGE = "/home/lied/Dekstop/redes/tp1/src/server_files"
SERVER_STORAGE = "/tmp/server_store"

def logs(client1_proc):
    timeout_s = 60*30
    start = time.time()
    while time.time() - start < timeout_s:
        c1 = client1_proc.poll()
        if c1 is not None:
            break
        time.sleep(1)

def wait_for_client(client_proc, timeout_s=60*30):
    start = time.time()
    while True:
        if client_proc.poll() is not None:
            return True 
        if time.time() - start > timeout_s:
            client_proc.terminate()
            return False  
        time.sleep(0.1)


def start_net(with_loss: int=0):

    net = Mininet(link=TCLink, autoSetMacs=True, autoStaticArp=True, switch=OVSBridge, controller=None)

    server_host = net.addHost('server', ip='10.0.0.1')
    client1 = net.addHost('client1', ip='10.0.0.2')

    s1 = net.addSwitch('s1')
    net.addLink(server_host, s1, cls=TCLink, loss=with_loss , delay='1ms', bw=100)
    net.addLink(client1, s1, cls=TCLink, loss=with_loss, delay='1ms', bw=100)

    net.start()
    return net, server_host, client1

def benchmark(protocol, with_loss: int=0):
    
    net, server_host, client1 = start_net(with_loss)
    server_storage = SERVER_STORAGE
    server_host.cmd(f'mkdir -p {server_storage}')
    server_host.cmd(f'chmod 755 {server_storage}')

    env = os.environ.copy()
    env['PYTHONPATH'] = f"{SRC_PATH}:{env.get('PYTHONPATH', '')}"
    server_proc = server_host.popen(
        [
            'python3', SERVER_SCRIPT,
            '-H', '10.0.0.1',
            '-p', '12000',
            '-s', server_storage,
            '-q'
        ],
        env=env,
        cwd=SRC_PATH,
        stdout=None,
        stderr=None
    )

    time.sleep(1)

    test_file1 = "/tmp/file2.pdf"

    start = time.perf_counter()

    client1.cmd(f'dd if=/dev/urandom of={test_file1} bs=1024 count=50 2>/dev/null')
    
    file1_size = client1.cmd(f'wc -c < {test_file1} 2>/dev/null').strip()

    client1_args = [
        'python3', CLIENT_SCRIPT,
        '-H', '10.0.0.1',
        '-p', '12000',
        '-s', test_file1,
        '-n', f'{protocol}-{with_loss}.pdf',
        '-r', protocol,
        '-q'
    ]

    client1_proc = client1.popen(
        client1_args,
        env=env,
        cwd=SRC_PATH,
        stdout=open(os.devnull, 'w'),
        stderr=open(os.devnull, 'w'),
    ) 

    #logs(client1_proc)
    wait_for_client(client1_proc)

    end = time.perf_counter()
    try:
        for filename in os.listdir(server_storage):
            file_path = os.path.join(server_storage, filename)
            if os.path.isfile(file_path):
                os.chmod(file_path, 0o666)
                print(f"Permissions changed for {file_path}")
    except Exception as e:
        print(f"Error changing permissions: {e}")

    net.stop()

    return f"Elapsed time: {end - start:.6f} seconds"

def main():
    test1 = benchmark("stop_and_wait", 0)
    test2 = benchmark("selective_repeat", 0)
    test3 = benchmark("stop_and_wait", 5)
    test4 = benchmark("selective_repeat", 5)
    test5 = benchmark("stop_and_wait", 10)
    test6 = benchmark("selective_repeat", 10)
    test7 = benchmark("stop_and_wait", 15)
    test8 = benchmark("selective_repeat", 15)
    test9 = benchmark("stop_and_wait", 20)
    test10 = benchmark("selective_repeat", 20)
    test11 = benchmark("stop_and_wait", 25)
    test12 = benchmark("selective_repeat", 25)

    print(f"TIME FOR ZERO LOSS -- PROTOCOL STOP AND WAIT -- {test1}")
    print(f"TIME FOR ZERO LOSS -- PROTOCOL SELECTIVE REPEAT -- {test2}")
    print(f"TIME FOR 5%  LOSS -- PROTOCOL STOP AND WAIT -- {test3}")
    print(f"TIME FOR 5%  LOSS -- PROTOCOL SELECTIVE REPEAT -- {test4}")
    print(f"TIME FOR 10%  LOSS -- PROTOCOL STOP AND WAIT -- {test5}")
    print(f"TIME FOR 10%  LOSS -- PROTOCOL SELECTIVE REPEAT -- {test6}")
    print(f"TIME FOR 15%  LOSS -- PROTOCOL STOP AND WAIT -- {test7}")
    print(f"TIME FOR 15%  LOSS -- PROTOCOL SELECTIVE REPEAT -- {test8}")

    print(f"TIME FOR 20%  LOSS -- PROTOCOL STOP AND WAIT -- {test9}")
    print(f"TIME FOR 20%  LOSS -- PROTOCOL SELECTIVE REPEAT -- {test10}")
    print(f"TIME FOR 25%  LOSS -- PROTOCOL STOP AND WAIT -- {test11}")
    print(f"TIME FOR 25%  LOSS -- PROTOCOL SELECTIVE REPEAT -- {test12}")


if __name__ == '__main__':
    main()