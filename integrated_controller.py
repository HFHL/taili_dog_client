import sys
from PyQt5.QtWidgets import (QApplication, QWidget, QPushButton, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout)
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt5.QtNetwork import QTcpSocket
import requests
import cv2
import numpy as np

# 视频流处理线程类
class StreamThread(QThread):
    frame_received = pyqtSignal(np.ndarray)  # 信号用于传递视频帧

    def __init__(self, url):
        super().__init__()
        self.url = url
        self.running = True  # 控制线程是否继续运行
        self.bytes_data = b""  # 缓冲区存储接收的字节流

    def run(self):
        try:
            # 发起HTTP请求，持续读取视频流数据
            with requests.get(self.url, stream=True, timeout=5) as response:
                for chunk in response.iter_content(chunk_size=1024):
                    if not self.running:
                        break

                    # 累加字节流数据
                    self.bytes_data += chunk
                    a = self.bytes_data.find(b'\xff\xd8')  # JPEG起始标志
                    b = self.bytes_data.find(b'\xff\xd9')  # JPEG结束标志

                    # 当发现完整的JPEG图像时，解码并发送信号
                    if a != -1 and b != -1:
                        jpg = self.bytes_data[a:b+2]
                        self.bytes_data = self.bytes_data[b+2:]
                        frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                        if frame is not None:
                            self.frame_received.emit(frame)  # 发送图像帧
        except Exception as e:
            print(f"Stream error: {e}")

    def stop(self):
        """停止线程"""
        self.running = False
        self.quit()
        self.wait()

# 主窗口：集成视频流与机器人控制
class RobotControlUI(QWidget):
    def __init__(self, server_ip, server_port, video_port):
        super().__init__()

        # 服务器配置
        self.server_ip = server_ip
        self.server_port = server_port
        self.video_port = video_port

        # 初始化TCP Socket
        self.socket = QTcpSocket(self)
        self.socket.connected.connect(self.on_connected)
        self.socket.disconnected.connect(self.on_disconnected)
        self.socket.errorOccurred.connect(self.on_error)

        # 命令发送定时器
        self.command_timer = QTimer()
        self.command_timer.timeout.connect(self.send_current_command)
        self.current_command = None

        # 初始化UI
        self.initUI()

        # 初始化视频流线程
        self.stream_thread = StreamThread(f"http://{server_ip}:{video_port}")
        self.stream_thread.frame_received.connect(self.update_video_frame)
        self.stream_thread.start()

    def initUI(self):
        # 视频显示区域
        self.video_view = QLabel("正在连接视频流...")
        self.video_view.setMinimumSize(640, 480)  # 设置最小尺寸
        self.video_view.setAlignment(Qt.AlignCenter)

        # 控制按钮区域
        self.init_control_buttons()

        # 主布局：左侧视频、右侧按钮
        main_layout = QHBoxLayout()
        main_layout.addWidget(self.video_view, stretch=2)  # 视频区域伸展占比2
        main_layout.addLayout(self.control_layout, stretch=1)  # 按钮区域占比1

        self.setLayout(main_layout)
        self.setWindowTitle("机器人控制与视频显示")
        self.resize(1000, 600)

    def init_control_buttons(self):
        """初始化机器人控制按钮"""
        self.control_layout = QVBoxLayout()

        # 连接/断开按钮
        self.connect_button = QPushButton("连接服务器")
        self.disconnect_button = QPushButton("断开连接")
        self.connect_button.clicked.connect(self.connect_to_server)
        self.disconnect_button.clicked.connect(self.disconnect_from_server)

        # 动作按钮
        self.stand_up_button = QPushButton("站立")
        self.sit_down_button = QPushButton("坐下")
        self.damp_button = QPushButton("■")
        self.damp_button.setStyleSheet("QPushButton { background-color: red; color: white; font-weight: bold; }")
        self.damp_button.setFixedSize(50, 50)
        
        # 单次命令按钮事件
        self.stand_up_button.clicked.connect(lambda: self.send_command("stand_up"))
        self.sit_down_button.clicked.connect(lambda: self.send_command("sit_down"))
        self.damp_button.clicked.connect(lambda: self.send_command("stop"))

        # 方向按钮布局
        direction_layout = QGridLayout()
        self.forward_button = QPushButton("▲")
        self.backward_button = QPushButton("▼")
        self.left_button = QPushButton("◀")
        self.right_button = QPushButton("▶")
        self.turn_left_button = QPushButton("↺")
        self.turn_right_button = QPushButton("↻")

        # 设置持续命令按钮事件
        self.setup_button_events(self.forward_button, "forward")
        self.setup_button_events(self.backward_button, "backward")
        self.setup_button_events(self.left_button, "left")
        self.setup_button_events(self.right_button, "right")
        self.setup_button_events(self.turn_left_button, "turn_left")
        self.setup_button_events(self.turn_right_button, "turn_right")

        # 布局位置设置
        direction_layout.addWidget(self.turn_left_button, 0, 0)
        direction_layout.addWidget(self.turn_right_button, 0, 2)
        direction_layout.addWidget(self.forward_button, 1, 1)
        direction_layout.addWidget(self.left_button, 2, 0)
        direction_layout.addWidget(self.right_button, 2, 2)
        direction_layout.addWidget(self.backward_button, 3, 1)

        # 将按钮布局添加到控制区域
        self.control_layout.addWidget(self.connect_button)
        self.control_layout.addWidget(self.disconnect_button)
        self.control_layout.addWidget(self.stand_up_button)
        self.control_layout.addWidget(self.sit_down_button)
        self.control_layout.addWidget(self.damp_button)
        self.control_layout.addLayout(direction_layout)
        self.control_layout.addStretch()  # 添加拉伸，保证按钮区域居中显示

    def setup_button_events(self, button, command):
        """设置按钮的按下和释放事件"""
        button.pressed.connect(lambda: self.start_continuous_command(command))
        button.released.connect(self.stop_continuous_command)

    def start_continuous_command(self, command):
        """开始持续发送命令"""
        self.current_command = command
        self.send_command(command)
        self.command_timer.start(100)  # 每100ms发送一次命令

    def stop_continuous_command(self):
        """停止持续发送命令"""
        self.command_timer.stop()
        self.current_command = None
        self.send_command("stop")

    def send_current_command(self):
        """发送当前命令（定时器触发）"""
        if self.current_command:
            self.send_command(self.current_command)

    def connect_to_server(self):
        """连接到服务器"""
        if self.socket.state() == QTcpSocket.UnconnectedState:
            self.socket.connectToHost(self.server_ip, self.server_port)
        else:
            print("已经连接或正在连接中...")

    def disconnect_from_server(self):
        """断开服务器连接"""
        if self.socket.state() == QTcpSocket.ConnectedState:
            self.socket.disconnectFromHost()
        else:
            print("未连接到服务器")

    def on_connected(self):
        """连接成功回调"""
        print(f"已连接到机器人服务器 {self.server_ip}:{self.server_port}")

    def on_disconnected(self):
        """断开连接回调"""
        print("已断开服务器连接")

    def on_error(self, socket_error):
        """Socket错误回调"""
        print("Socket错误:", self.socket.errorString())

    def send_command(self, cmd):
        """发送命令到服务器"""
        if self.socket.state() == QTcpSocket.ConnectedState:
            message = cmd + "\n"
            self.socket.write(message.encode('utf-8'))
            self.socket.flush()
        else:
            print(f"未连接到服务器，无法发送命令: {cmd}")

    def update_video_frame(self, frame):
        """更新视频流图像"""
        image = QImage(frame.data, frame.shape[1], frame.shape[0], QImage.Format_RGB888).rgbSwapped()
        pixmap = QPixmap.fromImage(image)
        self.video_view.setPixmap(pixmap.scaled(self.video_view.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def closeEvent(self, event):
        """窗口关闭时停止视频流线程"""
        self.stream_thread.stop()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # 服务器配置：替换为实际IP和端口
    SERVER_IP = "192.168.2.34"  # 服务器IP地址
    SERVER_PORT = 8082          # 机器人控制端口
    VIDEO_PORT = 8080           # 视频流端口

    # 启动应用
    window = RobotControlUI(SERVER_IP, SERVER_PORT, VIDEO_PORT)
    window.show()

    sys.exit(app.exec_())