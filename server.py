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
        print_flush(f"Attempting to connect to robot at {SERVER_IP}:{SERVER_PORT}")
        robot_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        robot_socket.settimeout(5)
        robot_socket.connect((SERVER_IP, SERVER_PORT))
        robot_socket.settimeout(None)
        print_flush("Successfully connected to robot")
        update_status('connect', True)
        return True
    except Exception as e:
        print_flush(f"Failed to connect to robot: {str(e)}")
        if robot_socket:
            try:
                robot_socket.close()
            except:
                pass
            robot_socket = None
        update_status('connect', False)
        return False

def send_robot_command(command):
    """发送命令到机器人"""
    global robot_socket
    try:
        if not robot_socket:
            print_flush("No connection to robot")
            update_status(command, False)
            return False
            
        print_flush(f"Sending command: {command}")
        if not command.endswith('\n'):
            command = command + '\n'
        
        robot_socket.sendall(command.encode('utf-8'))
        print_flush("Command sent successfully")
        update_status(command, True)
        return True
    except Exception as e:
        print_flush(f"Failed to send command: {str(e)}")
        if robot_socket:
            try:
                robot_socket.close()
            except:
                pass
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
        print_flush(f"Video stream error: {str(e)}")
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

        print_flush(f"\n[Command Request] {'-'*50}")
        print_flush(f"Command: {command}")
        print_flush(f"Button: {button_id}")
        print_flush(f"Time: {timestamp}")
        print_flush(f"{'='*60}\n")
        
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
                    print_flush(f"Error closing connection: {str(e)}")
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
        print_flush(f"Error handling command: {error_msg}")
        return jsonify({
            'status': 'error',
            'message': error_msg,
            'status_info': update_status()
        })

if __name__ == '__main__':
    print_flush("\nStarting Robot Control Server...")
    print_flush(f"Server IP: {SERVER_IP}")
    print_flush(f"Robot Control Port: {SERVER_PORT}")
    print_flush(f"Video Stream Port: {VIDEO_PORT}")
    print_flush("\nWaiting for connections...\n")
    app.run(host='127.0.0.1', port=5000, debug=True)
