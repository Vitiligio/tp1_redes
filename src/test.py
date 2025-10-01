#!/usr/bin/env python3
import logging
import sys
import time
import os
import subprocess
from mininet.net import Mininet
from mininet.link import TCLink
from mininet.node import OVSBridge

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
CLIENT_SCRIPT = "/home/vboxuser/Desktop/facultad/redes/tp1_redes/src/upload"
SERVER_SCRIPT = '/home/vboxuser/Desktop/facultad/redes/tp1_redes/src/start-server'

def setup_concurrency_test():
    # Set up logging
    logger = setup_logging()
    logger.info("Starting Mininet concurrency test")
    
    # Create a network with 2 client hosts and 1 server host
    net = Mininet(link=TCLink, autoSetMacs=True, autoStaticArp=True, switch=OVSBridge, controller=None)

    # Add hosts
    server_host = net.addHost('server', ip='10.0.0.1')
    client1 = net.addHost('client1', ip='10.0.0.2')
    client2 = net.addHost('client2', ip='10.0.0.3')
    logger.info(f"Created hosts: server(10.0.0.1), client1(10.0.0.2), client2(10.0.0.3)")

    # Add a switch and links with 10% packet loss and proper configuration for UDP
    s1 = net.addSwitch('s1')
    net.addLink(server_host, s1, cls=TCLink, loss=10, delay='1ms', bw=100)
    net.addLink(client1, s1, cls=TCLink, loss=10, delay='1ms', bw=100)
    net.addLink(client2, s1, cls=TCLink, loss=10, delay='1ms', bw=100)
    logger.info("Added switch s1 and links with 10% packet loss, 1ms delay, 100Mbps bandwidth")

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

    # Start server with proper Mininet configuration
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
    
    # Wait longer for server to initialize and verify it's ready
    logger.info("Waiting for server to initialize...")
    server_ready = False
    max_wait = 20  # Maximum 20 seconds
    wait_interval = 1
    
    for i in range(max_wait):
        time.sleep(wait_interval)
        
        # Check if server process is running
        if server_proc.poll() is not None:
            logger.warning(f"Server process not found at attempt {i+1}")
            continue
            
        # Check if server is listening on port 12000
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

    # Create test files
    test_file1 = "/home/vboxuser/Downloads/cursor.deb"
    test_file2 = "/home/vboxuser/Downloads/cursorr.deb"
    logger.info(f"Creating test files: {test_file1}, {test_file2}")
    
    # Create small test files for quick debugging
    client1.cmd(f'dd if=/dev/urandom of={test_file1} bs=1024 count=50 2>/dev/null')
    client2.cmd(f'dd if=/dev/urandom of={test_file2} bs=1024 count=50 2>/dev/null')
    
    file1_size = client1.cmd(f'wc -c < {test_file1} 2>/dev/null').strip()
    file2_size = client2.cmd(f'wc -c < {test_file2} 2>/dev/null').strip()
    logger.info(f"Test files created - File1: {file1_size} bytes, File2: {file2_size} bytes")

    # Prepare client popen commands and logs
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

    # Test network connectivity and packet loss
    logger.info("Testing network connectivity...")
    ping_result = client1.cmd('ping -c 1 10.0.0.1')
    if '1 received' in ping_result:
        logger.info("Network connectivity OK")
    else:
        logger.warning("Network connectivity issues detected")
    
    # Test packet loss with multiple pings
    logger.info("Testing packet loss with 10 pings...")
    ping_loss_test = client1.cmd('ping -c 10 10.0.0.1')
    logger.info(f"Ping loss test results:\n{ping_loss_test}")
    
    # Check if packet loss is working
    if 'packet loss' in ping_loss_test:
        logger.info("✅ Packet loss simulation is active")
    else:
        logger.warning("⚠️  Packet loss simulation may not be working")
    
    # Start Client 1
    logger.info("=== Starting Client 1 (Stop & Wait) ===")
    client1_proc = client1.popen(
        client1_args,
        env=env,
        cwd='/home/vboxuser/Desktop/facultad/redes/tp1_redes/src',
        stdout=client1_stdout,
        stderr=subprocess.STDOUT
    )
    logger.info(f"Client1 started with PID: {client1_proc.pid}")
    
    # Wait for Client 1 to establish connection before starting Client 2
    logger.info("Waiting for Client 1 to establish connection...")
    client1_connected = False
    for i in range(10):  # Wait up to 10 seconds
        time.sleep(1)
        # Check if client1 is still running (indicates it's working)
        if client1_proc.poll() is None:
            # Check if client1 log shows connection established
            client1_log_content = client1.cmd(f'cat {client1_log} 2>/dev/null')
            if 'Connection established!' in client1_log_content:
                logger.info("Client 1 connected successfully")
                client1_connected = True
                break
        logger.debug(f"Waiting for Client 1 connection (attempt {i+1})")
    
    if not client1_connected:
        logger.warning("Client 1 did not connect, but starting Client 2 anyway...")
    
    # Start Client 2
    logger.info("=== Starting Client 2 (Selective Repeat) ===")
    client2_proc = client2.popen(
        client2_args,
        env=env,
        cwd='/home/vboxuser/Desktop/facultad/redes/tp1_redes/src',
        stdout=client2_stdout,
        stderr=subprocess.STDOUT
    )
    logger.info(f"Client2 started with PID: {client2_proc.pid}")

    # Monitor both clients with detailed logging
    logger.info("Monitoring both clients for completion...")
    max_wait_time = 180  # Increased timeout
    check_interval = 3   # More frequent checks
    elapsed_time = 0
    
    while elapsed_time < max_wait_time:
        client1_running = client1_proc.poll() is None
        client2_running = client2_proc.poll() is None
        
        running_count = int(client1_running) + int(client2_running)
        
        if running_count == 0:
            logger.info("Both clients have completed")
            break
        else:
            remaining_time = max_wait_time - elapsed_time
            logger.info(f"Progress: {running_count}/2 clients running ({remaining_time}s remaining)")
            
            # Check client logs for progress
            if elapsed_time % 6 == 0:  # Every 18 seconds
                client1_log_tail = client1.cmd(f'tail -3 {client1_log} 2>/dev/null')
                client2_log_tail = client2.cmd(f'tail -3 {client2_log} 2>/dev/null')
                
                if client1_log_tail.strip():
                    logger.info(f"Client1 recent activity: {client1_log_tail.strip()}")
                if client2_log_tail.strip():
                    logger.info(f"Client2 recent activity: {client2_log_tail.strip()}")
                
                # Check server log for connection activity
                server_activity = server_host.cmd(f'tail -10 {server_log} 2>/dev/null | grep -E "(SYN|connected|Connection|ERROR)" | tail -3')
                if server_activity.strip():
                    logger.info(f"Server activity: {server_activity.strip()}")
        
        time.sleep(check_interval)
        elapsed_time += check_interval

    # Final checks and detailed analysis
    logger.info("Waiting 5 seconds for server finalization...")
    time.sleep(5)
    
    logger.info("=== FINAL RESULTS ===")
    
    # Check server storage
    logger.info("Checking server storage...")
    server_files = server_host.cmd(f'ls -la {server_storage}/')
    logger.info(f"Server storage:\n{server_files}")
    
    # Count successful uploads
    upload_count = server_host.cmd(f'find {server_storage} -name "*.bin" -o -name ".*.bin.*" | wc -l').strip()
    logger.info(f"Files in server storage: {upload_count}")
    
    # Show detailed client results
    logger.info("=== Client 1 Results ===")
    client1_final_log = client1.cmd(f'cat {client1_log} 2>/dev/null')
    logger.info(client1_final_log)
    
    logger.info("=== Client 2 Results ===")
    client2_final_log = client2.cmd(f'cat {client2_log} 2>/dev/null')
    logger.info(client2_final_log)
    
    # Show server activity
    logger.info("=== Server Activity Log ===")
    server_full_log = server_host.cmd(f'cat {server_log} 2>/dev/null')
    logger.info(server_full_log)
    
    # Determine test success
    success_count = 0
    if 'Upload completed successfully' in client1_final_log:
        success_count += 1
        logger.info("✅ Client 1 (Stop & Wait): SUCCESS")
    else:
        logger.info("❌ Client 1 (Stop & Wait): FAILED")
    
    if 'Upload completed successfully' in client2_final_log:
        success_count += 1
        logger.info("✅ Client 2 (Selective Repeat): SUCCESS")
    else:
        logger.info("❌ Client 2 (Selective Repeat): FAILED")
    
    logger.info(f"=== TEST SUMMARY: {success_count}/2 clients successful ===")
    
    if success_count == 2:
        logger.info("🎉 CONCURRENCY TEST PASSED!")
    elif success_count == 1:
        logger.info("⚠️  PARTIAL SUCCESS - One client worked")
    else:
        logger.info("❌ CONCURRENCY TEST FAILED - No clients worked")
    
    logger.info("Test completed")
    # Close file handles
    try:
        server_stdout.close()
        client1_stdout.close()
        client2_stdout.close()
    except Exception:
        pass
    net.stop()

if __name__ == '__main__':
    setup_concurrency_test()