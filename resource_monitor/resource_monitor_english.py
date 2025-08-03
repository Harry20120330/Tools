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

# Configure matplotlib to support Chinese display
plt.rcParams["font.family"] = ["SimHei"]
plt.rcParams['axes.unicode_minus'] = False  # Fix negative sign display issue

class MonitorThread(QThread):
    """Background thread for monitoring resources"""
    update_signal = pyqtSignal(dict)
    
    def __init__(self, software_list, update_interval=1, monitor_system=False):
        super().__init__()
        self.software_list = software_list
        self.update_interval = update_interval
        self.running = True
        self.process_network_counters = {}  # Store network counters for each process
        self.system_network_counters = psutil.net_io_counters(pernic=True)
        self.monitor_system = monitor_system
    
    def run(self):
        while self.running:
            try:
                data = self.get_resource_data()
                self.update_signal.emit(data)
                time.sleep(self.update_interval)
            except Exception as e:
                print(f"Monitoring thread error: {e}")
                self.running = False
    
    def stop(self):
        self.running = False
    
    def get_resource_data(self):
        """Get resource usage of specified software"""
        data = {}
        
        # Monitor system-wide resources
        if self.monitor_system:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=0.1)
            
            # Memory usage (MB)
            memory = psutil.virtual_memory()
            memory_mb = memory.used / (1024 **2)
            memory_percent = memory.percent
            
            # Network usage
            current_network_counters = psutil.net_io_counters(pernic=True)
            if self.system_network_counters:
                network_usage = 0
                for nic, counters in current_network_counters.items():
                    if nic in self.system_network_counters:
                        # Calculate difference in sent and received bytes
                        bytes_sent = counters.bytes_sent - self.system_network_counters[nic].bytes_sent
                        bytes_recv = counters.bytes_recv - self.system_network_counters[nic].bytes_recv
                        # Convert to Mbps
                        network_usage += (bytes_sent + bytes_recv) * 8 / (1024** 2) / self.update_interval
            else:
                network_usage = 0
            
            # Update last network I/O counters
            self.system_network_counters = current_network_counters
            
            # Disk usage
            disk_counters = psutil.disk_io_counters()
            disk_usage = (disk_counters.read_bytes + disk_counters.write_bytes) / (1024 **2) / self.update_interval
            
            # GPU usage
            try:
                gpus = GPUtil.getGPUs()
                if gpus:
                    gpu_usage = gpus[0].load * 100  # Convert to percentage
                else:
                    gpu_usage = 0
            except:
                gpu_usage = 0
            
            # Store system-wide data
            data["System"] = {
                'cpu': cpu_percent,
                'memory': memory_mb,
                'memory_percent': memory_percent,
                'network': network_usage,
                'disk': disk_usage,
                'gpu': gpu_usage,
                'pid': None,
                'username': os.getlogin()
            }
        
        # Get all process information
        current_process_network = {}  # Store current process network connections count
        
        for proc in psutil.process_iter(['name', 'cpu_percent', 'memory_info', 'pid', 'username']):
            try:
                process_name = proc.info['name'].lower()
                
                # Check if process name is in monitoring list
                for software in self.software_list:
                    if software.lower() in process_name:
                        # CPU usage
                        cpu_percent = proc.info['cpu_percent']
                        
                        # Memory usage (MB)
                        memory_mb = proc.info['memory_info'].rss / (1024** 2)
                        
                        # Network usage
                        try:
                            # Get process network connections
                            connections = proc.connections(kind='inet')
                            current_process_network[proc.info['pid']] = len(connections)
                            
                            # Estimate network usage based on connection count
                            if proc.info['pid'] in self.process_network_counters:
                                last_connections = self.process_network_counters[proc.info['pid']]
                                network_usage = len(connections) - last_connections
                                # If connection count decreases, it indicates data transmission
                                if network_usage < 0:
                                    network_usage = abs(network_usage) * 0.1  # Estimated value
                                else:
                                    network_usage = 0
                            else:
                                network_usage = 0
                            
                            # Limit maximum value
                            if network_usage > 100:
                                network_usage = 100
                            
                        except (psutil.AccessDenied, psutil.NoSuchProcess):
                            network_usage = 0
                        
                        # Disk usage
                        try:
                            # Get process I/O counters
                            io_counters = proc.io_counters()
                            if io_counters:
                                # Convert to MB/s
                                disk_usage = (io_counters.read_bytes + io_counters.write_bytes) / (1024 **2) / self.update_interval
                            else:
                                disk_usage = 0
                        except (psutil.AccessDenied, psutil.NoSuchProcess):
                            disk_usage = 0
                        
                        # GPU usage
                        try:
                            gpu_usage = 0
                            # Try to get GPU usage by process ID
                            # Note: This requires NVIDIA's pynvml library support
                            # Simplified handling here, actual implementation may need more complexity
                            gpus = GPUtil.getGPUs()
                            if gpus:
                                # Cannot directly get process GPU usage, example only
                                pass
                        except:
                            gpu_usage = 0
                        
                        # Store data
                        data[software] = {
                            'cpu': cpu_percent,
                            'memory': memory_mb,
                            'network': network_usage,
                            'disk': disk_usage,
                            'gpu': gpu_usage,
                            'pid': proc.info['pid'],
                            'username': proc.info['username'] if 'username' in proc.info else "Unknown"
                        }
                        
                        # Exit inner loop to avoid duplicate addition of the same process
                        break
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
        
        # Update process network counters
        self.process_network_counters = current_process_network
        
        # Set default values for software not found
        for software in self.software_list:
            if software not in data:
                data[software] = {
                    'cpu': 0,
                    'memory': 0,
                    'network': 0,
                    'disk': 0,
                    'gpu': 0,
                    'pid': None,
                    'username': "Unknown"
                }
        
        return data

class ProcessSelector(QDialog):
    """Process selection dialog"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Process")
        self.setMinimumSize(900, 600)  # Increase window size
        
        # Create layout
        layout = QVBoxLayout(self)
        
        # Filter area
        filter_layout = QHBoxLayout()
        
        # Process type filter
        self.process_type_combo = QComboBox()
        self.process_type_combo.addItems(["All Processes", "Applications", "System Processes", "User Processes"])
        self.process_type_combo.currentIndexChanged.connect(self.filter_processes)
        
        # Search box
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search processes...")
        self.search_edit.textChanged.connect(self.filter_processes)
        
        # Refresh button
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_processes)
        
        # Show icon checkbox
        self.show_icon_checkbox = QCheckBox("Show Icons")
        self.show_icon_checkbox.setChecked(True)
        self.show_icon_checkbox.stateChanged.connect(self.refresh_processes)
        
        filter_layout.addWidget(QLabel("Filter type:"))
        filter_layout.addWidget(self.process_type_combo)
        filter_layout.addWidget(QLabel("Search:"))
        filter_layout.addWidget(self.search_edit)
        filter_layout.addWidget(self.refresh_button)
        filter_layout.addWidget(self.show_icon_checkbox)
        
        layout.addLayout(filter_layout)
        
        # Create process tree
        self.process_tree = QTreeWidget()
        self.process_tree.setColumnCount(5)
        self.process_tree.setHeaderLabels(["Process Name", "PID", "Username", "CPU (%)", "Memory (MB)"])
        
        # Set column width policy
        self.process_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)  # Process name column auto-stretches
        self.process_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.process_tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.process_tree.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.process_tree.header().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        
        # Set font for better readability
        font = QFont()
        font.setPointSize(10)
        self.process_tree.setFont(font)
        
        # Set style to display full process names
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
        
        # Add to layout
        layout.addWidget(self.process_tree)
        
        # Button layout
        button_layout = QHBoxLayout()
        
        self.select_button = QPushButton("Select")
        self.select_button.clicked.connect(self.select_process)
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        
        button_layout.addStretch(1)
        button_layout.addWidget(self.select_button)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
        
        # Initialize process list
        self.refresh_processes()
        
        # Connect double-click event
        self.process_tree.itemDoubleClicked.connect(self.item_double_clicked)
        
        # Store original process data
        self.all_processes = []
    
    def refresh_processes(self):
        """Refresh process list"""
        self.process_tree.clear()
        self.all_processes = []
        
        # Get current user
        current_user = os.getlogin()
        
        # Create category root nodes
        self.all_root = QTreeWidgetItem(self.process_tree)
        self.all_root.setText(0, "All Processes")
        self.all_root.setExpanded(True)
        
        self.apps_root = QTreeWidgetItem(self.process_tree)
        self.apps_root.setText(0, "Applications")
        self.apps_root.setExpanded(True)
        
        self.system_root = QTreeWidgetItem(self.process_tree)
        self.system_root.setText(0, "System Processes")
        self.system_root.setExpanded(True)
        
        self.user_root = QTreeWidgetItem(self.process_tree)
        self.user_root.setText(0, "User Processes")
        self.user_root.setExpanded(True)
        
        # Get all processes
        for proc in psutil.process_iter(['name', 'cpu_percent', 'memory_info', 'username', 'pid']):
            try:
                process_name = proc.info['name']
                pid = proc.info['pid']
                cpu_percent = proc.info['cpu_percent']
                memory_mb = proc.info['memory_info'].rss / (1024** 2)
                username = proc.info['username'] if 'username' in proc.info else "Unknown"
                
                # Store original process data
                process_data = {
                    'name': process_name,
                    'pid': pid,
                    'username': username,
                    'cpu_percent': cpu_percent,
                    'memory_mb': memory_mb
                }
                self.all_processes.append(process_data)
                
                # Create process item
                process_item = QTreeWidgetItem()
                
                # Set process name, use ellipsis for long names
                process_item.setText(0, process_name)
                process_item.setToolTip(0, process_name)  # Set full name as tooltip
                
                process_item.setText(1, str(pid))
                process_item.setText(2, username)
                process_item.setText(3, f"{cpu_percent:.1f}")
                process_item.setText(4, f"{memory_mb:.1f}")
                
                # Set background color, processes with high CPU usage show red
                if cpu_percent > 50:
                    for i in range(5):
                        process_item.setBackground(i, QColor(255, 200, 200))
                        
                # Categorize by user
                self.all_root.addChild(process_item.clone())
                
                # Determine if it's an application
                is_application = self.is_application(process_name)
                if is_application:
                    self.apps_root.addChild(process_item.clone())
                
                # Categorize by user
                if username == current_user:
                    self.user_root.addChild(process_item.clone())
                else:
                    self.system_root.addChild(process_item.clone())
                    
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
        
        # Apply filter
        self.filter_processes()
    
    def is_application(self, process_name):
        """Determine if it's an application"""
        # Common application extensions
        app_extensions = ['.exe', '.app', '.jar', '.pyw']
        
        # Common application names
        app_names = ['chrome', 'firefox', 'explorer', 'word', 'excel', 'powerpoint', 
                    'notepad', 'photoshop', 'premiere', 'aftereffects', 'vscode', 'sublime']
        
        process_name_lower = process_name.lower()
        
        # Check extensions
        for ext in app_extensions:
            if process_name_lower.endswith(ext):
                return True
        
        # Check names
        for name in app_names:
            if name in process_name_lower:
                return True
        
        return False
    
    def filter_processes(self):
        """Filter processes according to filter criteria"""
        filter_type = self.process_type_combo.currentText()
        search_text = self.search_edit.text().lower()
        
        # Hide all root nodes
        self.all_root.setHidden(True)
        self.apps_root.setHidden(True)
        self.system_root.setHidden(True)
        self.user_root.setHidden(True)
        
        # Show corresponding root node according to filter type
        if filter_type == "All Processes":
            self.all_root.setHidden(False)
        elif filter_type == "Applications":
            self.apps_root.setHidden(False)
        elif filter_type == "System Processes":
            self.system_root.setHidden(False)
        elif filter_type == "User Processes":
            self.user_root.setHidden(False)
        
        # Get current root node
        if filter_type == "All Processes":
            current_root = self.all_root
        elif filter_type == "Applications":
            current_root = self.apps_root
        elif filter_type == "System Processes":
            current_root = self.system_root
        elif filter_type == "User Processes":
            current_root = self.user_root
        else:
            current_root = self.all_root
        
        # Traverse all child items
        for i in range(current_root.childCount()):
            child = current_root.child(i)
            
            # If there is search text, check for match
            if search_text and not (search_text in child.text(0).lower() or 
                                  search_text in child.text(1).lower() or 
                                  search_text in child.text(2).lower()):
                child.setHidden(True)
            else:
                child.setHidden(False)
    
    def item_double_clicked(self, item, column):
        """Select process when item is double-clicked"""
        # Ensure it's not a top-level item
        if item.parent() is not None:
            self.select_process()
    
    def select_process(self):
        """Select process and return"""
        selected_items = self.process_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Warning", "Please select a process first!")
            return
            
        # Get first selected item
        item = selected_items[0]
        
        # Ensure it's not a top-level item
        if item.parent() is not None:
            process_name = item.text(0)
            self.selected_process = process_name
            self.accept()

class MplCanvas(FigureCanvas):
    """Matplotlib canvas for displaying charts"""
    def __init__(self, parent=None, width=5, height=4, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.axes = self.fig.add_subplot(111)
        super(MplCanvas, self).__init__(self.fig)
        self.fig.tight_layout()
    
    def __del__(self):
        """Clean up resources"""
        self.axes.clear()
        self.fig.clear()

class ResourceMonitor(QMainWindow):
    """Main window class"""
    def __init__(self):
        super().__init__()
        
        # Set Chinese font
        font = QFont()
        font.setFamily("SimHei")
        font.setPointSize(10)
        QApplication.setFont(font)
        
        # Store monitoring data
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
        
        # Maximum history points
        self.max_history_points = 60
        
        # System-wide monitoring option
        self.monitor_system = False
        
        # Create UI
        self.init_ui()
        
        # Get system information
        self.update_system_info()
    
    def init_ui(self):
        """Initialize user interface"""
        # Set window title and size
        self.setWindowTitle("Software Resource Monitoring System")
        self.setGeometry(100, 100, 1200, 800)
        
        # Create main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # System information bar
        self.system_info_label = QLabel("System information will be displayed here...")
        main_layout.addWidget(self.system_info_label)
        
        # Splitter, divided into upper and lower parts
        splitter = QSplitter(Qt.Vertical)
        
        # Control panel
        control_widget = QWidget()
        control_layout = QVBoxLayout(control_widget)
        
        # Software monitoring group
        software_group = QGroupBox("Monitored Software")
        software_layout = QHBoxLayout()
        
        software_label = QLabel("Software name:")
        self.software_entry = QLineEdit()
        self.software_entry.setPlaceholderText("Enter software name or select from process list")
        
        self.select_process_button = QPushButton("Select from Processes")
        self.select_process_button.clicked.connect(self.select_process)
        
        add_button = QPushButton("Add")
        add_button.clicked.connect(self.add_software)
        
        remove_button = QPushButton("Remove")
        remove_button.clicked.connect(self.remove_software)
        
        # System-wide monitoring checkbox
        self.system_monitor_checkbox = QCheckBox("Monitor system-wide resources")
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
        
        # Settings group
        settings_group = QGroupBox("Monitoring Settings")
        settings_layout = QFormLayout()
        
        self.update_interval_spinbox = QDoubleSpinBox()
        self.update_interval_spinbox.setRange(0.1, 10.0)
        self.update_interval_spinbox.setValue(1.0)
        self.update_interval_spinbox.setSingleStep(0.1)
        self.update_interval_spinbox.setSuffix(" seconds")
        
        self.history_points_spinbox = QSpinBox()
        self.history_points_spinbox.setRange(10, 1000)
        self.history_points_spinbox.setValue(60)
        self.history_points_spinbox.setSuffix(" points")
        
        self.start_button = QPushButton("Start Monitoring")
        self.start_button.setCheckable(True)
        self.start_button.toggled.connect(self.toggle_monitoring)
        
        settings_layout.addRow("Update interval:", self.update_interval_spinbox)
        settings_layout.addRow("History points:", self.history_points_spinbox)
        settings_layout.addRow(self.start_button)
        
        settings_group.setLayout(settings_layout)
        control_layout.addWidget(settings_group)
        
        # Export buttons
        export_layout = QHBoxLayout()
        self.export_json_button = QPushButton("Export JSON")
        self.export_json_button.clicked.connect(lambda: self.export_data("json"))
        
        self.export_csv_button = QPushButton("Export CSV")
        self.export_csv_button.clicked.connect(lambda: self.export_data("csv"))
        
        export_layout.addStretch(1)
        export_layout.addWidget(self.export_json_button)
        export_layout.addWidget(self.export_csv_button)
        
        control_layout.addLayout(export_layout)
        
        # Add control area to splitter
        splitter.addWidget(control_widget)
        
        # Chart area - using tab layout
        self.chart_tabs = QTabWidget()
        
        # CPU chart
        self.cpu_canvas = MplCanvas(self, width=5, height=4, dpi=100)
        self.chart_tabs.addTab(self.cpu_canvas, "CPU Usage (%)")
        
        # Memory chart
        self.memory_canvas = MplCanvas(self, width=5, height=4, dpi=100)
        self.chart_tabs.addTab(self.memory_canvas, "Memory Usage (MB)")
        
        # Network chart
        self.network_canvas = MplCanvas(self, width=5, height=4, dpi=100)
        self.chart_tabs.addTab(self.network_canvas, "Network Usage (Mbps)")
        
        # Disk chart
        self.disk_canvas = MplCanvas(self, width=5, height=4, dpi=100)
        self.chart_tabs.addTab(self.disk_canvas, "Disk Usage (MB/s)")
        
        # GPU chart
        self.gpu_canvas = MplCanvas(self, width=5, height=4, dpi=100)
        self.chart_tabs.addTab(self.gpu_canvas, "GPU Usage (%)")
        
        # Add chart area to splitter
        splitter.addWidget(self.chart_tabs)
        
        # Set splitter proportions
        splitter.setSizes([200, 600])
        
        # Add splitter to main layout
        main_layout.addWidget(splitter)
        
        # Add status bar
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Ready")
    
    def update_system_info(self):
        """Update system information"""
        try:
            # CPU information
            cpu_count = psutil.cpu_count(logical=False)
            cpu_freq = psutil.cpu_freq().current / 1000  # GHz
            
            # Memory information
            memory = psutil.virtual_memory()
            total_memory = round(memory.total / (1024** 3), 2)  # GB
            
            # Operating system information
            import platform
            os_info = platform.platform()
            
            # GPU information
            try:
                gpus = GPUtil.getGPUs()
                if gpus:
                    gpu_info = gpus[0].name
                else:
                    gpu_info = "No GPU detected"
            except:
                gpu_info = "Unable to get GPU information"
            
            # Update information label
            info_text = f"OS: {os_info} | CPU: {cpu_count} cores @ {cpu_freq:.2f}GHz | Memory: {total_memory}GB | GPU: {gpu_info}"
            self.system_info_label.setText(info_text)
            
        except Exception as e:
            self.system_info_label.setText(f"Failed to get system information: {e}")
    
    def select_process(self):
        """Open process selection dialog"""
        dialog = ProcessSelector(self)
        if dialog.exec_():
            # Get selected process
            process_name = dialog.selected_process
            self.software_entry.setText(process_name)
    
    def toggle_system_monitoring(self, state):
        """Toggle system-wide monitoring option"""
        self.monitor_system = state == Qt.Checked
        
        # If monitoring is in progress, restart monitoring thread
        if self.monitor_thread and self.monitor_thread.isRunning():
            self.toggle_monitoring(False)
            self.toggle_monitoring(True)
    
    def add_software(self):
        """Add software to monitoring list"""
        software_name = self.software_entry.text().strip()
        if software_name and software_name not in self.software_list:
            self.software_list.append(software_name)
            self.software_listbox.addItem(software_name)
            self.software_entry.clear()
            
            # Initialize chart data
            self.cpu_data[software_name] = []
            self.memory_data[software_name] = []
            self.network_data[software_name] = []
            self.disk_data[software_name] = []
            self.gpu_data[software_name] = []
            self.pid_data[software_name] = []
            self.username_data[software_name] = []
    
    def remove_software(self):
        """Remove software from monitoring list"""
        selected_items = self.software_listbox.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Warning", "Please select the software to remove first!")
            return
            
        for item in selected_items:
            software_name = item.text()
            self.software_list.remove(software_name)
            self.software_listbox.takeItem(self.software_listbox.row(item))
            
            # Remove chart data
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
        """Start or stop monitoring"""
        if checked:
            if not self.software_list and not self.monitor_system:
                QMessageBox.warning(self, "Warning", "Please add software to monitor or select system-wide resource monitoring first!")
                self.start_button.setChecked(False)
                return
                
            # Reset data
            self.time_data = []
            for software in self.software_list:
                self.cpu_data[software] = []
                self.memory_data[software] = []
                self.network_data[software] = []
                self.disk_data[software] = []
                self.gpu_data[software] = []
                self.pid_data[software] = []
                self.username_data[software] = []
            
            # If monitoring system-wide, initialize system data
            if self.monitor_system:
                self.cpu_data["System"] = []
                self.memory_data["System"] = []
                self.network_data["System"] = []
                self.disk_data["System"] = []
                self.gpu_data["System"] = []
                self.pid_data["System"] = []
                self.username_data["System"] = []
            
            # Update maximum history points
            self.max_history_points = self.history_points_spinbox.value()
            
            # Start monitoring thread
            self.monitor_thread = MonitorThread(
                self.software_list, 
                self.update_interval_spinbox.value(),
                self.monitor_system
            )
            self.monitor_thread.update_signal.connect(self.update_charts)
            self.monitor_thread.finished.connect(self.monitoring_finished)
            self.monitor_thread.start()
            
            # Update UI status
            self.start_button.setText("Stop Monitoring")
            self.software_entry.setEnabled(False)
            self.select_process_button.setEnabled(False)
            self.system_monitor_checkbox.setEnabled(False)
            self.export_json_button.setEnabled(False)
            self.export_csv_button.setEnabled(False)
            self.update_interval_spinbox.setEnabled(False)
            self.history_points_spinbox.setEnabled(False)
            
            self.statusBar.showMessage("Monitoring...")
        else:
            # Stop monitoring thread
            if self.monitor_thread and self.monitor_thread.isRunning():
                self.monitor_thread.stop()
                self.monitor_thread.wait()
                self.monitor_thread = None
    
    def monitoring_finished(self):
        """Handle monitoring completion"""
        # Update UI status
        self.start_button.setText("Start Monitoring")
        self.software_entry.setEnabled(True)
        self.select_process_button.setEnabled(True)
        self.system_monitor_checkbox.setEnabled(True)
        self.export_json_button.setEnabled(True)
        self.export_csv_button.setEnabled(True)
        self.update_interval_spinbox.setEnabled(True)
        self.history_points_spinbox.setEnabled(True)
        
        self.statusBar.showMessage("Monitoring stopped")
    
    def update_charts(self, data):
        """Update chart display"""
        # Get current time
        current_time = QDateTime.currentDateTime().toString("HH:mm:ss")
        self.time_data.append(current_time)
        
        # Limit number of data points
        if len(self.time_data) > self.max_history_points:
            self.time_data.pop(0)
        
        # Process data for each software
        for software, metrics in data.items():
            # Add data to corresponding lists
            self.cpu_data[software].append(metrics['cpu'])
            self.memory_data[software].append(metrics['memory'])
            self.network_data[software].append(metrics['network'])
            self.disk_data[software].append(metrics['disk'])
            self.gpu_data[software].append(metrics['gpu'])
            self.pid_data[software].append(metrics['pid'])
            self.username_data[software].append(metrics['username'])
            
            # Limit number of data points
            if len(self.cpu_data[software]) > self.max_history_points:
                self.cpu_data[software].pop(0)
                self.memory_data[software].pop(0)
                self.network_data[software].pop(0)
                self.disk_data[software].pop(0)
                self.gpu_data[software].pop(0)
                self.pid_data[software].pop(0)
                self.username_data[software].pop(0)
        
        # Update charts
        self._update_canvas(self.cpu_canvas, self.cpu_data, "CPU Usage (%)")
        self._update_canvas(self.memory_canvas, self.memory_data, "Memory Usage (MB)")
        self._update_canvas(self.network_canvas, self.network_data, "Network Usage (Mbps)")
        self._update_canvas(self.disk_canvas, self.disk_data, "Disk Usage (MB/s)")
        self._update_canvas(self.gpu_canvas, self.gpu_data, "GPU Usage (%)")
    
    def _update_canvas(self, canvas, data, title):
        """Update a single canvas"""
        canvas.axes.clear()
        canvas.axes.set_title(title)
        canvas.axes.set_xlabel("Time")
        canvas.axes.grid(True)
        
        # Draw lines for each software
        colors = ['b', 'g', 'r', 'c', 'm', 'y', 'k', 'tab:orange', 'tab:purple', 'tab:brown']
        
        if self.time_data:
            for i, software in enumerate(data.keys()):
                color = colors[i % len(colors)]
                
                # Get latest PID and username
                last_pid = self.pid_data[software][-1] if self.pid_data[software] else "N/A"
                last_username = self.username_data[software][-1] if self.username_data[software] else "N/A"
                
                # ׼��ͼ���ı�
                label = f"{software} (PID: {last_pid}, �û�: {last_username})"
                
                # ��������
                canvas.axes.plot(self.time_data, data[software], label=label, color=color, linewidth=2)
            
            # �Զ���תx���ǩ
            canvas.axes.tick_params(axis='x', rotation=45)
            
            # ����ͼ��������λ��
            canvas.axes.legend(loc='upper left', bbox_to_anchor=(1, 1))
            
            # ���������Է�ֹ��ǩ���ض�
            canvas.fig.tight_layout()
        
        # ���»���
        canvas.draw()
    
    def export_data(self, format_type):
        """�����������"""
        if not self.time_data:
            QMessageBox.warning(self, "����", "û�пɵ���������!")
            return
        
        # ��ȡ����·��
        current_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"resource_monitor_data_{current_time}"
        
        if format_type == "json":
            default_filename += ".json"
            file_path, _ = QFileDialog.getSaveFileName(
                self, "����JSON", default_filename, "JSON Files (*.json)"
            )
            
            if file_path:
                try:
                    # ׼����������
                    export_data = {
                        "timestamp": datetime.datetime.now().isoformat(),
                        "time_points": self.time_data,
                        "software": {}
                    }
                    
                    for software in self.cpu_data.keys():
                        export_data["software"][software] = {
                            "cpu": self.cpu_data[software],
                            "memory": self.memory_data[software],
                            "network": self.network_data[software],
                            "disk": self.disk_data[software],
                            "gpu": self.gpu_data[software],
                            "pid": self.pid_data[software],
                            "username": self.username_data[software]
                        }
                    
                    # д��JSON�ļ�
                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump(export_data, f, ensure_ascii=False, indent=2)
                    
                    QMessageBox.information(self, "�ɹ�", f"�����ѳɹ������� {file_path}")
                except Exception as e:
                    QMessageBox.critical(self, "����", f"��������ʧ��: {str(e)}")
        
        elif format_type == "csv":
            default_filename += ".csv"
            file_path, _ = QFileDialog.getSaveFileName(
                self, "����CSV", default_filename, "CSV Files (*.csv)"
            )
            
            if file_path:
                try:
                    with open(file_path, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        
                        # д���ͷ
                        header = ["ʱ��"]
                        for software in self.cpu_data.keys():
                            header.extend([
                                f"{software}_CPU(%)",
                                f"{software}_�ڴ�(MB)",
                                f"{software}_����(Mbps)",
                                f"{software}_Ӳ��(MB/s)",
                                f"{software}_GPU(%)",
                                f"{software}_PID",
                                f"{software}_�û�"
                            ])
                        writer.writerow(header)
                        
                        # д��������
                        for i, time_point in enumerate(self.time_data):
                            row = [time_point]
                            for software in self.cpu_data.keys():
                                row.extend([
                                    self.cpu_data[software][i] if i < len(self.cpu_data[software]) else "",
                                    self.memory_data[software][i] if i < len(self.memory_data[software]) else "",
                                    self.network_data[software][i] if i < len(self.network_data[software]) else "",
                                    self.disk_data[software][i] if i < len(self.disk_data[software]) else "",
                                    self.gpu_data[software][i] if i < len(self.gpu_data[software]) else "",
                                    self.pid_data[software][i] if i < len(self.pid_data[software]) else "",
                                    self.username_data[software][i] if i < len(self.username_data[software]) else ""
                                ])
                            writer.writerow(row)
                    
                    QMessageBox.information(self, "�ɹ�", f"�����ѳɹ������� {file_path}")
                except Exception as e:
                    QMessageBox.critical(self, "����", f"��������ʧ��: {str(e)}")
    
    def closeEvent(self, event):
        """�رմ���ʱ�Ĵ���"""
        # ֹͣ����߳�
        if self.monitor_thread and self.monitor_thread.isRunning():
            self.monitor_thread.stop()
            self.monitor_thread.wait()
        
        event.accept()

if __name__ == "__main__":
    # ȷ��������ʾ����
    plt.rcParams["font.family"] = ["SimHei", "WenQuanYi Micro Hei", "Heiti TC"]
    
    app = QApplication(sys.argv)
    window = ResourceMonitor()
    window.show()
    sys.exit(app.exec_())