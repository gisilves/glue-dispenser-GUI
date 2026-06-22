import sys
import threading
import time
import re
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QFileDialog, QLabel, 
    QComboBox, QHBoxLayout, QMessageBox, QTabWidget, QGridLayout, QFrame,
    QLineEdit
)
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import pyqtSignal, QObject
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.patches as patches
import serial
import serial.tools.list_ports
import os.path
import heapq


class Communicator(QObject):
    update_status_signal = pyqtSignal(str)
    first_block_signal = pyqtSignal()

class GRBLController(QWidget):
    show_message_box_signal = pyqtSignal()

    def __init__(self):
        """
        Initialize the GRBLController widget.

        This constructor sets up the main window for the PG GLUE DISPENSER application, 
        initializes various attributes related to the serial communication, toolpath handling, 
        and UI components. It also connects signals for status updates and first block detection, 
        and initializes the user interface and available serial ports.

        Attributes:
            serial_port: Serial port object used for communication.
            sending: Boolean indicating if G-code is currently being sent.
            paused: Boolean indicating if the sending of G-code is paused.
            connected: Boolean indicating if the device is connected.
            coordinates: List of tuples representing toolpath coordinates.
            glued_coordinates: List of tuples representing coordinates with glue applied.
            maximumTravel: Maximum travel distance for the X axis.
            thread: Thread object for handling G-code sending in a separate thread.
            comm: Communicator object for emitting and connecting signals.
            debug: Boolean indicating if the application is in debug mode.
        """

        super().__init__()

        self.setWindowTitle("PG GLUE DISPENSER")
        self.resize(800, 600)

        self.serial_port = None
        self.sending = False
        self.paused = False
        self.connected = False
        self.coordinates = [(0, 0)]
        self.glued_coordinates = [(0, 0)]
        self.x_position = 0
        self.y_position = 0
        self.maximumTravel = 990
        self.thread = None
        self.comm = Communicator()
        self.comm.update_status_signal.connect(self.update_status)
        self.comm.first_block_signal.connect(self.first_point_reached)
        self.show_message_box_signal.connect(self.show_message_box)
        
        self.init_ui()
        self.scan_ports()

        self.debug = False

    def init_ui(self):
        """
            Initializes the UI components of the GRBLController widget, including the status label, tab widget, and various buttons and selectors.
        """

        main_layout = QVBoxLayout()

        # Status label (always visible)
        self.status_label = QLabel("Status: Idle")
        self.status_label.setStyleSheet("""
            font-size: 18px; 
            font-weight: bold; 
            color: white; 
            background-color: #2e3a47;
            padding: 10px;
            border-radius: 5px;
        """)
        main_layout.addWidget(self.status_label)

        self.small_enabled_button_style = """
            QPushButton {
                font-size: 16px;           /* Font size */
                font-weight: bold;         /* Bold text */
                min-width: 30px;           /* Minimum width */
                min-height: 30px;         /* Minimum height */
            }
        """

        self.enabled_button_style = """
            QPushButton {
                background-color: #4CAF50;  /* Green background */
                color: white;              /* White text */
                border: none;              /* No border */
                border-radius: 10px;       /* Rounded corners */
                padding: 10px;            /* Padding */
                font-size: 16px;           /* Font size */
                font-weight: bold;         /* Bold text */
                min-width: 60px;           /* Minimum width */
                min-height: 60px;         /* Minimum height */
            }
            QPushButton:hover {
                background-color: #45a049; /* Darker green on hover */
            }
            QPushButton:pressed {
                background-color: #3d8b40; /* Even darker green when pressed */
            }
        """

        self.disabled_button_style = """
            QPushButton {
                background-color: #bfbfbf;  /* Gray background */
                color: white;              /* White text */
                border: none;              /* No border */
                border-radius: 10px;       /* Rounded corners */
                padding: 10px;            /* Padding */
                font-size: 16px;           /* Font size */
                font-weight: bold;         /* Bold text */
                min-width: 60px;           /* Minimum width */
                min-height: 60px;         /* Minimum height */
            }
        """

        # Connection layout (always visible)
        port_layout = QHBoxLayout()
        self.port_selector = QComboBox()
        port_layout.addWidget(self.port_selector)

        # Refresh button
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.scan_ports)
        refresh_button.setStyleSheet(self.small_enabled_button_style)
        port_layout.addWidget(refresh_button)

        self.baud_selector = QComboBox()
        self.baud_selector.addItems(["9600", "115200", "250000"])
        self.baud_selector.setCurrentText("115200")
        port_layout.addWidget(self.baud_selector)

        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.toggle_connection)
        self.connect_button.setStyleSheet(self.small_enabled_button_style)
        port_layout.addWidget(self.connect_button)

        # Retrieve refresh button size
        refresh_button_size = refresh_button.sizeHint()
        refresh_button_height = refresh_button_size.height()
        self.port_selector.setFixedHeight(refresh_button_height)
        self.baud_selector.setFixedHeight(refresh_button_height)
        main_layout.addLayout(port_layout)

        # Tab widget
        self.tabs = QTabWidget()

        # Tab 1 - Main GUI
        self.main_tab = QWidget()
        self.main_tab_layout = QVBoxLayout()

        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)
        self.figure.subplots_adjust(left=0.05, right=0.95, bottom=0.05, top=0.95)
        self.ax = self.figure.add_subplot(111)
        self.ax.axis('off')
        if self.debug:
            print("Debug mode enabled.")
            # Add "DEBUG MODE" text to the plot
            self.ax.text(0.5, 0.5, "DEBUG MODE", fontsize=24, ha='center', va='center', color='red')
            self.ax.text(0.5, 0.4, "No serial communication", fontsize=16, ha='center', va='center', color='red')
            self.ax.text(0.5, 0.3, "G-code commands will only be printed on terminal", fontsize=16, ha='center', va='center', color='red')
        else:
            # Check if logo.png is present
            if os.path.isfile('logo.png'):
                self.ax.imshow(plt.imread('logo.png'))  # Logo as background
            else:
                self.ax.text(0.5, 0.5, "NORMAL MODE", fontsize=24, ha='center', va='center', color='red')
                self.ax.text(0.5, 0.4, "logo.png not found", fontsize=16, ha='center', va='center', color='red')
        self.main_tab_layout.addWidget(self.canvas)

        self.load_button = QPushButton("Load G-code File")
        self.load_button.setEnabled(False)
        self.load_button.clicked.connect(self.load_file)
        self.load_button.setStyleSheet(self.small_enabled_button_style)
        self.main_tab_layout.addWidget(self.load_button)

        # File label (always visible)
        self.file_label = QLabel("No file loaded")
        self.file_label.setStyleSheet("""
            font-size: 18px;
            font-weight: bold;
            border: 2px solid #2e3a47;
            padding: 10px;
            border-radius: 5px;
        """)
        
        
        # Retrieve Load button size
        load_button_size = self.load_button.sizeHint()
        load_button_height = load_button_size.height()
        self.file_label.setFixedHeight(load_button_height + 15)
        self.main_tab_layout.addWidget(self.file_label)

        settings_layout = QHBoxLayout()
        settings_layout.addWidget(QLabel("First Point:"))
        self.first_block_selector = QComboBox()
        self.first_block_selector.setEnabled(False)
        self.first_block_selector.setFixedHeight(load_button_height)
        settings_layout.addWidget(self.first_block_selector)

        settings_layout.addWidget(QLabel("Last Point:"))
        self.last_block_selector = QComboBox()
        self.last_block_selector.setEnabled(False)
        self.last_block_selector.setFixedHeight(load_button_height)
        settings_layout.addWidget(self.last_block_selector)

        self.main_tab_layout.addLayout(settings_layout)

        button_layout = QHBoxLayout()
        self.start_button = QPushButton("Start Sending")
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self.start_sending)
        self.start_button.setStyleSheet(self.small_enabled_button_style)
        button_layout.addWidget(self.start_button)

        self.pause_button = QPushButton("Pause")
        self.pause_button.setEnabled(False)
        self.pause_button.clicked.connect(self.toggle_pause)
        self.pause_button.setStyleSheet(self.small_enabled_button_style)
        button_layout.addWidget(self.pause_button)

        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_sending)
        self.stop_button.setStyleSheet(self.small_enabled_button_style)
        button_layout.addWidget(self.stop_button)

        self.main_tab_layout.addLayout(button_layout)

        self.main_tab.setLayout(self.main_tab_layout)

        self.tabs.addTab(self.main_tab, "Main Control")

        # Tab 2 - Manual movement
        self.manual_tab = QWidget()
        self.manual_tab_layout = QHBoxLayout()

        self.manual_tab.setLayout(self.manual_tab_layout)
        self.tabs.addTab(self.manual_tab, "Manual Control")

        # Left side: Jog controls
        jog_controls_widget = QWidget()
        jog_layout = QVBoxLayout()
        

        instructions = """
            1. Power off motors and glue dispenser (you can use the power strip switch)\n
            2. Select Arduino port and press connect\n
            3. Power on motors and glue dispenser\n
            4. Home the machine\n
            5. For standard operation:\n
	        \ta. If the syringe is new, press "Dispense" as many time as needed to purge\n
	        \tb. Load desired GCode file in "Main Control" tab\n
	        \tc. Press "Point 0" to move to first point of the glueing path\n
	        \td. Press "Lower Syringe" and verify position on the ladder\n
            \t\ti. If X coordinate is right, adjust Y position by moving the syringe in its holder (after raising it)\n
		    \t\tii. If X coordinate is right, use manual controls to find the offset, correct GCode file and restart procedure\n
		    \t\tiii. If needed, press "Ladder End" to move to last point of the line (without glue dispensing)\n
	        \te. Press "Raise Syringe" and continue on "Main Control" tab\n\n\n
            N.B. GUI might freeze during homing, don't touch it before it ends\n\n\n
            Homing is needed to enable manual control
            """

        self.warning_label = QLabel(instructions.expandtabs(4))
        

        self.warning_label.setStyleSheet("""
            font-size: 15px;
            font-weight: bold;
            border: 2px solid #2e3a47;
            padding: 10px;
            border-radius: 5px;
        """)

        # Set label size at half of the window height
        label_height = self.height() // 2

        jog_layout.addWidget(self.warning_label)
        
        jog_controls_widget.setLayout(jog_layout)

        # Add jog controls to the left side of the manual tab
        self.manual_tab_layout.addWidget(jog_controls_widget)

        # Add a vertical separator line
        separator = QFrame()
        separator.setFrameShape(QFrame.VLine)
        separator.setFrameShadow(QFrame.Sunken)
        self.manual_tab_layout.addWidget(separator)

        # Right side: Additional controls
        additional_controls_widget = QWidget()
        additional_layout = QVBoxLayout()

        # Add spacing and margins to layouts
        jog_layout.setSpacing(10)
        jog_layout.setContentsMargins(10, 10, 10, 10)  # Left, Top, Right, Bottom

        additional_layout.setSpacing(10)
        additional_layout.setContentsMargins(10, 10, 10, 10)

        # Add X steps control with label
        x_steps_layout = QHBoxLayout()
        x_steps_layout.addWidget(QLabel("X Step (mm):"))
        self.x_steps_selector = QLineEdit()
        self.x_steps_selector.setText("1")
        self.x_steps_selector.setFixedWidth(100)
        x_steps_layout.addWidget(self.x_steps_selector)
        additional_layout.addLayout(x_steps_layout)

        # Add Y steps control with label
        y_steps_layout = QHBoxLayout()
        y_steps_layout.addWidget(QLabel("Y Step (mm):"))
        self.y_steps_selector = QLineEdit()
        self.y_steps_selector.setText("1")
        self.y_steps_selector.setFixedWidth(100)
        y_steps_layout.addWidget(self.y_steps_selector)
        additional_layout.addLayout(y_steps_layout)

        # Add feed rate control with label
        feed_rate_layout = QHBoxLayout()
        feed_rate_layout.addWidget(QLabel("Feed Rate (mm/min):"))
        self.feed_rate_selector = QLineEdit()
        self.feed_rate_selector.setText("500")
        self.feed_rate_selector.setFixedWidth(100)
        feed_rate_layout.addWidget(self.feed_rate_selector)
        additional_layout.addLayout(feed_rate_layout)

        # Add horizontal separator line
        separator2 = QFrame()
        separator2.setFrameShape(QFrame.HLine)
        separator2.setFrameShadow(QFrame.Sunken)
        additional_layout.addWidget(separator2)

        # Jog Buttons        
        grid = QGridLayout()
        self.btnYplus = QPushButton("Y+")
        self.btnYplus.setStyleSheet(self.disabled_button_style)
        self.btnYplus.setEnabled(False)

        self.btnYminus = QPushButton("Y-")
        self.btnYminus.setStyleSheet(self.disabled_button_style)
        self.btnYminus.setEnabled(False)

        self.btnXplus = QPushButton("X+")
        self.btnXplus.setStyleSheet(self.disabled_button_style)
        self.btnXplus.setEnabled(False)

        self.btnXminus = QPushButton("X-")
        self.btnXminus.setStyleSheet(self.disabled_button_style)
        self.btnXminus.setEnabled(False)

        self.btnHome = QPushButton("Home")
        self.btnHome.setStyleSheet(self.disabled_button_style)
        self.btnHome.setEnabled(False)

        # Add buttons to the grid
        grid.addWidget(self.btnYplus, 0, 1)
        grid.addWidget(self.btnYminus, 2, 1)
        grid.addWidget(self.btnXplus, 1, 2)
        grid.addWidget(self.btnXminus, 1, 0)
        grid.addWidget(self.btnHome, 1, 1)
        
        additional_layout.addLayout(grid)

        additional_controls_widget.setLayout(additional_layout)

        # Add separator line
        separator3 = QFrame()
        separator3.setFrameShape(QFrame.HLine)
        separator3.setFrameShadow(QFrame.Sunken)
        additional_layout.addWidget(separator3)

        button_layout = QHBoxLayout()
        self.GoTo0 = QPushButton("Point 0")
        self.GoTo0.clicked.connect(self.move_to_point0)
        self.GoTo0.setStyleSheet(self.disabled_button_style)
        self.GoTo0.setEnabled(False)
        button_layout.addWidget(self.GoTo0)

        self.GoToEnd = QPushButton("Ladder End")
        self.GoToEnd.clicked.connect(self.move_to_ladder_end)
        self.GoToEnd.setStyleSheet(self.disabled_button_style)
        self.GoToEnd.setEnabled(False)
        button_layout.addWidget(self.GoToEnd)

        self.lowerSyringe = QPushButton("Lower Syringe")
        self.lowerSyringe.setStyleSheet(self.disabled_button_style)
        self.lowerSyringe.clicked.connect(self.lower_syringe)
        self.lowerSyringe.setEnabled(False)
        button_layout.addWidget(self.lowerSyringe)

        self.raiseSyringe = QPushButton("Raise Syringe")
        self.raiseSyringe.setStyleSheet(self.disabled_button_style)
        self.raiseSyringe.clicked.connect(self.raise_syringe)
        self.raiseSyringe.setEnabled(False)
        button_layout.addWidget(self.raiseSyringe)

        self.dispense = QPushButton("Dispense")
        self.dispense.setStyleSheet(self.disabled_button_style)
        self.dispense.clicked.connect(self.dispense_glue)
        self.dispense.setEnabled(False)
        button_layout.addWidget(self.dispense)

        additional_layout.addLayout(button_layout)
        
        # Add additional controls to the right side of the manual tab
        self.manual_tab_layout.addWidget(additional_controls_widget)

        # Add the tabs to the main layout
        main_layout.addWidget(self.tabs)
        self.setLayout(main_layout)

        # Connect controls to functions
        self.btnYplus.clicked.connect(self.manual_move)
        self.btnYminus.clicked.connect(self.manual_move)
        self.btnXplus.clicked.connect(self.manual_move)
        self.btnXminus.clicked.connect(self.manual_move)

        self.btnHome.clicked.connect(self.move_home)

        self.feed_rate_selector.textChanged.connect(self.update_feed_rate)

    def move_to_point0(self):
        """
        Move the toolhead to Point 0 in the toolpath.

        If no coordinates are loaded, a warning message box is displayed. 
        
        If the application is in debug mode, the command is printed instead of sent.

        Raises:
            QMessageBox: If no coordinates are loaded, a warning is shown.
        """

        self.sending = True
        self.comm.update_status_signal.emit("Moving to Point 0")
        if self.coordinates[1:]:
            x_vals, y_vals = zip(*self.coordinates)
            x0 = min(sorted(set(x_vals)))
            y0 = heapq.nsmallest(3, sorted(set(y_vals)))[1]
        else:
            QMessageBox.warning(self, "WARNING", "No coordinates loaded", QMessageBox.Abort)
            return

        command = f"G0 X{x0} Y{y0}"
        if GRBLController.debug:
            self.print_lines([command])
        else:
            self.send_lines([command])
        self.sending = False

    def move_to_ladder_end(self):
        """
        Move the toolhead to the end of the ladder in the toolpath (on first line).

        If no coordinates are loaded, a warning message box is displayed. 
        
        If the application is in debug mode, the command is printed instead of sent.

        Raises:
            QMessageBox: If no coordinates are loaded, a warning is shown.
        """
        self.sending = True
        self.comm.update_status_signal.emit("Moving to Ladder End")
        if self.coordinates[1:]:
            x_vals, y_vals = zip(*self.coordinates)
            xEnd = max(x_vals)
            yEnd = min(y_vals)
        else:
            QMessageBox.warning(self, "WARNING", "No coordinates loaded", QMessageBox.Abort)
            return

        command = f"G0 X{xEnd} Y{yEnd}"
        if GRBLController.debug:
            self.print_lines([command])
        else:
            self.send_lines([command])
        self.sending = False

    def lower_syringe(self):
        """
        Lower the syringe for glue deposition.

        Attributes:
            sending (bool): Temporarily set to True while the command is being sent.

        Emits:
            update_status_signal: Emitted with the message "Lowering Syringe".
        """

        self.sending = True
        self.comm.update_status_signal.emit("Lowering Syringe")
        command = "M4"
        if GRBLController.debug:
            self.print_lines([command])
        else:
            self.send_lines([command])
        self.sending = False

    def raise_syringe(self):
        """
        Raise the syringe for glue deposition.

        Attributes:
            sending (bool): Temporarily set to True while the command is being sent.

        Emits:
            update_status_signal: Emitted with the message "Raising Syringe".
        """
        self.sending = True
        self.comm.update_status_signal.emit("Raising Syringe")
        command = "M3"
        if GRBLController.debug:
            self.print_lines([command])
        else:
            self.send_lines([command])
        self.sending = False

    def dispense_glue(self):
        """
        Dispense glue from the syringe as set on the glue dispenser.

        Attributes:
            sending (bool): Temporarily set to True while the command is being sent.

        Emits:
            update_status_signal: Emitted with the message "Dispensing Glue".

        If the application is in debug mode, the commands are printed instead of sent.
        """
       
        self.sending = True
        self.comm.update_status_signal.emit("Dispensing Glue")
        command1 = "M8"
        command2 = "M9"
        if GRBLController.debug:
            self.print_lines([command1])
            time.sleep(1)
            self.print_lines([command2])
        else:
            self.send_lines([command1])
            time.sleep(1)
            self.send_lines([command2])

    def manual_move(self):

        """
        Perform a manual move of the toolhead along the X or Y axis.

        Attributes:
            sending (bool): Temporarily set to True while the command is being sent.

        Emits:
            update_status_signal: Emitted with a message indicating the direction and
                distance of movement.

        If the application is in debug mode, the command is printed instead of sent.

        TODO: Replace with actual position tracking when available.
        """
        if self.sender() == self.btnYplus or self.sender() == self.btnXplus:
            direction = +1
        else:
            direction = -1

        axis = "Y" if self.sender() in [self.btnYplus, self.btnYminus] else 'X'
        steps = int(self.x_steps_selector.text()) if axis == 'X' else int(self.y_steps_selector.text())
        
        current_x, current_y = self.get_current_position()  # TODO: Replace with actual position tracking

        # If movement results in value less than 0, clip it to a bit over 0
        if (current_x + direction * steps if axis == 'X' else current_y + direction * steps) < 0:
            command = f"G00 {axis}{current_x + 0.001 if axis == 'X' else current_y + 0.001}"
        else:
            command = f"G00 {axis}{direction * steps}"

        self.sending = True
        self.comm.update_status_signal.emit(f"Moving {axis} by {direction * steps} mm")

        if GRBLController.debug:
            print("In debug mode, not sending command.")
            self.print_lines([command])
        else:
            print("Sending command to serial port")
            self.send_lines([command])

        self.update_position(direction * steps if axis == 'X' else 0, direction * steps if axis == "Y" else 0)
        self.sending = False

    def move_home(self):
        """
        Move the toolhead to its home position.

        Emits:
            update_status_signal: Emitted with a message indicating the action.

        If the application is in debug mode, the command is printed instead of sent.

        TODO: Replace with actual position tracking when available.
        """
        self.comm.update_status_signal.emit("Moving to home position")
        self.sending = True
        command = "$H"
        if GRBLController.debug:
            self.print_lines([command])
            self.x_position = 0
            self.y_position = 0  # Reset position to home
        else:
            self.send_lines([command])
            self.x_position = 0
            self.y_position = 0  # Reset position to home
        self.sending = False

        # Enable movement buttons
        self.btnYplus.setEnabled(True)
        self.btnYplus.setStyleSheet(self.enabled_button_style)
        self.btnYminus.setEnabled(True)
        self.btnYminus.setStyleSheet(self.enabled_button_style)
        self.btnXplus.setEnabled(True)
        self.btnXplus.setStyleSheet(self.enabled_button_style)
        self.btnXminus.setEnabled(True)
        self.btnXminus.setStyleSheet(self.enabled_button_style)

        self.GoTo0.setEnabled(True)
        self.GoTo0.setStyleSheet(self.enabled_button_style)

        self.GoToEnd.setEnabled(True)
        self.GoToEnd.setStyleSheet(self.enabled_button_style)
        
        # Enable syringe control
        self.lowerSyringe.setEnabled(True)
        self.lowerSyringe.setStyleSheet(self.enabled_button_style)
        self.raiseSyringe.setEnabled(True)
        self.raiseSyringe.setStyleSheet(self.enabled_button_style)
        self.dispense.setEnabled(True)
        self.dispense.setStyleSheet(self.enabled_button_style)

    def update_feed_rate(self, value):
        """
        Update the feed rate of the GRBL controller to the given value in mm/min.

        Args:
            value (int): The new feed rate in mm/min.

        Emits:
            update_status_signal: Emitted with a message indicating the new feed rate.

        If the application is in debug mode, the command is printed instead of sent.
        """
        self.comm.update_status_signal.emit(f"Setting feed rate to {value} mm/min")
        command = f"F{value}"
        
        if GRBLController.debug:
            self.print_lines([command])
        else:
            self.send_lines([command])
            
    def update_position(self, x_change, y_change):
        """
        Update the current position of the toolhead based on the given changes in the X and Y directions.

        Args:
            x_change (float): The change to apply to the current X position.
            y_change (float): The change to apply to the current Y position.

        Updates:
            x_position: The updated X position of the toolhead.
            y_position: The updated Y position of the toolhead.
        """

        current_x, current_y = self.get_current_position()  # Replace with actual position tracking
        self.x_position = current_x + x_change
        self.y_position = current_y + y_change
        
    def get_current_position(self):
        # Replace with actual logic to get the current position
        # Read value from variable for now
        """
        Get the current position of the toolhead in the X and Y directions.

        Returns:
            tuple: A tuple of two floats representing the current X and Y positions of the toolhead.
        """
        return self.x_position, self.y_position
    
    def scan_ports(self):
        """
        Clear the serial port selector and re-populate it with the available serial ports on the system.

        If no serial ports are found, a message is emitted to update the status label.
        """
        self.port_selector.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.port_selector.addItem(f"{port.device} - {port.description}", port.device)
        if self.port_selector.count() == 0:
            self.comm.update_status_signal.emit("No serial ports found.")

    def toggle_connection(self):
        """
        Toggle the connection state of the GRBL controller.

        If currently connected, disconnect from the serial port.
        If not connected, initialize the serial connection and unlock the machine.

        Emits:
            update_status_signal: Emitted with a message indicating the connection status.
        """

        if self.connected:
            self.disconnect_serial()
        else:
            self.init_serial()
            self.send_lines('$X') # Unlock the machine
            # Switch to manual tab
            self.tabs.setCurrentIndex(1)

    def init_serial(self):
        """
        Initialize the serial communication with the selected port and baud rate.

        The method attempts to open a serial connection to the selected port 
        with the specified baud rate. If successful, it sends initialization 
        commands to the device, updates the connection status, and enables 
        relevant UI controls. If no port is selected, or if there is an error 
        opening the port, an appropriate status message is emitted.

        Raises:
            SerialException: If there is an error opening the serial port.

        Emits:
            update_status_signal: Emitted with a message indicating the connection 
            status or any errors encountered.
        """

        port = self.port_selector.currentData()
        baud = int(self.baud_selector.currentText())
        
        if GRBLController.debug:
            self.load_button.setEnabled(True)
        elif port:
            try:
                self.serial_port = serial.Serial(port, baud, timeout=1)
                time.sleep(2)
                self.serial_port.write(b"\r\n\r\n")
                time.sleep(2)
                self.serial_port.flushInput()
                self.connected = True
                self.connect_button.setText("Disconnect")
                self.comm.update_status_signal.emit(f"Connected to {port} at {baud} baud.")
                self.load_button.setEnabled(True)
               
                # Enable home control
                self.btnHome.setEnabled(True)
                self.btnHome.setStyleSheet(self.enabled_button_style)

            except serial.SerialException as e:
                self.comm.update_status_signal.emit(f"Serial error: {e}")
        else:
            self.comm.update_status_signal.emit("No port selected.")

    def disconnect_serial(self):
        """
        Disconnect the serial port and update UI elements.

        This method checks if the serial port is open and closes it if so. It then updates the 
        connection status to reflect that the device is disconnected and disables various UI 
        controls related to serial communication and tool operation.

        Emits:
            update_status_signal: Emitted with a message indicating the disconnection status.
        """

        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        self.connected = False
        self.connect_button.setText("Connect")
        self.load_button.setEnabled(False)
        self.start_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.first_block_selector.setEnabled(False)
        self.last_block_selector.setEnabled(False)
        self.file_label.setText("File: None")
        self.btnHome.setEnabled(False)
        self.btnYminus.setEnabled(False)
        self.btnYplus.setEnabled(False)
        self.btnXminus.setEnabled(False)
        self.btnXplus.setEnabled(False)

        # Disable syringe control
        self.lowerSyringe.setEnabled(False)
        self.raiseSyringe.setEnabled(False)
        self.dispense.setEnabled(False)
        self.GoTo0.setEnabled(False)
        self.GoToEnd.setEnabled(False)
        
        self.comm.update_status_signal.emit("Disconnected from serial port.")

    def load_file(self):
        """
        Load a G-code file and parse its contents.

        Opens a file dialog to select a G-code file to load. If a file is selected, 
        it is parsed and the toolpath is plotted. The Start button is enabled if the 
        device is connected.

        Emits:
            update_status_signal: Emitted with a message indicating the status of the file load operation.
        """
        file_path, _ = QFileDialog.getOpenFileName(self, "Open G-code File", "", "G-code Files (*.gcode)")
        if file_path:
            self.coordinates = [(0, 0)]  # Reset coordinates
            self.glued_coordinates = [(0, 0)]
            self.parse_gcode(file_path)
            self.comm.update_status_signal.emit("G-code file loaded and parsed.")
            if hasattr(self, 'ax'): # Clear plot if a file was previously loaded
                self.ax.cla()
            self.plot_toolpath()  # Plot the original toolpath
            if self.connected:
                self.start_button.setEnabled(True)  # Enable Start button after file load
                self.first_block_selector.setEnabled(True)
                self.last_block_selector.setEnabled(True)
                self.file_label.setStyleSheet("""
                    font-size: 18px;
                    font-weight: bold;
                    padding: 10px;
                    border: 2px solid #2e3a47;
                    border-radius: 5px;
                """)
                self.file_label.setText(f"File: {file_path}")

    def parse_gcode(self, file_path):
        """
        Parse a G-code file into a toolpath and extract the program initialization block and all
        the glue deposition blocks.

        The first and last block selectors are updated with the range of blocks in the toolpath.

        :param file_path: Path to the G-code file to parse
        :type file_path: str
        :raises FileNotFoundError: If the specified file does not exist
        """
        self.movement_type = []
        self.toolpath = []  # List of {'x': ..., 'y': ..., 'glue_commands': [...]}
        self.program_initialization = []  # Stores the init block

        current_x, current_y = 0.0, 0.0
        is_relative = False
        in_init_block = False
        in_glue_block = False
        movement_type = '0'
        current_glue_commands = []

        command_pattern = re.compile(r'G(\d+)(?:X([-.\d]+))?(?:Y([-.\d]+))?')

        with open(file_path, 'r') as file:
            for line in file:
                line = line.strip()

                if '; Program initialization' in line:
                    in_init_block = True
                    self.program_initialization = [line]
                    continue
                elif '; End of program initialization' in line:
                    in_init_block = False
                    self.program_initialization.append(line)
                    continue

                if in_init_block:
                    self.program_initialization.append(line)
                    if 'G90' in line:
                        is_relative = False
                    elif 'G91' in line:
                        is_relative = True
                    if 'G00' or 'G01' in line:
                        x, y, movement_type = self.match_pattern(line, command_pattern)

                        if is_relative:
                            current_x += x
                            current_y += y
                        else:
                            current_x = x
                            current_y = y

                        self.coordinates.append((current_x, current_y))
                        self.movement_type.append(movement_type)
                    
                    if '$130' in line:
                        self.maximumTravel = line[5:8]
                        
                if "; ------- Glue deposition -------" in line:
                    in_glue_block = True
                    current_glue_commands = [line]
                    continue
                elif "; ------- End of glue deposition -------" in line:
                    in_glue_block = False
                    current_glue_commands.append(line)
                    if self.coordinates:
                        x, y = self.coordinates[-1]
                        self.toolpath.append({'x': x, 'y': y, 'glue_commands': current_glue_commands.copy(), 'movement_type' : self.movement_type[-1]})
                    current_glue_commands = []
                    continue

                if in_glue_block:
                    current_glue_commands.append(line)

                if not in_init_block:
                    
                    x, y, movement_type = self.match_pattern(line, command_pattern)
                    
                    if 'G90' in line:
                        is_relative = False
                    elif 'G91' in line:
                        is_relative = True
                        
                    if is_relative:
                        current_x += x
                        current_y += y
                    else:
                        current_x = x
                        current_y = y

                    self.coordinates.append((current_x, current_y))
                    self.movement_type.append(movement_type)

            # Update the first and last block selectors
            self.first_block_selector.clear()
            self.first_block_selector.addItems([str(i) for i in range(len(self.toolpath))])
            self.first_block_selector.setCurrentIndex(0)

            self.last_block_selector.clear()
            self.last_block_selector.addItems([str(i) for i in range(len(self.toolpath))])
            self.last_block_selector.setCurrentIndex(len(self.toolpath) - 1)
                
    def match_pattern(self, line, pattern):
        """
        Extract X and Y coordinates and movement type from a line of G-code.

        :param line: A line of G-code
        :param pattern: A compiled regular expression pattern
        :return: A tuple of (x, y, movement_type)
        """
        x, y, movement_type = 0.0, 0.0, '0'
        
        matches = pattern.finditer(line.upper())
        for match in matches:
            x = float(match.group(2)) if match.group(2) else 0.0
            y = float(match.group(3)) if match.group(3) else 0.0

            if match.group(1) == '00' or match.group(1) == '01':
                movement_type = match.group(1)
    
        return x, y, movement_type

    def plot_toolpath(self, pointcolor='lightgray'):
        """
        Plot the toolpath on the canvas.

        :param pointcolor: Color of the points to be plotted
        :type pointcolor: str

        This function creates a plot of the toolpath if it doesn't already exist.

        Additionally, lines are added to the plot for each unique x and y value. The
        line is drawn from the x or y value to the edge of the plot and labeled with
        the column or row number.

        Finally, the function checks if the last line is over the maximum allowed
        travel and displays a warning if it is.
        """

        # Ensure the background plot is created only once
        if not hasattr(self, 'ax'):
            self.ax = self.figure.add_subplot(111)

        if self.coordinates:
            x_vals, y_vals = zip(*self.coordinates)
            self.ax.plot(x_vals, y_vals, linestyle='--', color=pointcolor, label='Toolpath')
            self.ax.scatter(x_vals, y_vals, color=pointcolor, s=50)
        
        self.ax.set_xlim(-50, max(x_vals) + 50)
        self.ax.set_ylim(-50, max(y_vals) + 50)
        
        self.ax.set_xlabel("X Axis")
        self.ax.set_ylabel("Y Axis")

        # Find all unique x and y values
        unique_x = sorted(set(x_vals))
        unique_y = sorted(set(y_vals))

        col_num, row_num = 0, -1
        # Add a line for each unique x and y value
        for x in unique_x:
            self.ax.plot([x, x], [max(y_vals), max(y_vals) + 50], color='lightgray', linewidth=0.5)
            # Add text with column number
            self.ax.annotate(f"{col_num}", (x, max(y_vals) + 50), xytext=(0, 10), textcoords='offset points', ha='center', va='bottom', arrowprops=dict(arrowstyle='->', color='lightgray'))
            col_num += 1
        
        # Add a line for each unique y value
        for y in unique_y:
            self.ax.plot([max(x_vals), max(x_vals) + 50], [y, y], color='lightgray', linewidth=0.5)
            # Add text with row number
            self.ax.annotate(f"{row_num}", (max(x_vals) + 50, y), xytext=(-10, 0), textcoords='offset points', ha='right', va='center', arrowprops=dict(arrowstyle='->', color='lightgray'))
            row_num += 1

        self.ax.grid(True)
        self.ax.set_aspect('equal', adjustable='box')
        
        # Check if the last line is over the maximum allowed travel
        if max(x_vals) >= float(self.maximumTravel):
            QMessageBox.warning(self, "WARNING", "The last line is over the maximum allowed travel", QMessageBox.Ok)
        self.canvas.draw()

    def plot_glued_toolpath(self):
        """
        Plot the glued toolpath in red (foreground) on the existing axes.
        
        It uses the same x and y limits as the original toolpath, and adds a label
        to the legend.
        
        :param self: Instance of the class
        """
        # No need to clear the axes, we just add to the existing one
        if self.glued_coordinates:
            x_vals, y_vals = zip(*self.glued_coordinates)

            # Plot the glued toolpath in red (foreground)
            self.ax.plot(x_vals, y_vals, linestyle='-', color='red', label='Glued Toolpath')  
            self.ax.scatter(x_vals, y_vals, color='red', s=50)
            # Compute point index
            point_idx = len(self.glued_coordinates) - 2 + int(self.first_block_selector.currentText())
            # Remove last annotations
            self.ax.texts[-1].remove()
            # Add last point index to glued length near the point
            self.ax.annotate(f"{point_idx}", (x_vals[-1], y_vals[-1]), xytext=(0, 10), textcoords='offset points', ha='center', va='bottom', arrowprops=dict(arrowstyle='->', color='red'))

            self.ax.set_xlabel("X Axis")
            self.ax.set_ylabel("Y Axis")
            self.ax.grid(True)
            self.ax.set_aspect('equal', adjustable='box')

        self.canvas.draw()

    def toggle_pause(self):
        """
        Toggle the pause state of the G-code sender.

        If currently paused, resume sending G-code.
        If currently sending, pause the G-code sender.

        :param self: Instance of the class
        :return: None
        """
        COLOR_PAUSED = "#FFEE8C"  # Light yellow

        if self.paused:
            self.paused = False
            status_message = "Resumed sending G-code."
            self.pause_button.setStyleSheet(self.small_enabled_button_style) 
        else:
            self.paused = True
            status_message = "Paused sending G-code."
            # Get the current style sheet
            current_style = self.pause_button.styleSheet().split("\n")
            # Reassemble the style sheet
            new_style = "\n".join(current_style[:-2] + [f"background-color: {COLOR_PAUSED};}}"])

            self.pause_button.setStyleSheet(new_style)

        # Update status
        self.comm.update_status_signal.emit(status_message)

    def stop_sending(self):
        """
        Stop the sending of G-code commands.

        This method sets the sending and paused flags to False and updates the UI elements 
        to reflect that the G-code sending has been stopped. It enables the start button 
        and disables the pause and stop buttons. Additionally, it emits a status signal 
        indicating that the G-code sending has been stopped.
        """

        self.sending = False
        self.paused = False
        self.start_button.setEnabled(True)
        self.comm.update_status_signal.emit("G-code sending stopped.")
        self.paused = False
        self.pause_button.setStyleSheet(self.small_enabled_button_style)
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.first_block_selector.setEnabled(True)
        self.last_block_selector.setEnabled(True)

    def start_sending(self):
        """
        Start sending G-code commands.

        This method sets the sending flag to True and paused flag to False, updates the UI elements 
        to reflect that the G-code sending has started, and starts a new thread to send the G-code commands.
        Additionally, it emits a status signal indicating that the G-code sending has started.

        If not connected to the device, a status message is emitted indicating the disconnection.
        """
        if not self.connected:
            self.comm.update_status_signal.emit("Not connected to the device.")
            return

        self.sending = True
        self.paused = False
        self.start_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.stop_button.setEnabled(True)

        # Clean up glued coordinates
        self.glued_coordinates = [(0, 0)]
        # Clean up glued toolpath
        if hasattr(self, 'ax'):
            self.ax.cla()
            self.plot_toolpath()

        self.thread = threading.Thread(target=self.send_gcode)
        self.thread.start()

    def send_gcode(self):
        """
        Send G-code to the connected device.

        This function transmits G-code commands to the device, starting with the
        program initialization block and followed by the movement and glue deposition
        commands. It manages the sending state, updates the UI elements, and handles
        any exceptions that occur during transmission. The function supports pausing
        and resuming the transmission and emits signals for status updates.

        Emits:
            update_status_signal: Emitted with messages indicating the transmission status.
            first_block_signal: Emitted when the first block in the toolpath is reached.

        Raises:
            SerialException: If a serial error occurs during transmission.
            Exception: For any other errors encountered.

        """

        try:
            # Send the program initialization block
            self.comm.update_status_signal.emit("Starting G-code transmission")

            if GRBLController.debug:
                self.print_lines(self.program_initialization)
                self.print_lines(["G90"])  # Ensure absolute positioning (coordinates are converted during parsing to absolute)
            else:
                self.send_lines(self.program_initialization)
                self.send_lines(["G90"])

            first_block = int(self.first_block_selector.currentText())
            last_block = int(self.last_block_selector.currentText())

            # Disable the first and last block selectors while sending
            self.first_block_selector.setEnabled(False)
            self.last_block_selector.setEnabled(False)

            # Send each command block in the toolpath
            for block in self.toolpath[first_block:last_block + 1]:

                if not self.sending:
                    break

                while self.paused:
                    time.sleep(0.1)
                # Send movement command
                if GRBLController.debug:
                    self.print_lines([f"G{block['movement_type']} X{block['x']} Y{block['y']}"])
                    if block == self.toolpath[first_block]:
                        print("First block reached, emitting signal")  # Debug print
                        self.comm.update_status_signal.emit("First point reached")
                        self.comm.first_block_signal.emit()  # Emit the signal
                        time.sleep(5)
                else:
                    self.send_lines([f"G{block['movement_type']} X{block['x']} Y{block['y']}"])
                    if block == self.toolpath[first_block]:
                        self.comm.update_status_signal.emit("Moving to first point")
                        self.comm.first_block_signal.emit()  # Emit the signal
  

                # Send glue deposition commands
                if GRBLController.debug:
                    self.print_lines(block['glue_commands'])
                else:
                    self.send_lines(block['glue_commands'])

                self.glued_coordinates.append((block['x'], block['y']))
                self.plot_glued_toolpath()

            self.comm.update_status_signal.emit("Finished sending G-code.")
        except serial.SerialException as e:
            self.comm.update_status_signal.emit(f"Serial error: {e}")
            self.sending = False
        except Exception as e:
            self.comm.update_status_signal.emit(f"Error: {e}")
            self.sending = False
        finally:
            self.comm.update_status_signal.emit("Transmission stopped")
            self.start_button.setEnabled(True)
            self.pause_button.setEnabled(False)
            self.stop_button.setEnabled(False)

    def send_lines(self, lines):
        """
        Send a list of lines to the serial port, checking for pause and stop conditions
        and reporting the lines sent and any errors encountered.

        :param lines: List of lines to send
        :type lines: list

        :raises SerialException: If there is an error writing to the serial port
        :raises Exception: If any other error occurs
        """
        for line in lines:
            if not self.sending:
                break
            while self.paused:
                time.sleep(0.1)

            try:
                self.serial_port.write((line + '\n').encode())
                self.comm.update_status_signal.emit(f"Sent: {line}")
                while True:
                    response = self.serial_port.readline().decode().strip()
                    if response == 'ok':
                        break
                    time.sleep(0.1)

            except serial.SerialException as e:
                self.comm.update_status_signal.emit(f"Serial error while sending: {e}")
                self.sending = False
                break
            except Exception as e:
                self.comm.update_status_signal.emit(f"Error while sending: {e}")
                self.sending = False
                break

    def print_lines(self, lines):
        """
        Simulate sending a list of lines to the serial port, printing the lines instead.

        This is used in debug mode to simulate sending G-code to the device.

        :param lines: List of lines to "send"
        :type lines: list

        :raises Exception: If any error occurs
        """
        for line in lines:
            if not self.sending:
                break
            while self.paused:
                time.sleep(0.1)
            print((line))
            self.comm.update_status_signal.emit(f"Sent: {line}")
            time.sleep(0.25)

    def update_status(self, message):
        """
        Update the status label with the given message.

        :param message: Status message to display
        :type message: str
        """
        self.status_label.setText(f"Status: {message}")

    def first_point_reached(self):
        """
        Pause the transmission and show a message box when the first point in the toolpath is reached,
        asking the user to confirm whether to continue with the transmission or not.

        :raises Exception: If any error occurs
        """
        self.toggle_pause()  # Pause the transmission
        self.show_message_box_signal.emit()  # Emit the signal to show the message box
    
    def show_message_box(self):
        """
        Shows a message box when the first point in the toolpath is reached.

        :raises Exception: If any error occurs
        """

        reply = QMessageBox.question(
            self, "Message", "Moving to first point. Continue?", QMessageBox.Yes, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.toggle_pause()  # Resume the transmission
        else:
            self.stop_sending()  # Stop the transmission

    def closeEvent(self, event):
        """
        Override of QWidget.closeEvent to ask for confirmation before closing the application.

        If the user confirms, the event is accepted and the application is closed. If the user cancels, the event is ignored.

        :param event: The close event
        :type event: QCloseEvent
        """
        reply = QMessageBox.question(
            self, "Message", "Are you sure you want to quit?", QMessageBox.Yes, QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            if self.serial_port and self.serial_port.is_open:
                self.serial_port.close()
            event.accept()
        else:
            event.ignore()


if __name__ == "__main__":

    # If launched with -d or --debug flag, enable debug mode
    if len(sys.argv) > 1 and sys.argv[1] in ['-d', '--debug']:
        GRBLController.debug = True
    else:
        GRBLController.debug = False

    app = QApplication(sys.argv)
    window = GRBLController()
    window.showMaximized()
    window.setWindowIcon(QIcon('icon.ico'))
    sys.exit(app.exec_())
