#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import ctypes
import sys
import sqlite3
import os
import threading
import subprocess
import platform
import time
from queue import Queue, Empty
from PyQt5.QtWidgets import (QApplication, QWidget, QGridLayout, QVBoxLayout,
                             QPushButton, QLabel, QFrame, QMenu)
from PyQt5.QtCore import Qt, QSize, QTimer
from PyQt5.QtGui import QPixmap, QIcon, QPainter, QResizeEvent, QFont, QColor, QPen,QFontDatabase
current_os = platform.system()
print(f"检测到操作系统: {current_os}")

if current_os == "Linux":
    try:
        from evdev import ecodes, InputDevice, UInput, KeyEvent
        LINUX_EVDEV_AVAILABLE = True
        print("Linux evdev 模块加载成功")
    except ImportError:
        print("警告: Linux 系统但 evdev 模块未安装")
        LINUX_EVDEV_AVAILABLE = False
elif current_os == "Windows":
    try:
        import pynput
        from pynput import keyboard
        WINDOWS_PYNPUT_AVAILABLE = True
        print("Windows pynput 模块加载成功")
    except ImportError:
        print("警告: Windows 系统但 pynput 模块未安装")
        print("请运行: pip install pynput")
        WINDOWS_PYNPUT_AVAILABLE = False
else:
    print(f"不支持的操作系统: {current_os}")
    LINUX_EVDEV_AVAILABLE = False
    WINDOWS_PYNPUT_AVAILABLE = False

class CustomGridFrame(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def show_context_menu(self, pos):
        # Trigger the parent's right-click handler
        self.parent().on_grid_right_click(pos)

class Q9InputMethodUI(QWidget):
    def __init__(self, device_path="/dev/input/by-path/pci-0000:67:00.4-usb-0:1:1.0-event-kbd"):
        super().__init__()

        # 检测操作系统
        self.current_os = platform.system()
        print(f"当前操作系统: {self.current_os}")

        # 狀態變量
        self.current_input = ""
        self.current_page = "input"
        self.db_path = "files/dataset.db"
        self.db_connection = None
        self.app = QApplication.instance()

        # 選字模式
        self.select_words = []
        self.curr_page = 0
        self.total_page = 0
        self.select_mode = False

        # 關聯詞
        self.last_word = ""
        self.current_relates = []
        self.showing_relates = False        
        self.sc_output = False

        # 添加隐藏状态变量
        self.is_hidden = False

        # Keyboard hook setup
        self.setup_keyboard_hook_variables(device_path)        

        # 初始化 DB
        self.init_database()

        # 載入圖片
        self.images = {}
        for type_val in range(11):
            for i in range(1, 10):
                index = type_val * 10 + i
                img_path = f"files/img/{type_val}_{i}.png"
                if os.path.exists(img_path):
                    self.images[index] = QPixmap(img_path)
                    print(f"載入圖像: {img_path}")
                else:
                    print(f"圖像未找到: {img_path}")

        # 半透明圖像
        for j in range(1, 10):
            index = 110 + j
            if j in self.images:
                original = self.images[j]
                transparent_pixmap = QPixmap(original.size())
                transparent_pixmap.fill(Qt.transparent)
                painter = QPainter(transparent_pixmap)
                painter.setOpacity(0.5)
                painter.drawPixmap(0, 0, original)
                painter.end()
                self.images[index] = transparent_pixmap

        self.init_ui()
        self.start_keyboard_hook()

    def set_best_chinese_font(self):
        fontTargets = [
            "Noto Sans HK Medium", "Noto Sans HK", "Noto Sans HK Black", 
            "Noto Sans HK Light", "Noto Sans HK Thin", "Noto Sans TC", 
            "Noto Sans TC Black", "Noto Sans TC Light", "Noto Sans TC Medium",
            "Noto Sans TC Regular", "Noto Sans TC Thin", 
            "Noto Serif CJK TC Black", "Noto Serif CJK TC Medium", 
            "Noto Sans CJK JP", "Noto Sans CJK TC Black", 
            "Noto Sans CJK TC Bold", "Noto Sans CJK TC Medium", 
            "Noto Sans CJK TC Regular", "Noto Sans CJK DemiLight", 
            "Microsoft JhengHei"
        ]
        
        available_fonts = QFontDatabase().families()
        for target in fontTargets:
            if target in available_fonts:
                app_font = QFont(target)
                app_font.setPointSize(12)  # 你可以調整字號
                QApplication.setFont(app_font)
                print(f"已套用字體: {target}")
                return target
        print("未找到匹配的中文字體，使用系統預設字體")
        return None
    def setup_keyboard_hook_variables(self, device_path):
        """根据操作系统设置键盘钩子变量"""
        if self.current_os == "Linux" and LINUX_EVDEV_AVAILABLE:
            self.setup_linux_keyboard_hook(device_path)
        elif self.current_os == "Windows" and WINDOWS_PYNPUT_AVAILABLE:
            self.setup_windows_keyboard_hook_improved()
        else:
            self.setup_fallback_keyboard_hook()    

    def cleanup_windows_hook(self):
        """清理Windows钩子"""
        if hasattr(self, 'use_win32_hook') and self.use_win32_hook and hasattr(self, 'hook_id') and self.hook_id:
            try:
                import ctypes
                from ctypes import windll
                result = windll.user32.UnhookWindowsHookEx(self.hook_id)
                if result:
                    print("Windows API 钩子已清理")
                else:
                    print("Windows API 钩子清理失败")
                self.hook_id = None
            except Exception as e:
                print(f"清理Windows API钩子失败: {e}")
        
        # 清理pynput listener
        if hasattr(self, 'pynput_listener') and self.pynput_listener:
            try:
                self.pynput_listener.stop()
                print("Pynput listener已停止")
            except Exception as e:
                print(f"停止pynput listener失败: {e}")
    def setup_linux_keyboard_hook(self, device_path):
        """设置Linux evdev键盘钩子"""
        self.device_path = device_path
        self.running = True
        self.original_device = None
        self.virtual_keyboard = None
        self.key_queue = Queue()
        self.key_map = {
            ecodes.KEY_KP0: "0",
            ecodes.KEY_KP1: "1",
            ecodes.KEY_KP2: "2",
            ecodes.KEY_KP3: "3",
            ecodes.KEY_KP4: "4",
            ecodes.KEY_KP5: "5",
            ecodes.KEY_KP6: "6",
            ecodes.KEY_KP7: "7",
            ecodes.KEY_KP8: "8",
            ecodes.KEY_KP9: "9",
            ecodes.KEY_KPDOT: ".",
            ecodes.KEY_F10: "F10",
        }
        self.intercepted_codes = set(self.key_map.keys())
        print("Linux evdev 键盘钩子设置完成")

    def setup_windows_keyboard_hook_improved(self):
        """修正的 Windows API 鍵盤鉤子設置 (帶詳細日誌)"""
        self.running = True
        self.key_queue = Queue()

        try:
            import ctypes
            from ctypes import wintypes, windll, POINTER, c_int

            self.use_win32_hook = True
            self.hook_id = None

            # 定義 HOOKPROC 類型
            self.HOOKPROC = ctypes.WINFUNCTYPE(
                c_int,           # 返回值
                c_int,           # nCode
                wintypes.WPARAM, # wParam
                wintypes.LPARAM  # lParam
            )

            print(f"[DEBUG] HOOKPROC 類型: {self.HOOKPROC}, id={id(self.HOOKPROC)}")

            # 常量
            self.WH_KEYBOARD_LL = 13
            self.WM_KEYDOWN = 0x0100
            self.WM_SYSKEYDOWN = 0x0104

            # KBDLLHOOKSTRUCT 結構
            class KBDLLHOOKSTRUCT(ctypes.Structure):
                _fields_ = [
                    ("vkCode", wintypes.DWORD),
                    ("scanCode", wintypes.DWORD),
                    ("flags", wintypes.DWORD),
                    ("time", wintypes.DWORD),
                    ("dwExtraInfo", POINTER(wintypes.ULONG))
                ]
            self.KBDLLHOOKSTRUCT = KBDLLHOOKSTRUCT

            print("Windows API 鍵盤鉤子結構設置完成")

        except Exception as e:
            print(f"Windows API 鉤子設置失敗（回退到簡化鉤子）: {e}")
            self.use_win32_hook = False
            self.setup_windows_keyboard_hook_simple()

    def setup_fallback_keyboard_hook(self):
        """设置回退模式（仅UI，无键盘钩子）"""
        self.running = False
        self.key_queue = Queue()
        print("警告: 键盘钩子不可用，仅运行UI模式")

    def position_window_right_center(self):
        """将窗口定位到屏幕右侧中央"""
        try:
            # 获取屏幕几何信息
            desktop = QDesktopWidget()
            screen_rect = desktop.screenGeometry()
            
            # 计算窗口位置 - 右侧中央
            window_width = self.width()
            window_height = self.height()
            
            # 右侧位置（留一些边距）
            x = screen_rect.width() - window_width - 20  # 右侧20px边距
            # 垂直居中
            y = (screen_rect.height() - window_height) // 2
            
            # 移动窗口
            self.move(x, y)
            print(f"窗口定位到: ({x}, {y})")
            
        except Exception as e:
            print(f"窗口定位失败: {e}")
    def start_keyboard_hook(self):
        """根据操作系统启动对应的键盘钩子"""
        if self.current_os == "Linux" and LINUX_EVDEV_AVAILABLE:
            self.start_linux_keyboard_hook()
        elif self.current_os == "Windows" and WINDOWS_PYNPUT_AVAILABLE:
            self.start_windows_keyboard_hook_improved()
        else:
            print("键盘钩子不可用，程序仍可通过鼠标点击使用")
    
    def start_linux_keyboard_hook(self):
        """启动Linux evdev键盘钩子"""
        print(f"寻找键盘设备: {self.device_path}...", file=sys.stderr, flush=True)
        try:
            self.original_device = InputDevice(self.device_path)
            print(f"成功连接到原始键盘: {self.original_device.name}", file=sys.stderr, flush=True)
            self.virtual_keyboard = UInput.from_device(self.original_device, name='Virtual Keyboard')
            print("成功创建虚拟键盘设备。", file=sys.stderr, flush=True)
            self.original_device.grab()
            print("已独占原始键盘设备。", file=sys.stderr, flush=True)
            threading.Thread(target=self.linux_event_loop, daemon=True).start()
            # 启动按键队列处理定时器
            self.key_timer = QTimer(self)
            self.key_timer.timeout.connect(self.process_key_queue)
            self.key_timer.start(100)
        except Exception as e:
            print(f"Linux 键盘钩子启动失败: {e}", file=sys.stderr, flush=True)

    def start_windows_keyboard_hook_improved(self):
        """啟動 Windows API 鍵盤鉤子 (使用 SetWindowsHookExA + hMod=0 避免 126 錯誤)"""
        if not self.use_win32_hook:
            return self.start_windows_keyboard_hook_simple()

        try:
            import ctypes
            from ctypes import wintypes, windll, POINTER, cast

            def keyboard_hook_proc(nCode, wParam, lParam):
                try:
                    if nCode >= 0 and wParam in (self.WM_KEYDOWN, self.WM_SYSKEYDOWN):
                        kbd_struct = cast(lParam, POINTER(self.KBDLLHOOKSTRUCT)).contents
                        vk_code = kbd_struct.vkCode
                        print(f"Win32 Hook: VK Code = {vk_code}")

                        if vk_code == 0x79:  # F10
                            self.key_queue.put("F10")
                            return 1

                        numpad_vk_map = {
                            0x60: "0", 0x61: "1", 0x62: "2", 0x63: "3",
                            0x64: "4", 0x65: "5", 0x66: "6", 0x67: "7",
                            0x68: "8", 0x69: "9", 0x6E: "."
                        }
                        if vk_code in numpad_vk_map and not self.is_hidden:
                            self.key_queue.put(numpad_vk_map[vk_code])
                            return 1

                    return windll.user32.CallNextHookEx(self.hook_id, nCode, wParam, lParam)

                except Exception as e:
                    print(f"鉤子回調錯誤: {e}")
                    return windll.user32.CallNextHookEx(self.hook_id, nCode, wParam, lParam)

            # ✅ 實例化回調並保留引用
            self._keyboard_hook_proc = self.HOOKPROC(keyboard_hook_proc)

            user32 = windll.user32

            # ✅ 顯式設置參數和返回類型
            user32.SetWindowsHookExA.argtypes = [
                ctypes.c_int,            # idHook
                self.HOOKPROC,           # lpfn (回調類型)
                wintypes.HINSTANCE,      # hMod
                wintypes.DWORD           # dwThreadId
            ]
            user32.SetWindowsHookExA.restype = wintypes.HHOOK

            # ✅ 安裝鉤子，hMod=0 避免 ERROR_MOD_NOT_FOUND (126)
            self.hook_id = user32.SetWindowsHookExA(
                self.WH_KEYBOARD_LL,
                self._keyboard_hook_proc,
                0,   # 🔹 不傳模組句柄，避免 126 錯誤
                0
            )

            if not self.hook_id:
                err = windll.kernel32.GetLastError()
                print(f"Windows API 鉤子安裝失敗, 錯誤代碼: {err}")
                self.use_win32_hook = False
                return self.start_windows_keyboard_hook_simple()

            print(f"Windows API 鍵盤鉤子安裝成功 (Hook ID: {self.hook_id})")

            self.key_timer = QTimer(self)
            self.key_timer.timeout.connect(self.process_key_queue)
            self.key_timer.start(10)
            return True

        except Exception as e:
            print(f"Windows API 鉤子啟動失敗: {e}")
            self.use_win32_hook = False
            return self.start_windows_keyboard_hook_simple()



    def on_windows_key_press(self, key):
        """Windows 按键按下事件处理 - 简化版 - 永远不返回False"""
        try:
            print(f"Windows 按键检测: {key}")
            
            # 处理F10键
            if key == keyboard.Key.f10:
                print("F10 detected")
                self.key_queue.put("F10")
                return  # 不返回False，让系统正常处理F10
            
            # 处理数字键盘 - 使用VK码检测
            if hasattr(key, 'vk') and key.vk is not None:
                if key.vk in self.numpad_vk_map:
                    mapped_key = self.numpad_vk_map[key.vk]
                    print(f"Numpad key detected: VK={key.vk} -> {mapped_key}")
                    
                    if not self.is_hidden:  # 只有界面显示时才处理
                        self.key_queue.put(mapped_key)
                        print(f"Key added to queue: {mapped_key}")
                        # 不返回False，让按键正常传递
                        # 用户需要手动删除在其他应用中输入的数字
                    else:
                        print("Interface hidden, key passed through normally")
                        
        except Exception as e:
            print(f"Windows 按键处理错误: {e}")

    def on_windows_key_release(self, key):
        """Windows 按键释放事件处理 - 简化版"""
        # 不处理释放事件，直接返回
        pass

    def toggle_visibility(self):
        """切换窗口的隐藏/显示状态"""
        if self.is_hidden:
            self.show()
            # 重新定位到右侧中央
            self.position_window_right_center()
            self.is_hidden = False
            print("输入法界面已显示")
        else:
            self.hide()
            self.is_hidden = True
            print("输入法界面已隐藏")
    def linux_event_loop(self):
        """Linux evdev 事件循环"""
        while self.running:
            try:
                for event in self.original_device.read_loop():
                    if event.type != ecodes.EV_KEY:
                        self.virtual_keyboard.write(event.type, event.code, event.value)
                        self.virtual_keyboard.syn()
                        continue
                    
                    # 处理F10键 - 始终拦截
                    if event.code == ecodes.KEY_F10 and event.value == KeyEvent.key_down:
                        self.key_queue.put("F10")
                        continue
                    
                    # 如果界面隐藏，数字键盘按键正常传递
                    if self.is_hidden and event.code in self.intercepted_codes and event.code != ecodes.KEY_F10:
                        self.virtual_keyboard.write(event.type, event.code, event.value)
                        self.virtual_keyboard.syn()
                        continue
                    
                    # 界面显示时，拦截数字键盘按键用于输入法
                    if event.code in self.intercepted_codes and event.value == KeyEvent.key_down:
                        key = self.key_map.get(event.code)
                        if key and key != "F10":
                            self.key_queue.put(key)
                            continue
                    
                    # 其他按键正常传递
                    self.virtual_keyboard.write(event.type, event.code, event.value)
                    self.virtual_keyboard.syn()
                    
            except Exception as e:
                print(f"Linux 事件循环错误: {e}", file=sys.stderr, flush=True)
                break
    
    def process_key_queue(self):
        """处理按键队列 - 改进版"""
        processed_count = 0
        max_process = 10  # 每次最多处理10个按键，避免阻塞UI
        
        try:
            while processed_count < max_process:
                key = self.key_queue.get_nowait()
                print(f"Processing key from queue: {key}")
                self.handle_key_input(key)
                processed_count += 1
        except Empty:
            pass  # 队列为空，正常情况
        except Exception as e:
            print(f"处理按键队列时出错: {e}")

    def closeEvent(self, event):
        """修正的closeEvent，包含完整的清理逻辑"""
        self.running = False
        
        # 清理Windows钩子
        if self.current_os == "Windows":
            self.cleanup_windows_hook()
        
        # Linux 清理
        if self.current_os == "Linux" and hasattr(self, 'original_device') and self.original_device:
            try:
                self.original_device.ungrab()
            except Exception:
                pass
            try:
                self.original_device.close()
            except Exception:
                pass
        if hasattr(self, 'virtual_keyboard') and self.virtual_keyboard:
            try:
                self.virtual_keyboard.close()
            except Exception:
                pass
            
        # 数据库清理
        if self.db_connection:
            try:
                self.db_connection.close()
            except Exception:
                pass
            
        event.accept()

    def init_ui(self):
        self.setWindowTitle("Q9 中文輸入法")
        #self.setFixedSize(300, 450)
        self.initial_width = 230
        self.initial_height = 320
        self.resize(self.initial_width, self.initial_height)
        self.aspect_ratio = self.initial_width / self.initial_height
        self.set_best_chinese_font()
        
        # 移除標題欄
        # self.setWindowFlags(Qt.FramelessWindowHint)
        #self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.WindowCloseButtonHint)

        # 紧凑的白底主题样式
        self.setStyleSheet("""
            QWidget {
                background-color: #ffffff;
                color: #000000;
            }
            QPushButton {
                background-color: #f0f0f0;
                border: 1px solid #cccccc;  /* 边框从2px减少到1px */
                border-radius: 2px;         /* 圆角从5px减少到3px */
                color: #000000;
                font-size: 26px;           /* 字体从30px减少到26px */
                font-weight: bold;
                padding: 2px;              /* padding从5px减少到2px */
                min-height: 80px;          /* 高度从70px减少到55px */
                text-align: center;
            }
            QPushButton#NumberButton {
                background-color: #f8f8f8;
                border: 1px solid #cccccc;
                border-radius: 3px;
                color: #000000;
                font-size: 26px;
                font-weight: bold;
                padding: 2px;
                min-height: 30px;
                text-align: center;           
            }
            QPushButton#relate-preview {
                background-color: #f8f8f8;
                border: 1px solid #cccccc;
                border-radius: 3px;
                color: #333333;
                font-size: 20px;           /* 字体从20px减少到16px */
                text-align: left;
                padding-top: 1px;          /* padding减少 */
                padding-left: 2px;
            }
            QPushButton#function-button {
                background-color: #e0e0e0;
                border: 1px solid #cccccc;
                border-radius: 3px;
                color: #000000;
                min-height: 32px;          /* 高度从40px减少到32px */
                font-size: 16px;           /* 字体从20px减少到16px */
                padding: 3px;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
                border-color: #999999;
            }
            QPushButton:pressed {
                background-color: #d0d0d0;
                border-color: #666666;
            }            
            QLabel {
                color: #000000;
                font-size: 26px;
                text-align: center;
                padding: 1px;
                background-color: transparent;
            }
        """)

        # 紧凑布局 - 减少margins和spacing
        main_layout = QVBoxLayout()
        main_layout.setSpacing(1)      # 从10减少到3
        main_layout.setContentsMargins(1, 1, 1, 1)  # 从10减少到5

        # 网格布局
        self.grid_frame = CustomGridFrame(self)
        self.grid_frame.installEventFilter(self)
        self.grid_layout = QGridLayout(self.grid_frame)
        self.grid_layout.setSpacing(1)  # 从2减少到1，让按钮更贴近
        self.grid_layout.setContentsMargins(0, 0, 0, 0)  # 移除网格的margins
        self.create_grid_buttons()
        main_layout.addWidget(self.grid_frame)

        # 功能按钮布局
        function_layout = QGridLayout()
        function_layout.setSpacing(2)   # 减少功能按钮间距
        function_layout.setContentsMargins(0, 0, 0, 0)
        
        self.function_0_btn = QPushButton("下一頁")
        self.function_0_btn.setObjectName("function-button")
        self.function_0_btn.clicked.connect(lambda: self.handle_key_input(0))
        function_layout.addWidget(self.function_0_btn, 0, 0)
        
        self.function_dot_btn = QPushButton("取消")
        self.function_dot_btn.setObjectName("function-button")
        self.function_dot_btn.clicked.connect(lambda: self.handle_key_input("."))
        function_layout.addWidget(self.function_dot_btn, 0, 1)

        main_layout.addLayout(function_layout)
        self.setLayout(main_layout)
        self.set_button_img(0)       

    def on_grid_right_click(self, pos):
        """Handle right-click on grid_frame"""
        print(f"Right-click detected at position: {pos}")
        # Example: Show a context menu
        menu = QMenu(self)
        if self.sc_output == False:
            menu.addAction("輸出簡體", self.tcsc_output)
        else:menu.addAction("輸出繁體", self.tcsc_output)
        #menu.addAction("Custom Action", lambda: print("Custom action triggered"))
        menu.exec_(self.grid_frame.mapToGlobal(pos))
    def resizeEvent(self, event):
        # 取得新視窗大小
        new_size = event.size()
        new_width = new_size.width()
        new_height = new_size.height()

        # 根據長寬比例調整大小，以寬度為基準
        if new_width / new_height > self.aspect_ratio:
            new_width = int(new_height * self.aspect_ratio)
        else:
            new_height = int(new_width / self.aspect_ratio)

        # 重新設定視窗大小
        self.resize(new_width, new_height)

        # 根據新的寬度來更新樣式
        self.update_style_for_size(new_width)
    def update_style_for_size(self, current_width):
        scale_factor = current_width / self.initial_width
        
        # 紧凑模式的尺寸计算
        button_size = 80 * scale_factor      # 基础尺寸从70减少到55
        func_button_size = 32 * scale_factor # 功能按钮从30减少到25
        button_font_size = int(40 * scale_factor)  # 字体从30减少到26
        relate_font_size = int(15 * scale_factor)  # 字体从20减少到16
        input_display_font_size = 26 * scale_factor

        new_style = f"""
            QWidget {{
                background-color: #ffffff;
                color: #000000;
            }}
            QPushButton {{
                background-color: #f0f0f0;
                border: 1px solid #cccccc;
                border-radius: 3px;
                color: #000000;
                font-size: {button_font_size}px;
                font-weight: bold;
                padding: 2px;
                min-height: {button_size}px;
                min-width: {button_size}px;
                max-height: {button_size}px;
                max-width: {button_size}px;
            }}
            QPushButton#NumberButton {{
                background-color: #f8f8f8;
                border: 1px solid #cccccc;
                border-radius: 1px;
                color: #000000;
                font-size: {button_font_size}px;
                font-weight: bold;
                padding: 2px;
                min-height: {button_size}px;
                min-width: {button_size}px;
                max-height: {button_size}px;
                max-width: {button_size}px;
            }}
            QPushButton:hover {{
                background-color: #e0e0e0;
                border-color: #999999;
            }}
            QPushButton:pressed {{
                background-color: #d0d0d0;
                border-color: #666666;
            }}
            QPushButton#relate-preview {{
                background-color: #f8f8f8;
                border: 1px solid #cccccc;
                border-radius: 3px;
                color: #333333;
                font-size: {relate_font_size}px;
                text-align: left;
                font-weight: bold;
                padding: 2px;               
                min-height: {button_size}px;
                min-width: {button_size}px;
                max-height: {button_size}px;
                max-width: {button_size}px;
            }}
            QPushButton#function-button {{
                background-color: #e0e0e0;
                border: 1px solid #cccccc;
                border-radius: 3px;
                color: #000000;
                min-height: {func_button_size}px;
                max-height: {func_button_size}px;
                font-size: {relate_font_size}px;
                padding: 3px;
            }}
            QLabel {{
                color: #000000;
                font-size: {input_display_font_size}px;
                text-align: center;
                padding: 1px;
                background-color: transparent;
            }}
        """
        
        self.setStyleSheet(new_style)

        # 图标尺寸也相应减小
        icon_size = int(65 * scale_factor)  # 从80减少到65
        for btn in self.grid_buttons.values():
            btn.setIconSize(QSize(icon_size, icon_size))
    def set_button_img(self, type_val):
        """根據 type 設置九宮格按鈕的圖像"""
        for i in range(1, 10):
            num = (11 if type_val == 10 else type_val) * 10 + i
            btn = self.grid_buttons[i]
            btn.setObjectName("NumberButton")
            btn.setStyleSheet("")   
            if num in self.images:
                btn.setIcon(QIcon(self.images[num]))
                #print(f"Png:"f"{num}")
                btn.setIconSize(QSize(80, 80))
                btn.setText("")
            else:
                btn.setText(str(i))
                btn.setIcon(QIcon())            
            
            #btn.setStyleSheet("""
            #    QPushButton {
            #        background-color: #404040;
            #        border: 1px solid #555;
            #        border-radius: 5px;
            #        color: white;
            #        font-size: 14px;
            #        font-weight: bold;
            #        padding: 10px;
            #        min-height: 70px;
            #    }
            #    QPushButton:hover { background-color: #505050; }
            #    QPushButton:pressed { background-color: #606060; }
            #""")
        self.function_0_btn.setText("標點")

    def create_grid_buttons(self):
        self.grid_buttons = {}
        positions = [(2, 0, 1), (2, 1, 2), (2, 2, 3),
                     (1, 0, 4), (1, 1, 5), (1, 2, 6),
                     (0, 0, 7), (0, 1, 8), (0, 2, 9)]
        for row, col, num in positions:
            btn = QPushButton(str(num))
            btn.clicked.connect(lambda checked, n=num: self.handle_key_input(n))
            self.grid_layout.addWidget(btn, row, col)
            self.grid_buttons[num] = btn

    def init_database(self):
        if os.path.exists(self.db_path):
            self.db_connection = sqlite3.connect(self.db_path)
            print(f"數據庫連接成功: {self.db_path}")
        else:
            print(f"數據庫文件不存在: {self.db_path}")

    def sql_to_character_array(self, sql_statement):
        try:
            cursor = self.db_connection.cursor()
            cursor.execute(sql_statement)
            result = cursor.fetchone()
            if result and result[0]:
                return list(result[0])
            return None
        except Exception as e:
            print(f"SQL查詢錯誤: {e}")
            return None

    def key_input(self, key):
        """根據 key 查詢字符"""
        print(f"查詢字符: {key}")
        return self.sql_to_character_array(f"SELECT characters FROM mapped_table WHERE id='{key}'")

    def get_relate(self, word):
        if not self.db_connection:
            return None
        try:
            cursor = self.db_connection.cursor()
            cursor.execute(f"SELECT candidates FROM related_candidates_table WHERE character='{word}'")
            result = cursor.fetchone()
            if result and result[0]:
                return [w.strip() for w in result[0].split(" ") if w.strip()]
            return None
        except Exception as e:
            print(f"關聯詞查詢錯誤: {e}")
            return None
    def create_text_overlay_with_background(self, base_image, text, font_size=16):
        """创建带背景色的文字覆盖（更好的可读性）"""
        if base_image.isNull():
            return base_image
        
        result_pixmap = QPixmap(base_image.size())
        result_pixmap.fill(Qt.transparent)
        
        painter = QPainter(result_pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 绘制原始图像
        painter.drawPixmap(0, 0, base_image)
        
        # 文字区域
        text_rect = result_pixmap.rect()
        text_rect.setRight(text_rect.width() // 2)
        text_rect.setBottom(text_rect.height() // 2)
        
        # 绘制半透明白色背景提高文字可读性
        painter.fillRect(text_rect, QColor(255, 255, 255, 180))
        
        # 设置字体和文字颜色
        font = QFont("Arial", font_size, QFont.Bold)
        painter.setFont(font)
        painter.setPen(QPen(QColor(0, 0, 0), 2))
        
        # 绘制文字
        painter.drawText(text_rect, Qt.AlignTop | Qt.AlignLeft, text)
        
        painter.end()
        return result_pixmap
    def create_text_overlay_image(self, base_image, text, font_size=16):
        """为白底主题创建文字覆盖图像"""
        if base_image.isNull():
            return base_image
        
        result_pixmap = QPixmap(base_image.size())
        result_pixmap.fill(Qt.transparent)
        
        painter = QPainter(result_pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 绘制原始图像
        painter.drawPixmap(0, 0, base_image)
        
        # 设置字体
        font = QFont("Arial", font_size, QFont.Bold)
        painter.setFont(font)
        
        # 黑色文字，适合白底主题
        painter.setPen(QPen(QColor(0, 0, 0), 2))  # 黑色文字
        
        # 文字区域 - 左上角
        text_rect = result_pixmap.rect()
        text_rect.setRight(text_rect.width() // 2)    # 左半部
        text_rect.setBottom(text_rect.height() // 2)  # 上半部
        
        # 绘制文字
        painter.drawText(text_rect, Qt.AlignTop | Qt.AlignLeft, text)
        
        painter.end()
        return result_pixmap

    def show_relate_preview(self, relates):
        """显示关联词预览，白底主题版本"""
        self.current_relates = relates
        self.showing_relates = True
        self.current_page = "input"
        self.select_mode = False
        self.select_words = []
        self.curr_page = 0
        self.total_page = 0
        
        for i in range(1, 10):
            btn = self.grid_buttons[i]
            
            if i-1 < len(relates) and relates[i-1] and relates[i-1] != "*":
                # 有关联词的情况
                num = 100 + i
                if num in self.images:
                    # 创建带有黑色文字的复合图像
                    base_image = self.images[num]
                    composite_image = self.create_text_overlay_image(
                        base_image, 
                        relates[i-1], 
                        font_size=45
                    )
                    btn.setIcon(QIcon(composite_image))
                    btn.setIconSize(QSize(80, 80))
                    btn.setText("")
                else:
                    # 没有对应图像，使用按钮文字
                    btn.setText(relates[i-1])
                    btn.setIcon(QIcon())
                
                btn.setObjectName("relate-preview")
            else:
                # 空白情况
                num = 100 + i
                if num in self.images:
                    btn.setText("")
                    btn.setIcon(QIcon(self.images[num]))
                    btn.setIconSize(QSize(80, 80))
                else:
                    btn.setText("")
                    btn.setIcon(QIcon())
                
                btn.setObjectName("relate-preview")
            
            btn.setStyleSheet("")  # 使用默认样式
            btn.update()
        
        self.function_0_btn.setText("選字" if relates else "標點")
        self.function_dot_btn.setText("取消")

    def show_page_list(self, words):
        for i in range(1, 10):
            if i <= len(words):
                self.grid_buttons[i].setText(words[i - 1])
            else:
                self.grid_buttons[i].setText(str(i))

    def handle_key_input(self, key):

        # 处理F10切换显示/隐藏
        if key == "F10":
            self.toggle_visibility()
            return
        
        # 如果界面隐藏，忽略其他输入法按键
        if self.is_hidden:
            return
        """統一處理所有輸入"""
        if key == ".":
            self.reset_input()
            return

        try:
            num = int(key)
        except ValueError:
            return

        # === 選字模式 ===
        if self.select_mode:
            if num == 0:
                self.add_page(1)
            else:
                page_index = self.curr_page * 9 + num - 1
                if 0 <= page_index < len(self.select_words):
                    selected_char = self.select_words[page_index]
                    if not isinstance(selected_char, str):
                        print(f"[調試] select_word(): 非 str 類型，自動轉換: {type(selected_char)}")
                        selected_char = str(selected_char)
                    self.select_word(selected_char)
            return

        # === 關聯詞預覽模式 ===
        if self.showing_relates:
            if num == 0:
                self.start_select_word(self.current_relates)
                return
            elif key == ".":
                self.reset_input()
                return
            else:
                print("不關聯詞輸入")
                self.reset_input()
                       
            

        # === 輸入模式 ===
        self.current_input += str(num)
        print("Output: " + f"{self.current_input}")  
        #self.input_display.setText(self.current_input)

        # 單獨處理 0、10、20...90 立即查詢
        if self.current_input in ["0", "10", "20", "30", "40", "50", "60", "70", "80", "90"]:
            chars = self.key_input(self.current_input)
            if chars:
                print(f"[調試] DB 查詢 {self.current_input} → {chars}")
                self.start_select_word(chars)
            else:
                #self.status_label.setText(f"未找到 {self.current_input} 對應的字符")
                self.reset_input()
            return

        # 普通三位數輸入完成
        if len(self.current_input) == 3:
            chars = self.key_input(self.current_input)
            if chars:
                print(f"[調試] DB 查詢 {self.current_input} → {chars}")
                self.start_select_word(chars)
            else:
                #self.status_label.setText(f"未找到 {self.current_input} 對應的字符")
                self.reset_input()
        elif len(self.current_input) == 1:
            self.set_button_img(num)
        elif len(self.current_input) == 2:
            self.set_button_img(10)

    def output_character(self, char):
        """输出字符 - 使用跨平台方法"""
        self.output_character_cross_platform(char)
    def start_select_word(self, words):
        if not isinstance(words, (list, tuple)):
            print(f"[調試] start_select_word() 參數非列表，類型: {type(words)}")
            return
        if not words:
            print("[調試] start_select_word() 收到空列表")
            return
        self.select_words = words
        self.total_page = (len(words) + 8) // 9
        self.select_mode = True
        self.current_input = ""
        self.current_page = "select"
        self.show_page(0)
        self.function_0_btn.setText("下頁")

    def select_word(self, selected_char):
        """選擇字符，保留關聯功能"""
        if not isinstance(selected_char, str):
            print(f"[調試] select_word(): 非 str 類型，自動轉換: {type(selected_char)}")
            selected_char = str(selected_char)
        self.output_character(selected_char)
        if len(selected_char) == 1:
            self.last_word = selected_char
            relates = self.get_relate(selected_char)
            if relates:
                self.show_relate_preview(relates)
            else:
                self.reset_input()
        else:
            self.last_word = ""
            self.reset_input()

    def show_page(self, show_page_num):
        self.curr_page = show_page_num
        for i in range(1, 10):
            page_index = self.curr_page * 9 + i - 1
            btn = self.grid_buttons[i]
            
            # 移除硬编码的样式，让按钮使用全局白底主题样式
            btn.setObjectName("NumberButton")  # 设置为数字按钮样式
            btn.setStyleSheet("")  # 清除内联样式，使用全局样式表
            btn.setIcon(QIcon())   # 清除图标
            
            if page_index >= len(self.select_words):
                btn.setText("")
            else:
                word = self.select_words[page_index]
                btn.setText(word if word and word != "*" else "")
        page_info = f"{self.curr_page + 1}/{self.total_page}頁" if self.total_page > 1 else ""
        #self.status_label.setText(f"請選擇字符 - {page_info}")

    def add_page(self, add_num):
        new_page = (self.curr_page + add_num) % self.total_page
        self.show_page(new_page)

    def tcsc(self, input_char):
        """Convert traditional Chinese to simplified Chinese using ts_chinese_table"""
        if not self.db_connection:
            print("Database connection not initialized")
            return input_char
        
        output = ""
        for c in input_char:
            try:
                cursor = self.db_connection.cursor()
                query = f"SELECT simplified FROM ts_chinese_table WHERE traditional='{c}' LIMIT 1"
                cursor.execute(query)
                result = cursor.fetchone()
                if result and result[0]:
                    output += result[0]
                else:
                    output += c
            except Exception as e:
                print(f"Error converting character '{c}': {e}")
                output += c
        return output
    def tcsc_output(self):
        """Toggle between simplified and traditional Chinese output"""
        self.sc_output = not self.sc_output
        print(f"Output mode: {'Simplified' if self.sc_output else 'Traditional'} Chinese")
        self.set_button_img(0)  # Reset button images
        
    def output_character_cross_platform(self, char):
        """跨平台字符输出"""
        output_char = self.tcsc(char) if self.sc_output else char
        print(f"输出字符: {output_char}")
        
        # 根据操作系统选择输出方法
        try:
            if self.current_os == "Linux":
                # Linux 先复制到剪贴板再粘贴
                clipboard = self.app.clipboard()
                clipboard.setText(output_char)
                print(f"已复制到剪贴板: {output_char}")
                subprocess.run(["xdotool", "key", "ctrl+v"], check=True)
                print(f"Linux: 已模拟粘贴: {output_char}")
            elif self.current_os == "Windows":
                # Windows 直接使用 pynput 输出字符
                if WINDOWS_PYNPUT_AVAILABLE:
                    # 创建键盘控制器
                    kb = keyboard.Controller()
                    # 直接输入字符，无需剪贴板
                    kb.type(output_char)
                    print(f"Windows: 已直接输入: {output_char}")
                else:
                    # 回退到剪贴板方法
                    clipboard = self.app.clipboard()
                    clipboard.setText(output_char)
                    print("Windows: pynput 不可用，已复制到剪贴板，请手动粘贴")
        except Exception as e:
            print(f"字符输出失败: {e}", file=sys.stderr)
            # 失败时回退到剪贴板
            try:
                clipboard = self.app.clipboard()
                clipboard.setText(output_char)
                print(f"回退: 已复制到剪贴板: {output_char}")
            except Exception as e2:
                print(f"剪贴板操作也失败: {e2}", file=sys.stderr)

    def reset_input(self, clean_relate=True):
        self.current_input = ""
        self.current_page = "input"
        self.candidates = []
        self.select_words = []
        self.curr_page = 0
        self.total_page = 0
        self.select_mode = False
        self.last_word = ""
        self.current_relates = []
        self.showing_relates = False
        #self.status_label.setText("請輸入3位數字")
        #self.input_display.setText("")
        if clean_relate:
            self.set_button_img(0)
        self.function_0_btn.setText("標點")
        self.function_dot_btn.setText("取消")

def check_windows_dependencies():
    """檢查 Windows 依賴"""
    if platform.system() == "Windows":
        try:
            import pynput
            print("✓ Windows 依賴檢查通過")
            return True
        except ImportError:
            print("✗ Windows 缺少依賴")
            print("請運行以下命令安裝:")
            print("pip install pynput")
            return False
    return True


def main():
    if not check_windows_dependencies():
        input("按回車鍵退出...")
        return
    
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # 僅在 Linux 上掃描設備
    if platform.system() == "Linux":
        from evdev import InputDevice, list_devices
        device_options = []
        device_map = {}  # 映射名稱到路徑
        
        # 掃描 /dev/input/by-path 和 /dev/input/event* 設備
        try:
            # 嘗試 /dev/input/by-path
            by_path_devices = [os.path.join('/dev/input/by-path', d) for d in os.listdir('/dev/input/by-path') if os.path.islink(os.path.join('/dev/input/by-path', d))]
            for path in by_path_devices:
                try:
                    dev = InputDevice(path)
                    name = dev.name
                    device_options.append(name)
                    device_map[name] = path
                    dev.close()
                except Exception:
                    continue
            
            # 補充 /dev/input/event* 設備
            event_devices = [f"/dev/input/{d}" for d in os.listdir('/dev/input') if d.startswith('event')]
            for path in event_devices:
                try:
                    dev = InputDevice(path)
                    name = dev.name
                    if name not in device_map:  # 避免重複
                        device_options.append(name)
                        device_map[name] = path
                    dev.close()
                except Exception:
                    continue
        except FileNotFoundError:
            print("未找到設備目錄。使用預設路徑。")
            device_options = []
        
        if not device_options:
            print("未找到輸入設備。使用預設路徑。")
            device_path = "/dev/input/by-path/pci-0000:67:00.4-usb-0:1:1.0-event-kbd"
        else:
            # 顯示設備名稱選擇對話框
            from PyQt5.QtWidgets import QInputDialog
            device_name, ok = QInputDialog.getItem(None, "選擇輸入設備", "選擇鍵盤設備:", device_options, 0, False)
            if not ok:
                sys.exit(0)  # 用戶取消選擇
            device_path = device_map[device_name]
            print(f"選定設備: {device_name} -> {device_path}")
    else:
        # 非 Linux 系統使用預設行為
        device_path = None

    input_method = Q9InputMethodUI(device_path)
    input_method.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
