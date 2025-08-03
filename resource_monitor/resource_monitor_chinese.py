import sys
import psutil
import GPUtil
import time
import json
import os
import datetime
import queue
import win32gui
import win32process
import win32con
import win32ui
import csv
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QLabel, QLineEdit, QPushButton, QListWidget, QTabWidget, 
                            QSplitter, QMessageBox, QFileDialog, QGroupBox, QFormLayout, 
                            QSpinBox, QDoubleSpinBox, QComboBox, QStatusBar, QDialog, 
                            QTreeWidget, QTreeWidgetItem, QHeaderView, QProgressBar, 
                            QToolBar, QAction, QMenu, QCheckBox, QTreeWidgetItemIterator,
                            QListWidgetItem, QFrame, QGridLayout, QSizePolicy)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QDateTime, QTimer, QSortFilterProxyModel, QSize
from PyQt5.QtGui import QFont, QIcon, QColor, QStandardItemModel, QStandardItem, QPixmap, QImage
import matplotlib
matplotlib.use('Qt5Agg')
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt

# 设置matplotlib支持中文显示
plt.rcParams["font.family"] = ["SimHei"]
plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题

class MonitorThread(QThread):
    """监控资源的后台线程"""
    update_signal = pyqtSignal(dict)
    
    def __init__(self, software_list, update_interval=1, monitor_system=False):
        super().__init__()
        self.software_list = software_list
        self.update_interval = update_interval
        self.running = True
        self.process_network_counters = {}  # 存储各进程的网络计数器
        self.system_network_counters = psutil.net_io_counters(pernic=True)
        self.monitor_system = monitor_system
    
    def run(self):
        while self.running:
            try:
                data = self.get_resource_data()
                self.update_signal.emit(data)
                time.sleep(self.update_interval)
            except Exception as e:
                print(f"监控线程错误: {e}")
                self.running = False
    
    def stop(self):
        self.running = False
    
    def get_resource_data(self):
        """获取指定软件的资源使用情况"""
        data = {}
        
        # 监控整机资源
        if self.monitor_system:
            # CPU使用率
            cpu_percent = psutil.cpu_percent(interval=0.1)
            
            # 内存使用率 (MB)
            memory = psutil.virtual_memory()
            memory_mb = memory.used / (1024 ** 2)
            memory_percent = memory.percent
            
            # 网络使用率
            current_network_counters = psutil.net_io_counters(pernic=True)
            if self.system_network_counters:
                network_usage = 0
                for nic, counters in current_network_counters.items():
                    if nic in self.system_network_counters:
                        # 计算接收和发送的字节数差
                        bytes_sent = counters.bytes_sent - self.system_network_counters[nic].bytes_sent
                        bytes_recv = counters.bytes_recv - self.system_network_counters[nic].bytes_recv
                        # 转换为Mbps
                        network_usage += (bytes_sent + bytes_recv) * 8 / (1024 ** 2) / self.update_interval
            else:
                network_usage = 0
            
            # 更新上次网络I/O计数器
            self.system_network_counters = current_network_counters
            
            # 硬盘使用率
            disk_counters = psutil.disk_io_counters()
            disk_usage = (disk_counters.read_bytes + disk_counters.write_bytes) / (1024 ** 2) / self.update_interval
            
            # GPU使用率
            try:
                gpus = GPUtil.getGPUs()
                if gpus:
                    gpu_usage = gpus[0].load * 100  # 转换为百分比
                else:
                    gpu_usage = 0
            except:
                gpu_usage = 0
            
            # 存储整机数据
            data["系统"] = {
                'cpu': cpu_percent,
                'memory': memory_mb,
                'memory_percent': memory_percent,
                'network': network_usage,
                'disk': disk_usage,
                'gpu': gpu_usage,
                'pid': None,
                'username': os.getlogin()
            }
        
        # 获取所有进程信息
        current_process_network = {}  # 存储当前进程的网络连接数
        
        for proc in psutil.process_iter(['name', 'cpu_percent', 'memory_info', 'pid', 'username']):
            try:
                process_name = proc.info['name'].lower()
                
                # 检查进程名是否在监控列表中
                for software in self.software_list:
                    if software.lower() in process_name:
                        # CPU使用率
                        cpu_percent = proc.info['cpu_percent']
                        
                        # 内存使用率 (MB)
                        memory_mb = proc.info['memory_info'].rss / (1024 ** 2)
                        
                        # 网络使用率
                        try:
                            # 获取进程的网络连接
                            connections = proc.connections(kind='inet')
                            current_process_network[proc.info['pid']] = len(connections)
                            
                            # 基于连接数估算网络使用
                            if proc.info['pid'] in self.process_network_counters:
                                last_connections = self.process_network_counters[proc.info['pid']]
                                network_usage = len(connections) - last_connections
                                # 如果连接数减少，说明有数据传输
                                if network_usage < 0:
                                    network_usage = abs(network_usage) * 0.1  # 估算值
                                else:
                                    network_usage = 0
                            else:
                                network_usage = 0
                            
                            # 限制最大值
                            if network_usage > 100:
                                network_usage = 100
                            
                        except (psutil.AccessDenied, psutil.NoSuchProcess):
                            network_usage = 0
                        
                        # 硬盘使用率
                        try:
                            # 获取进程的I/O计数器
                            io_counters = proc.io_counters()
                            if io_counters:
                                # 转换为MB/s
                                disk_usage = (io_counters.read_bytes + io_counters.write_bytes) / (1024 ** 2) / self.update_interval
                            else:
                                disk_usage = 0
                        except (psutil.AccessDenied, psutil.NoSuchProcess):
                            disk_usage = 0
                        
                        # GPU使用率
                        try:
                            gpu_usage = 0
                            # 尝试通过进程ID获取GPU使用情况
                            # 注意：这需要NVIDIA的pynvml库支持
                            # 这里简化处理，实际应用中可能需要更复杂的实现
                            gpus = GPUtil.getGPUs()
                            if gpus:
                                # 无法直接获取进程的GPU使用，这里仅作示例
                                pass
                        except:
                            gpu_usage = 0
                        
                        # 存储数据
                        data[software] = {
                            'cpu': cpu_percent,
                            'memory': memory_mb,
                            'network': network_usage,
                            'disk': disk_usage,
                            'gpu': gpu_usage,
                            'pid': proc.info['pid'],
                            'username': proc.info['username'] if 'username' in proc.info else "未知"
                        }
                        
                        # 跳出内层循环，避免重复添加同一进程
                        break
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
        
        # 更新进程网络计数器
        self.process_network_counters = current_process_network
        
        # 为未找到的软件设置默认值
        for software in self.software_list:
            if software not in data:
                data[software] = {
                    'cpu': 0,
                    'memory': 0,
                    'network': 0,
                    'disk': 0,
                    'gpu': 0,
                    'pid': None,
                    'username': "未知"
                }
        
        return data

class ProcessSelector(QDialog):
    """进程选择对话框"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择进程")
        self.setMinimumSize(900, 600)  # 增大窗口尺寸
        
        # 创建布局
        layout = QVBoxLayout(self)
        
        # 筛选区域
        filter_layout = QHBoxLayout()
        
        # 进程类型筛选
        self.process_type_combo = QComboBox()
        self.process_type_combo.addItems(["所有进程", "应用程序", "系统进程", "用户进程"])
        self.process_type_combo.currentIndexChanged.connect(self.filter_processes)
        
        # 搜索框
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索进程...")
        self.search_edit.textChanged.connect(self.filter_processes)
        
        # 刷新按钮
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.clicked.connect(self.refresh_processes)
        
        # 显示图标复选框
        self.show_icon_checkbox = QCheckBox("显示图标")
        self.show_icon_checkbox.setChecked(True)
        self.show_icon_checkbox.stateChanged.connect(self.refresh_processes)
        
        filter_layout.addWidget(QLabel("筛选类型:"))
        filter_layout.addWidget(self.process_type_combo)
        filter_layout.addWidget(QLabel("搜索:"))
        filter_layout.addWidget(self.search_edit)
        filter_layout.addWidget(self.refresh_button)
        filter_layout.addWidget(self.show_icon_checkbox)
        
        layout.addLayout(filter_layout)
        
        # 创建进程树
        self.process_tree = QTreeWidget()
        self.process_tree.setColumnCount(5)
        self.process_tree.setHeaderLabels(["进程名称", "PID", "用户名", "CPU (%)", "内存 (MB)"])
        
        # 设置列宽策略
        self.process_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)  # 进程名称列自动拉伸
        self.process_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.process_tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.process_tree.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.process_tree.header().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        
        # 设置字体，使其更易读
        font = QFont()
        font.setPointSize(10)
        self.process_tree.setFont(font)
        
        # 设置样式，使进程名称可以显示完整
        self.process_tree.setStyleSheet("""
            QTreeWidget {
                show-decoration-selected: 1;
                alternate-background-color: #f2f2f2;
            }
            QTreeWidget::item {
                height: 30px;
                border-bottom: 1px solid #e0e0e0;
            }
            QTreeWidget::item:selected {
                background-color: #bde0fe;
                color: black;
            }
        """)
        
        self.process_tree.setSortingEnabled(True)
        self.process_tree.sortByColumn(0, Qt.AscendingOrder)
        
        # 添加到布局
        layout.addWidget(self.process_tree)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        
        self.select_button = QPushButton("选择")
        self.select_button.clicked.connect(self.select_process)
        
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.reject)
        
        button_layout.addStretch(1)
        button_layout.addWidget(self.select_button)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
        
        # 初始化进程列表
        self.refresh_processes()
        
        # 连接双击事件
        self.process_tree.itemDoubleClicked.connect(self.item_double_clicked)
        
        # 存储原始进程数据
        self.all_processes = []
    
    def refresh_processes(self):
        """刷新进程列表"""
        self.process_tree.clear()
        self.all_processes = []
        
        # 获取当前用户
        current_user = os.getlogin()
        
        # 创建分类根节点
        self.all_root = QTreeWidgetItem(self.process_tree)
        self.all_root.setText(0, "所有进程")
        self.all_root.setExpanded(True)
        
        self.apps_root = QTreeWidgetItem(self.process_tree)
        self.apps_root.setText(0, "应用程序")
        self.apps_root.setExpanded(True)
        
        self.system_root = QTreeWidgetItem(self.process_tree)
        self.system_root.setText(0, "系统进程")
        self.system_root.setExpanded(True)
        
        self.user_root = QTreeWidgetItem(self.process_tree)
        self.user_root.setText(0, "用户进程")
        self.user_root.setExpanded(True)
        
        # 获取所有进程
        for proc in psutil.process_iter(['name', 'cpu_percent', 'memory_info', 'username', 'pid']):
            try:
                process_name = proc.info['name']
                pid = proc.info['pid']
                cpu_percent = proc.info['cpu_percent']
                memory_mb = proc.info['memory_info'].rss / (1024 ** 2)
                username = proc.info['username'] if 'username' in proc.info else "未知"
                
                # 存储原始进程数据
                process_data = {
                    'name': process_name,
                    'pid': pid,
                    'username': username,
                    'cpu_percent': cpu_percent,
                    'memory_mb': memory_mb
                }
                self.all_processes.append(process_data)
                
                # 创建进程项
                process_item = QTreeWidgetItem()
                
                # 设置进程名称，使用省略号处理过长的名称
                process_item.setText(0, process_name)
                process_item.setToolTip(0, process_name)  # 设置完整名称为tooltip
                
                process_item.setText(1, str(pid))
                process_item.setText(2, username)
                process_item.setText(3, f"{cpu_percent:.1f}")
                process_item.setText(4, f"{memory_mb:.1f}")
                
                # 设置背景色，CPU使用率高的进程显示为红色
                if cpu_percent > 50:
                    for i in range(5):
                        process_item.setBackground(i, QColor(255, 200, 200))
                        
                # 根据用户分类
                self.all_root.addChild(process_item.clone())
                
                # 判断是否为应用程序
                is_application = self.is_application(process_name)
                if is_application:
                    self.apps_root.addChild(process_item.clone())
                
                # 根据用户分类
                if username == current_user:
                    self.user_root.addChild(process_item.clone())
                else:
                    self.system_root.addChild(process_item.clone())
                    
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
        
        # 应用筛选
        self.filter_processes()
    
    def is_application(self, process_name):
        """判断是否为应用程序"""
        # 常见的应用程序扩展名
        app_extensions = ['.exe', '.app', '.jar', '.pyw']
        
        # 常见的应用程序名称
        app_names = ['chrome', 'firefox', 'explorer', 'word', 'excel', 'powerpoint', 
                    'notepad', 'photoshop', 'premiere', 'aftereffects', 'vscode', 'sublime']
        
        process_name_lower = process_name.lower()
        
        # 检查扩展名
        for ext in app_extensions:
            if process_name_lower.endswith(ext):
                return True
        
        # 检查名称
        for name in app_names:
            if name in process_name_lower:
                return True
        
        return False
    
    def filter_processes(self):
        """根据筛选条件过滤进程"""
        filter_type = self.process_type_combo.currentText()
        search_text = self.search_edit.text().lower()
        
        # 隐藏所有根节点
        self.all_root.setHidden(True)
        self.apps_root.setHidden(True)
        self.system_root.setHidden(True)
        self.user_root.setHidden(True)
        
        # 根据筛选类型显示相应的根节点
        if filter_type == "所有进程":
            self.all_root.setHidden(False)
        elif filter_type == "应用程序":
            self.apps_root.setHidden(False)
        elif filter_type == "系统进程":
            self.system_root.setHidden(False)
        elif filter_type == "用户进程":
            self.user_root.setHidden(False)
        
        # 获取当前根节点
        if filter_type == "所有进程":
            current_root = self.all_root
        elif filter_type == "应用程序":
            current_root = self.apps_root
        elif filter_type == "系统进程":
            current_root = self.system_root
        elif filter_type == "用户进程":
            current_root = self.user_root
        else:
            current_root = self.all_root
        
        # 遍历所有子项
        for i in range(current_root.childCount()):
            child = current_root.child(i)
            
            # 如果有搜索文本，检查是否匹配
            if search_text and not (search_text in child.text(0).lower() or 
                                  search_text in child.text(1).lower() or 
                                  search_text in child.text(2).lower()):
                child.setHidden(True)
            else:
                child.setHidden(False)
    
    def item_double_clicked(self, item, column):
        """双击项目时选择进程"""
        # 确保不是顶级项目
        if item.parent() is not None:
            self.select_process()
    
    def select_process(self):
        """选择进程并返回"""
        selected_items = self.process_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "警告", "请先选择一个进程!")
            return
            
        # 获取第一个选中的项目
        item = selected_items[0]
        
        # 确保不是顶级项目
        if item.parent() is not None:
            process_name = item.text(0)
            self.selected_process = process_name
            self.accept()

class MplCanvas(FigureCanvas):
    """Matplotlib画布，用于显示图表"""
    def __init__(self, parent=None, width=5, height=4, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.axes = self.fig.add_subplot(111)
        super(MplCanvas, self).__init__(self.fig)
        self.fig.tight_layout()
    
    def __del__(self):
        """清理资源"""
        self.axes.clear()
        self.fig.clear()

class ResourceMonitor(QMainWindow):
    """主窗口类"""
    def __init__(self):
        super().__init__()
        
        # 设置中文字体
        font = QFont()
        font.setFamily("SimHei")
        font.setPointSize(10)
        QApplication.setFont(font)
        
        # 存储监控数据
        self.software_list = []
        self.monitor_thread = None
        self.time_data = []
        self.cpu_data = {}
        self.memory_data = {}
        self.network_data = {}
        self.disk_data = {}
        self.gpu_data = {}
        self.pid_data = {}
        self.username_data = {}
        
        # 最大历史记录点
        self.max_history_points = 60
        
        # 整机监控选项
        self.monitor_system = False
        
        # 创建UI
        self.init_ui()
        
        # 获取系统信息
        self.update_system_info()
    
    def init_ui(self):
        """初始化用户界面"""
        # 设置窗口标题和大小
        self.setWindowTitle("软件资源监控系统")
        self.setGeometry(100, 100, 1200, 800)
        
        # 创建主布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # 系统信息栏
        self.system_info_label = QLabel("系统信息将在这里显示...")
        main_layout.addWidget(self.system_info_label)
        
        # 分割器，分为上下两部分
        splitter = QSplitter(Qt.Vertical)
        
        # 控制面板
        control_widget = QWidget()
        control_layout = QVBoxLayout(control_widget)
        
        # 软件监控组
        software_group = QGroupBox("监控软件")
        software_layout = QHBoxLayout()
        
        software_label = QLabel("软件名称:")
        self.software_entry = QLineEdit()
        self.software_entry.setPlaceholderText("输入软件名称或从进程列表选择")
        
        self.select_process_button = QPushButton("从进程选择")
        self.select_process_button.clicked.connect(self.select_process)
        
        add_button = QPushButton("添加")
        add_button.clicked.connect(self.add_software)
        
        remove_button = QPushButton("移除")
        remove_button.clicked.connect(self.remove_software)
        
        # 整机监控复选框
        self.system_monitor_checkbox = QCheckBox("监控整机资源")
        self.system_monitor_checkbox.stateChanged.connect(self.toggle_system_monitoring)
        
        self.software_listbox = QListWidget()
        
        software_layout.addWidget(software_label)
        software_layout.addWidget(self.software_entry)
        software_layout.addWidget(self.select_process_button)
        software_layout.addWidget(add_button)
        software_layout.addWidget(remove_button)
        software_layout.addWidget(self.system_monitor_checkbox)
        software_layout.addWidget(self.software_listbox)
        
        software_group.setLayout(software_layout)
        control_layout.addWidget(software_group)
        
        # 设置组
        settings_group = QGroupBox("监控设置")
        settings_layout = QFormLayout()
        
        self.update_interval_spinbox = QDoubleSpinBox()
        self.update_interval_spinbox.setRange(0.1, 10.0)
        self.update_interval_spinbox.setValue(1.0)
        self.update_interval_spinbox.setSingleStep(0.1)
        self.update_interval_spinbox.setSuffix(" 秒")
        
        self.history_points_spinbox = QSpinBox()
        self.history_points_spinbox.setRange(10, 1000)
        self.history_points_spinbox.setValue(60)
        self.history_points_spinbox.setSuffix(" 个点")
        
        self.start_button = QPushButton("开始监控")
        self.start_button.setCheckable(True)
        self.start_button.toggled.connect(self.toggle_monitoring)
        
        settings_layout.addRow("更新间隔:", self.update_interval_spinbox)
        settings_layout.addRow("历史记录点:", self.history_points_spinbox)
        settings_layout.addRow(self.start_button)
        
        settings_group.setLayout(settings_layout)
        control_layout.addWidget(settings_group)
        
        # 导出按钮
        export_layout = QHBoxLayout()
        self.export_json_button = QPushButton("导出JSON")
        self.export_json_button.clicked.connect(lambda: self.export_data("json"))
        
        self.export_csv_button = QPushButton("导出CSV")
        self.export_csv_button.clicked.connect(lambda: self.export_data("csv"))
        
        export_layout.addStretch(1)
        export_layout.addWidget(self.export_json_button)
        export_layout.addWidget(self.export_csv_button)
        
        control_layout.addLayout(export_layout)
        
        # 添加控制区域到分割器
        splitter.addWidget(control_widget)
        
        # 图表区域 - 使用选项卡布局
        self.chart_tabs = QTabWidget()
        
        # CPU图表
        self.cpu_canvas = MplCanvas(self, width=5, height=4, dpi=100)
        self.chart_tabs.addTab(self.cpu_canvas, "CPU使用率 (%)")
        
        # 内存图表
        self.memory_canvas = MplCanvas(self, width=5, height=4, dpi=100)
        self.chart_tabs.addTab(self.memory_canvas, "内存使用 (MB)")
        
        # 网络图表
        self.network_canvas = MplCanvas(self, width=5, height=4, dpi=100)
        self.chart_tabs.addTab(self.network_canvas, "网络使用 (Mbps)")
        
        # 硬盘图表
        self.disk_canvas = MplCanvas(self, width=5, height=4, dpi=100)
        self.chart_tabs.addTab(self.disk_canvas, "硬盘使用 (MB/s)")
        
        # GPU图表
        self.gpu_canvas = MplCanvas(self, width=5, height=4, dpi=100)
        self.chart_tabs.addTab(self.gpu_canvas, "GPU使用率 (%)")
        
        # 添加图表区域到分割器
        splitter.addWidget(self.chart_tabs)
        
        # 设置分割器比例
        splitter.setSizes([200, 600])
        
        # 添加分割器到主布局
        main_layout.addWidget(splitter)
        
        # 添加状态栏
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("就绪")
    
    def update_system_info(self):
        """更新系统信息"""
        try:
            # CPU信息
            cpu_count = psutil.cpu_count(logical=False)
            cpu_freq = psutil.cpu_freq().current / 1000  # GHz
            
            # 内存信息
            memory = psutil.virtual_memory()
            total_memory = round(memory.total / (1024**3), 2)  # GB
            
            # 操作系统信息
            import platform
            os_info = platform.platform()
            
            # GPU信息
            try:
                gpus = GPUtil.getGPUs()
                if gpus:
                    gpu_info = gpus[0].name
                else:
                    gpu_info = "未检测到GPU"
            except:
                gpu_info = "无法获取GPU信息"
            
            # 更新信息标签
            info_text = f"操作系统: {os_info} | CPU: {cpu_count}核 @ {cpu_freq:.2f}GHz | 内存: {total_memory}GB | GPU: {gpu_info}"
            self.system_info_label.setText(info_text)
            
        except Exception as e:
            self.system_info_label.setText(f"获取系统信息失败: {e}")
    
    def select_process(self):
        """打开进程选择对话框"""
        dialog = ProcessSelector(self)
        if dialog.exec_():
            # 获取选择的进程
            process_name = dialog.selected_process
            self.software_entry.setText(process_name)
    
    def toggle_system_monitoring(self, state):
        """切换整机监控选项"""
        self.monitor_system = state == Qt.Checked
        
        # 如果正在监控，重启监控线程
        if self.monitor_thread and self.monitor_thread.isRunning():
            self.toggle_monitoring(False)
            self.toggle_monitoring(True)
    
    def add_software(self):
        """添加软件到监控列表"""
        software_name = self.software_entry.text().strip()
        if software_name and software_name not in self.software_list:
            self.software_list.append(software_name)
            self.software_listbox.addItem(software_name)
            self.software_entry.clear()
            
            # 初始化图表数据
            self.cpu_data[software_name] = []
            self.memory_data[software_name] = []
            self.network_data[software_name] = []
            self.disk_data[software_name] = []
            self.gpu_data[software_name] = []
            self.pid_data[software_name] = []
            self.username_data[software_name] = []
    
    def remove_software(self):
        """从监控列表中移除软件"""
        selected_items = self.software_listbox.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "警告", "请先选择要移除的软件!")
            return
            
        for item in selected_items:
            software_name = item.text()
            self.software_list.remove(software_name)
            self.software_listbox.takeItem(self.software_listbox.row(item))
            
            # 移除图表数据
            if software_name in self.cpu_data:
                del self.cpu_data[software_name]
            if software_name in self.memory_data:
                del self.memory_data[software_name]
            if software_name in self.network_data:
                del self.network_data[software_name]
            if software_name in self.disk_data:
                del self.disk_data[software_name]
            if software_name in self.gpu_data:
                del self.gpu_data[software_name]
            if software_name in self.pid_data:
                del self.pid_data[software_name]
            if software_name in self.username_data:
                del self.username_data[software_name]
    
    def toggle_monitoring(self, checked):
        """开始或停止监控"""
        if checked:
            if not self.software_list and not self.monitor_system:
                QMessageBox.warning(self, "警告", "请先添加要监控的软件或选择监控整机资源!")
                self.start_button.setChecked(False)
                return
                
            # 重置数据
            self.time_data = []
            for software in self.software_list:
                self.cpu_data[software] = []
                self.memory_data[software] = []
                self.network_data[software] = []
                self.disk_data[software] = []
                self.gpu_data[software] = []
                self.pid_data[software] = []
                self.username_data[software] = []
            
            # 如果监控整机，初始化系统数据
            if self.monitor_system:
                self.cpu_data["系统"] = []
                self.memory_data["系统"] = []
                self.network_data["系统"] = []
                self.disk_data["系统"] = []
                self.gpu_data["系统"] = []
                self.pid_data["系统"] = []
                self.username_data["系统"] = []
            
            # 更新最大历史记录点
            self.max_history_points = self.history_points_spinbox.value()
            
            # 启动监控线程
            self.monitor_thread = MonitorThread(
                self.software_list, 
                self.update_interval_spinbox.value(),
                self.monitor_system
            )
            self.monitor_thread.update_signal.connect(self.update_charts)
            self.monitor_thread.finished.connect(self.monitoring_finished)
            self.monitor_thread.start()
            
            # 更新UI状态
            self.start_button.setText("停止监控")
            self.software_entry.setEnabled(False)
            self.select_process_button.setEnabled(False)
            self.system_monitor_checkbox.setEnabled(False)
            self.export_json_button.setEnabled(False)
            self.export_csv_button.setEnabled(False)
            self.update_interval_spinbox.setEnabled(False)
            self.history_points_spinbox.setEnabled(False)
            
            self.statusBar.showMessage("正在监控...")
        else:
            # 停止监控线程
            if self.monitor_thread and self.monitor_thread.isRunning():
                self.monitor_thread.stop()
                self.monitor_thread.wait()
                self.monitor_thread = None
    
    def monitoring_finished(self):
        """监控结束处理"""
        # 更新UI状态
        self.start_button.setText("开始监控")
        self.software_entry.setEnabled(True)
        self.select_process_button.setEnabled(True)
        self.system_monitor_checkbox.setEnabled(True)
        self.export_json_button.setEnabled(True)
        self.export_csv_button.setEnabled(True)
        self.update_interval_spinbox.setEnabled(True)
        self.history_points_spinbox.setEnabled(True)
        
        self.statusBar.showMessage("监控已停止")
    
    def update_charts(self, data):
        """更新图表显示"""
        # 获取当前时间
        current_time = QDateTime.currentDateTime().toString("HH:mm:ss")
        self.time_data.append(current_time)
        
        # 限制数据点数量
        if len(self.time_data) > self.max_history_points:
            self.time_data.pop(0)
        
        # 处理每个软件的数据
        for software, metrics in data.items():
            # 添加数据到相应的列表
            self.cpu_data[software].append(metrics['cpu'])
            self.memory_data[software].append(metrics['memory'])
            self.network_data[software].append(metrics['network'])
            self.disk_data[software].append(metrics['disk'])
            self.gpu_data[software].append(metrics['gpu'])
            self.pid_data[software].append(metrics['pid'])
            self.username_data[software].append(metrics['username'])
            
            # 限制数据点数量
            if len(self.cpu_data[software]) > self.max_history_points:
                self.cpu_data[software].pop(0)
                self.memory_data[software].pop(0)
                self.network_data[software].pop(0)
                self.disk_data[software].pop(0)
                self.gpu_data[software].pop(0)
                self.pid_data[software].pop(0)
                self.username_data[software].pop(0)
        
        # 更新图表
        self._update_canvas(self.cpu_canvas, self.cpu_data, "CPU使用率 (%)")
        self._update_canvas(self.memory_canvas, self.memory_data, "内存使用 (MB)")
        self._update_canvas(self.network_canvas, self.network_data, "网络使用 (Mbps)")
        self._update_canvas(self.disk_canvas, self.disk_data, "硬盘使用 (MB/s)")
        self._update_canvas(self.gpu_canvas, self.gpu_data, "GPU使用率 (%)")
    
    def _update_canvas(self, canvas, data, title):
        """更新单个画布"""
        canvas.axes.clear()
        canvas.axes.set_title(title)
        canvas.axes.set_xlabel("时间")
        canvas.axes.grid(True)
        
        # 为每种软件绘制线条
        colors = ['b', 'g', 'r', 'c', 'm', 'y', 'k', 'tab:orange', 'tab:purple', 'tab:brown']
        
        if self.time_data:
            for i, software in enumerate(data.keys()):
                color = colors[i % len(colors)]
                
                # 获取最新的PID和用户名
                latest_pid = self.pid_data[software][-1] if self.pid_data[software] else None
                latest_username = self.username_data[software][-1] if self.username_data[software] else "未知"
                
                label = f"{software}"
                if latest_pid is not None:
                    label += f" (PID: {latest_pid}, 用户: {latest_username})"
                
                # 绘制系统资源时使用特殊样式
                if software == "系统":
                    canvas.axes.plot(self.time_data, data[software], label=label, color=color, linewidth=2, linestyle='--')
                else:
                    canvas.axes.plot(self.time_data, data[software], label=label, color=color)
            
            # 添加图例和旋转x轴标签
            canvas.axes.legend(loc='upper left')
            canvas.axes.tick_params(axis='x', rotation=45)
            
            # 调整布局
            canvas.fig.tight_layout()
            canvas.draw()
    
    def export_data(self, file_type):
        """导出数据到文件"""
        if not self.time_data or not self.cpu_data:
            QMessageBox.warning(self, "警告", "没有数据可导出!")
            return
            
        try:
            # 获取保存文件路径
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            default_filename = f"resource_monitor_{timestamp}.{file_type}"
            
            if file_type == "json":
                file_path, _ = QFileDialog.getSaveFileName(
                    self, "保存JSON文件", default_filename, "JSON文件 (*.json)"
                )
                
                if not file_path:
                    return
                    
                # 导出为JSON文件
                export_data = []
                
                # 获取所有时间点的时间戳
                timestamps = [datetime.datetime.strptime(t, "%H:%M:%S").timestamp() for t in self.time_data]
                
                for i, time_str in enumerate(self.time_data):
                    entry = {
                        '时间': time_str,
                        '时间戳': timestamps[i],
                        '软件资源': {}
                    }
                    
                    for software in self.cpu_data.keys():
                        entry['软件资源'][software] = {
                            'CPU(%)': self.cpu_data[software][i] if i < len(self.cpu_data[software]) else None,
                            '内存(MB)': self.memory_data[software][i] if i < len(self.memory_data[software]) else None,
                            '网络(Mbps)': self.network_data[software][i] if i < len(self.network_data[software]) else None,
                            '硬盘(MB/s)': self.disk_data[software][i] if i < len(self.disk_data[software]) else None,
                            'GPU(%)': self.gpu_data[software][i] if i < len(self.gpu_data[software]) else None,
                            'PID': self.pid_data[software][i] if i < len(self.pid_data[software]) else None,
                            '用户名': self.username_data[software][i] if i < len(self.username_data[software]) else None
                        }
                    
                    export_data.append(entry)
                
                with open(file_path, 'w', encoding='utf-8') as jsonfile:
                    json.dump(export_data, jsonfile, ensure_ascii=False, indent=4)
            
            elif file_type == "csv":
                file_path, _ = QFileDialog.getSaveFileName(
                    self, "保存CSV文件", default_filename, "CSV文件 (*.csv)"
                )
                
                if not file_path:
                    return
                    
                # 导出为CSV文件
                with open(file_path, 'w', newline='', encoding='utf-8-sig') as csvfile:
                    writer = csv.writer(csvfile)
                    
                    # 创建表头
                    headers = ['时间']
                    for software in self.cpu_data.keys():
                        headers.extend([
                            f'{software}_CPU(%)', 
                            f'{software}_内存(MB)', 
                            f'{software}_网络(Mbps)', 
                            f'{software}_硬盘(MB/s)', 
                            f'{software}_GPU(%)',
                            f'{software}_PID',
                            f'{software}_用户名'
                        ])
                    
                    writer.writerow(headers)
                    
                    # 写入数据
                    for i, time_str in enumerate(self.time_data):
                        row = [time_str]
                        for software in self.cpu_data.keys():
                            # 获取该时间点的数据
                            cpu = self.cpu_data[software][i] if i < len(self.cpu_data[software]) else None
                            memory = self.memory_data[software][i] if i < len(self.memory_data[software]) else None
                            network = self.network_data[software][i] if i < len(self.network_data[software]) else None
                            disk = self.disk_data[software][i] if i < len(self.disk_data[software]) else None
                            gpu = self.gpu_data[software][i] if i < len(self.gpu_data[software]) else None
                            pid = self.pid_data[software][i] if i < len(self.pid_data[software]) else None
                            username = self.username_data[software][i] if i < len(self.username_data[software]) else None
                            
                            # 添加到行数据
                            row.extend([cpu, memory, network, disk, gpu, pid, username])
                        
                        writer.writerow(row)
            
            self.statusBar.showMessage(f"数据已成功导出到 {file_path}")
            
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"导出数据时出错: {str(e)}")
            self.statusBar.showMessage("导出数据失败")
    
    def closeEvent(self, event):
        """关闭窗口时的处理"""
        # 停止监控线程
        if self.monitor_thread and self.monitor_thread.isRunning():
            self.monitor_thread.stop()
            self.monitor_thread.wait()
        
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ResourceMonitor()
    window.show()
    sys.exit(app.exec_())