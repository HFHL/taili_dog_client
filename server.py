from flask import Flask, render_template, Response, jsonify, request
import cv2
import numpy as np
import requests
import threading
import logging
import socket
import time
import sys
from datetime import datetime

app = Flask(__name__)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Configuration
SERVER_IP = "192.168.2.34"
SERVER_PORT = 8082
VIDEO_PORT = 8080

# Global variables
video_thread = None
running = False
bytes_data = b""
robot_socket = None
last_command_time = None
connection_status = {
    'connected': False,
    'last_command': None,
    'last_command_time': None,
    'total_commands': 0,
    'failed_commands': 0
}

def print_flush(*args, **kwargs):
    """立即打印并刷新输出"""
    print(*args, **kwargs)
    sys.stdout.flush()

def update_status(command=None, success=True):
    """更新状态信息"""
    global connection_status
    current_time = time.strftime('%H:%M:%S')
    
    if command:
        connection_status['last_command'] = command
        connection_status['last_command_time'] = current_time
        connection_status['total_commands'] += 1
        if not success:
            connection_status['failed_commands'] += 1
    
    connection_status['connected'] = bool(robot_socket)
    connection_status['current_time'] = current_time
    
    return connection_status

def connect_to_robot():
    """连接到机器人"""
    global robot_socket
    try:
        logging.info(f"Attempting to connect to robot at {SERVER_IP}:{SERVER_PORT}")
        
        # 检查IP地址格式
        try:
            socket.inet_aton(SERVER_IP)
        except socket.error:
            logging.error(f"Invalid IP address format: {SERVER_IP}")
            raise ValueError(f"Invalid IP address: {SERVER_IP}")

        # 检查端口范围
        if not (0 <= SERVER_PORT <= 65535):
            logging.error(f"Invalid port number: {SERVER_PORT}")
            raise ValueError(f"Port number must be between 0 and 65535")

        # 创建socket
        try:
            robot_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            logging.info("Socket created successfully")
        except socket.error as se:
            logging.error(f"Failed to create socket: {str(se)}")
            raise

        # 设置socket选项
        try:
            robot_socket.settimeout(5)
            # 设置keep-alive
            robot_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            # 设置非阻塞模式
            robot_socket.setblocking(True)
        except socket.error as se:
            logging.error(f"Failed to set socket options: {str(se)}")
            raise

        # 尝试连接
        try:
            robot_socket.connect((SERVER_IP, SERVER_PORT))
        except socket.timeout:
            logging.error("Connection attempt timed out")
            raise TimeoutError("Connection timed out - server may be down or unreachable")
        except ConnectionRefusedError:
            logging.error("Connection refused by server")
            raise ConnectionRefusedError("Server actively refused connection - check if server is running and port is correct")
        except PermissionError as pe:
            logging.error(f"Permission denied: {str(pe)}")
            raise PermissionError("Permission denied - try running as administrator")
        except socket.gaierror as ge:
            logging.error(f"Address-related error: {str(ge)}")
            raise
        except socket.error as se:
            logging.error(f"Socket error during connect: {str(se)}")
            raise

        # 连接成功后的设置
        robot_socket.settimeout(None)
        logging.info("Successfully connected to robot")
        
        # 测试连接是否真正建立
        try:
            robot_socket.getpeername()
            logging.info("Connection verified")
        except socket.error:
            logging.error("Connection verification failed")
            raise ConnectionError("Connection appeared to succeed but verification failed")

        update_status('connect', True)
        return True

    except Exception as e:
        logging.error(f"Connection failed: {str(e)}")
        if robot_socket:
            try:
                robot_socket.close()
                logging.info("Socket closed after error")
            except Exception as close_error:
                logging.error(f"Error while closing socket: {str(close_error)}")
            finally:
                robot_socket = None
        
        update_status('connect', False)
        return False

def send_robot_command(command):
    """发送命令到机器人"""
    global robot_socket
    try:
        if not robot_socket:
            logging.error("No connection to robot")
            update_status(command, False)
            return False

        if not isinstance(command, str):
            logging.error(f"Invalid command type: {type(command)}, expected string")
            raise TypeError("Command must be a string")
            
        logging.info(f"Sending command: {command}")
        
        # 确保命令格式正确
        if not command.strip():
            logging.error("Empty command")
            raise ValueError("Command cannot be empty")
            
        if not command.endswith('\n'):
            command = command + '\n'
        
        # 尝试发送命令
        try:
            bytes_sent = robot_socket.sendall(command.encode('utf-8'))
            logging.info(f"Command sent successfully: {command.strip()}")
        except UnicodeEncodeError as ue:
            logging.error(f"Command encoding error: {str(ue)}")
            raise
        except socket.timeout:
            logging.error("Send timeout")
            raise TimeoutError("Send operation timed out")
        except ConnectionResetError:
            logging.error("Connection reset by peer")
            raise ConnectionResetError("Connection was reset - server may have closed connection")
        except BrokenPipeError:
            logging.error("Broken pipe")
            raise BrokenPipeError("Connection broken - server may have closed connection")
        except socket.error as se:
            logging.error(f"Socket error while sending: {str(se)}")
            raise

        update_status(command, True)
        return True

    except Exception as e:
        logging.error(f"Failed to send command: {str(e)}")
        if robot_socket:
            try:
                robot_socket.close()
                logging.info("Socket closed after send error")
            except Exception as close_error:
                logging.error(f"Error while closing socket: {str(close_error)}")
            finally:
                robot_socket = None
        
        update_status(command, False)
        return False

def generate_frames():
    """生成视频帧"""
    global bytes_data, running
    running = True
    video_url = f"http://{SERVER_IP}:{VIDEO_PORT}"
    
    try:
        with requests.get(video_url, stream=True, timeout=5) as response:
            if response.status_code == 200:
                while running:
                    chunk = response.raw.read(1024)
                    if not chunk or not running:
                        break
                    
                    bytes_data += chunk
                    a = bytes_data.find(b'\xff\xd8')
                    b = bytes_data.find(b'\xff\xd9')
                    
                    if a != -1 and b != -1:
                        jpg = bytes_data[a:b+2]
                        bytes_data = bytes_data[b+2:]
                        frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                        if frame is not None:
                            ret, buffer = cv2.imencode('.jpg', frame)
                            if ret:
                                frame = buffer.tobytes()
                                yield (b'--frame\r\n'
                                      b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
    except Exception as e:
        logging.error(f"Video stream error: {str(e)}")
    finally:
        running = False

@app.route('/')
def index():
    """渲染主页"""
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    """视频流端点"""
    return Response(generate_frames(),
                   mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/status', methods=['GET'])
def get_status():
    """获取当前状态"""
    return jsonify(update_status())

@app.route('/api/command', methods=['POST'])
def handle_command():
    """处理命令请求"""
    try:
        data = request.get_json()
        command = data.get('command')
        button_id = data.get('button_id')
        timestamp = data.get('timestamp')

        logging.info(f"\n[Command Request] {'-'*50}")
        logging.info(f"Command: {command}")
        logging.info(f"Button: {button_id}")
        logging.info(f"Time: {timestamp}")
        logging.info(f"{'='*60}\n")
        
        if command == 'connect':
            success = connect_to_robot()
            return jsonify({
                'status': 'success' if success else 'error',
                'status_info': update_status()
            })
        elif command == 'disconnect':
            global robot_socket
            if robot_socket:
                try:
                    robot_socket.close()
                except Exception as e:
                    logging.error(f"Error closing connection: {str(e)}")
                robot_socket = None
            return jsonify({
                'status': 'success',
                'status_info': update_status()
            })
        else:
            if not robot_socket:
                return jsonify({
                    'status': 'error',
                    'message': 'Not connected to robot',
                    'status_info': update_status()
                })
            
            success = send_robot_command(command)
            return jsonify({
                'status': 'success' if success else 'error',
                'message': 'Command sent' if success else 'Failed to send command',
                'status_info': update_status()
            })
            
    except Exception as e:
        error_msg = str(e)
        logging.error(f"Error handling command: {error_msg}")
        return jsonify({
            'status': 'error',
            'message': error_msg,
            'status_info': update_status()
        })

if __name__ == '__main__':
    logging.info("\nStarting Robot Control Server...")
    logging.info(f"Server IP: {SERVER_IP}")
    logging.info(f"Robot Control Port: {SERVER_PORT}")
    logging.info(f"Video Stream Port: {VIDEO_PORT}")
    logging.info("\nWaiting for connections...\n")
    app.run(host='127.0.0.1', port=5000, debug=True)
