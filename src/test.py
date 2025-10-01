#!/usr/bin/env python3
import logging
import sys
import time
import os
from mininet.net import Mininet
from mininet.node import Controller
from mininet.link import TCLink

# Set up logging configuration
def setup_logging():
    """Configure logging to file and console"""
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

# Define the absolute paths to your client and server scripts
CLIENT_SCRIPT = "/home/lied/Desktop/redes/tp1/src/upload"
SERVER_SCRIPT = '/home/lied/Desktop/redes/tp1/src/start-server'

def setup_concurrency_test():
    # Set up logging
    logger = setup_logging()
    logger.info("Starting Mininet concurrency test")
    
    # Create a network with 2 client hosts and 1 server host
    net = Mininet(controller=Controller, link=TCLink)
    net.addController('c0')

    # Add hosts
    server_host = net.addHost('server', ip='10.0.0.1')
    client1 = net.addHost('client1', ip='10.0.0.2')
    client2 = net.addHost('client2', ip='10.0.0.3')
    logger.info(f"Created hosts: server(10.0.0.1), client1(10.0.0.2), client2(10.0.0.3)")

    # Add links with 10% packet loss
    net.addLink(server_host, client1, cls=TCLink, loss=10)
    net.addLink(server_host, client2, cls=TCLink, loss=10)
    logger.info("Added links with 10% packet loss")

    # Start the network
    net.start()
    logger.info("Network started successfully")

    # Create log files for each host
    log_dir = "/tmp/mininet_test_logs"
    server_log = f"{log_dir}/server_{int(time.time())}.log"
    client1_log = f"{log_dir}/client1_{int(time.time())}.log" 
    client2_log = f"{log_dir}/client2_{int(time.time())}.log"

    # Create storage directory on server host
    server_storage = "/tmp/server_storage"
    server_host.cmd(f'mkdir -p {server_storage}')
    logger.info(f"Created server storage at: {server_storage}")

    # Start server with non-blocking socket fix
    logger.info("Starting server with verbose logging on 10.0.0.1:12000...")
    server_cmd = f'python3 {SERVER_SCRIPT} -H 10.0.0.1 -p 12000 -s {server_storage} -v > {server_log} 2>&1 &'
    logger.debug(f"Server command: {server_cmd}")
    server_host.cmd(server_cmd)
    
    # Wait longer for server to initialize with non-blocking socket
    logger.debug("Waiting 8 seconds for server to initialize with non-blocking socket...")
    time.sleep(8)
    
    # Verify server is running
    server_process_check = server_host.cmd('ps aux | grep "python3.*start-server" | grep -v grep')
    if server_process_check.strip():
        logger.info("Server process is running")
    else:
        logger.error("Server process is NOT running")
        net.stop()
        return

    # Create test files
    test_file1 = "/tmp/test_file1.bin"
    test_file2 = "/tmp/test_file2.bin"
    logger.info(f"Creating test files: {test_file1}, {test_file2}")
    
    # Create small test files for quick debugging
    client1.cmd(f'dd if=/dev/urandom of={test_file1} bs=1024 count=50 2>/dev/null')
    client2.cmd(f'dd if=/dev/urandom of={test_file2} bs=1024 count=50 2>/dev/null')
    
    file1_size = client1.cmd(f'wc -c < {test_file1} 2>/dev/null').strip()
    file2_size = client2.cmd(f'wc -c < {test_file2} 2>/dev/null').strip()
    logger.info(f"Test files created - File1: {file1_size} bytes, File2: {file2_size} bytes")

    # Client commands
    client1_cmd = (f'python3 {CLIENT_SCRIPT} -H 10.0.0.1 -p 12000 -s {test_file1} -n uploaded_1.bin -r stop_and_wait -v '
                   f'> {client1_log} 2>&1')
    
    client2_cmd = (f'python3 {CLIENT_SCRIPT} -H 10.0.0.1 -p 12000 -s {test_file2} -n uploaded_2.bin -r stop_and_wait -v '
                   f'> {client2_log} 2>&1')

    # Start Client 1
    logger.info("=== Starting Client 1 (Stop & Wait) ===")
    client1.cmd(client1_cmd + ' &')
    client1_pid = client1.cmd('echo $!').strip()
    logger.info(f"Client1 started with PID: {client1_pid}")
    
    # Wait 10 seconds before starting Client 2 to ensure server can handle second connection
    logger.info("Waiting 10 seconds before starting Client 2 to avoid socket contention...")
    time.sleep(10)
    
    # Start Client 2
    logger.info("=== Starting Client 2 (Selective Repeat) ===")
    client2.cmd(client2_cmd + ' &')
    client2_pid = client2.cmd('echo $!').strip()
    logger.info(f"Client2 started with PID: {client2_pid}")

    # Monitor both clients
    logger.info("Monitoring both clients for completion...")
    max_wait_time = 120
    check_interval = 5
    elapsed_time = 0
    
    while elapsed_time < max_wait_time:
        client1_running = client1.cmd(f'kill -0 {client1_pid} 2>/dev/null && echo "running" || echo "not running"').strip()
        client2_running = client2.cmd(f'kill -0 {client2_pid} 2>/dev/null && echo "running" || echo "not running"').strip()
        
        running_count = [client1_running, client2_running].count('running')
        
        if running_count == 0:
            logger.info("Both clients have completed")
            break
        else:
            remaining_time = max_wait_time - elapsed_time
            logger.info(f"Progress: {running_count}/2 clients running ({remaining_time}s remaining)")
            
            # Check server log for connection activity
            if elapsed_time % 10 == 0:
                server_activity = server_host.cmd(f'tail -5 {server_log} | grep -E "(SYN|connected|Connection)" | tail -3')
                if server_activity.strip():
                    logger.info(f"Server connection activity: {server_activity.strip()}")
        
        time.sleep(check_interval)
        elapsed_time += check_interval

    # Final checks
    logger.info("Waiting 5 seconds for server finalization...")
    time.sleep(5)
    
    logger.info("Checking server storage...")
    server_files = server_host.cmd(f'ls -la {server_storage}/')
    logger.info(f"Server storage:\n{server_files}")
    
    # Show key log sections
    logger.info("=== Server SYN/Connection Log ===")
    server_connections = server_host.cmd(f'grep -E "(SYN|connected|Connection)" {server_log} | tail -10')
    logger.info(server_connections)
    
    logger.info("Test completed")
    net.stop()

if __name__ == '__main__':
    setup_concurrency_test()