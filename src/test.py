#!/usr/bin/env python3
import logging
import sys
import time
import os
import subprocess
from mininet.net import Mininet
from mininet.link import TCLink
from mininet.node import OVSBridge

def setup_logging():
    log_dir = "/tmp/mininet_test_logs"
    os.makedirs(log_dir, exist_ok=True)
    
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    
    file_handler = logging.FileHandler(f"{log_dir}/mininet_test_{int(time.time())}.log")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    
    logger.handlers.clear()
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

CLIENT_SCRIPT = "/home/vboxuser/Desktop/facultad/redes/tp1_redes/src/upload"
SERVER_SCRIPT = '/home/vboxuser/Desktop/facultad/redes/tp1_redes/src/start-server'

def setup_concurrency_test():
    logger = setup_logging()
    logger.info("Starting Mininet concurrency test")
    
    net = Mininet(link=TCLink, autoSetMacs=True, autoStaticArp=True, switch=OVSBridge, controller=None)

    server_host = net.addHost('server', ip='10.0.0.1')
    client1 = net.addHost('client1', ip='10.0.0.2')
    client2 = net.addHost('client2', ip='10.0.0.3')
    logger.info(f"Created hosts: server(10.0.0.1), client1(10.0.0.2), client2(10.0.0.3)")

    s1 = net.addSwitch('s1')
    net.addLink(server_host, s1, cls=TCLink, loss=10, delay='1ms', bw=100)
    net.addLink(client1, s1, cls=TCLink, loss=10, delay='1ms', bw=100)
    net.addLink(client2, s1, cls=TCLink, loss=10, delay='1ms', bw=100)
    logger.info("Added switch s1 and links with 10% packet loss, 1ms delay, 100Mbps bandwidth")

    net.start()
    logger.info("Network started successfully")

    log_dir = "/tmp/mininet_test_logs"
    server_log = f"{log_dir}/server_{int(time.time())}.log"
    client1_log = f"{log_dir}/client1_{int(time.time())}.log" 
    client2_log = f"{log_dir}/client2_{int(time.time())}.log"

    server_storage = "/tmp/server_storage"
    server_host.cmd(f'mkdir -p {server_storage}')
    logger.info(f"Created server storage at: {server_storage}")

    logger.info("Starting server with verbose logging on 10.0.0.1:12000...")
    env = os.environ.copy()
    env['PYTHONPATH'] = f"/home/vboxuser/Desktop/facultad/redes/tp1_redes/src:{env.get('PYTHONPATH', '')}"
    server_stdout = open(server_log, 'w')
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
        stdout=server_stdout,
        stderr=subprocess.STDOUT
    )
    logger.info(f"Server PID: {server_proc.pid}")
    
    logger.info("Waiting for server to initialize...")
    server_ready = False
    max_wait = 20
    wait_interval = 1
    
    for i in range(max_wait):
        time.sleep(wait_interval)
        
        if server_proc.poll() is not None:
            logger.warning(f"Server process not found at attempt {i+1}")
            continue
            
        port_check = server_host.cmd('netstat -tulpn 2>/dev/null | grep 12000')
        if '12000' in port_check:
            logger.info(f"Server is listening on port 12000 (attempt {i+1})")
            server_ready = True
            break
        else:
            logger.debug(f"Server not listening yet (attempt {i+1})")
    
    if not server_ready:
        logger.error("Server failed to start or listen on port 12000")
        logger.error(f"Server log content: {server_host.cmd(f'cat {server_log}')}")
        net.stop()
        return
    
    logger.info("Server is ready and listening")

    test_file1 = "/home/vboxuser/Downloads/cursor.deb"
    test_file2 = "/home/vboxuser/Downloads/cursorr.deb"
    logger.info(f"Creating test files: {test_file1}, {test_file2}")
    
    client1.cmd(f'dd if=/dev/urandom of={test_file1} bs=1024 count=50 2>/dev/null')
    client2.cmd(f'dd if=/dev/urandom of={test_file2} bs=1024 count=50 2>/dev/null')
    
    file1_size = client1.cmd(f'wc -c < {test_file1} 2>/dev/null').strip()
    file2_size = client2.cmd(f'wc -c < {test_file2} 2>/dev/null').strip()
    logger.info(f"Test files created - File1: {file1_size} bytes, File2: {file2_size} bytes")

    client1_stdout = open(client1_log, 'w')
    client2_stdout = open(client2_log, 'w')
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

    logger.info("Testing network connectivity...")
    ping_result = client1.cmd('ping -c 1 10.0.0.1')
    if '1 received' in ping_result:
        logger.info("Network connectivity OK")
    else:
        logger.warning("Network connectivity issues detected")
    
    logger.info("Testing packet loss with 10 pings...")
    ping_loss_test = client1.cmd('ping -c 10 10.0.0.1')
    logger.info(f"Ping loss test results:\n{ping_loss_test}")
    
    if 'packet loss' in ping_loss_test:
        logger.info("✅ Packet loss simulation is active")
    else:
        logger.warning("⚠️  Packet loss simulation may not be working")
    
    logger.info("=== Starting Client 1 (Stop & Wait) ===")
    client1_proc = client1.popen(
        client1_args,
        env=env,
        cwd='/home/vboxuser/Desktop/facultad/redes/tp1_redes/src',
        stdout=client1_stdout,
        stderr=subprocess.STDOUT
    )
 
    logger.info("=== Starting Client 2 (Selective Repeat) ===")
    client2_proc = client2.popen(
        client2_args,
        env=env,
        cwd='/home/vboxuser/Desktop/facultad/redes/tp1_redes/src',
        stdout=client2_stdout,
        stderr=subprocess.STDOUT
    )
 
    logger.info("Test completed")
    try:
        server_stdout.close()
        client1_stdout.close()
        client2_stdout.close()
    except Exception:
        pass
    net.stop()

if __name__ == '__main__':
    setup_concurrency_test()