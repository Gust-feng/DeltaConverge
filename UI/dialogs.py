import sys
import os
import subprocess
import logging
import asyncio

# 配置日志
logger = logging.getLogger(__name__)

def pick_folder() -> str | None:
    """
    打开系统原生文件夹选择对话框并返回路径。
    支持 Windows (Modern UI), macOS, Linux。
    如果原生方法失败，回退到 Tkinter。
    
    注意：此函数是阻塞的，应该在线程池中运行。
    """
    system = sys.platform
    try:
        if system == "win32":
            return _pick_folder_windows()
        elif system == "darwin":
            return _pick_folder_macos()
        else:
            return _pick_folder_linux()
    except Exception as e:
        logger.error(f"Native picker failed, falling back to tkinter: {e}")
        return _pick_folder_tkinter()

def _pick_folder_windows() -> str | None:
    """
    使用 PowerShell 和 C# COM Interop 调用 Windows Vista+ 风格的 IFileOpenDialog。
    比旧版 FolderBrowserDialog 更现代、美观。
    """
    # C# 代码定义，通过 PowerShell Add-Type 编译
    # 包含了必要的 COM 接口定义
    ps_script = r"""
    Add-Type -TypeDefinition @"
    using System;
    using System.Runtime.InteropServices;

    [ComImport, Guid("DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7")]
    [ClassInterface(ClassInterfaceType.None)]
    public class FileOpenDialog { }

    [ComImport, Guid("42f85136-db7e-439c-85f1-e4075d135fc8")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IFileDialog {
        [PreserveSig] int Show(IntPtr parent);
        void SetFileTypes();
        void SetFileTypeIndex();
        void GetFileTypeIndex();
        void Advise();
        void Unadvise();
        void SetOptions(uint fos);
        void GetOptions();
        void SetDefaultFolder();
        void SetFolder();
        void GetFolder();
        void GetCurrentSelection();
        void SetFileName();
        void GetFileName();
        void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string title);
        void SetOkButtonLabel();
        void SetFileNameLabel();
        void GetResult(out IShellItem ppsi);
        void AddPlace();
        void SetDefaultExtension();
        void Close();
        void SetClientGuid();
        void ClearClientData();
        void SetFilter();
    }

    [ComImport, Guid("43826d1e-e718-42ee-bc55-a1e261c37bfe")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IShellItem {
        void BindToHandler();
        void GetParent();
        void GetDisplayName(uint sigdnName, [MarshalAs(UnmanagedType.LPWStr)] out string ppszName);
        void GetAttributes();
        void Compare();
    }

    public class Picker {
        public static string Show() {
            try {
                var dialog = new FileOpenDialog();
                var ifd = (IFileDialog)dialog;
                
                // FOS_PICKFOLDERS = 0x20 | FOS_FORCEFILESYSTEM = 0x40
                ifd.SetOptions(0x60); 
                ifd.SetTitle("请选择项目根目录");
                
                // Show dialog
                int hr = ifd.Show(IntPtr.Zero);
                
                // Check if cancelled (hr < 0)
                if (hr < 0) return null;

                IShellItem item;
                ifd.GetResult(out item);
                string path;
                // SIGDN_FILESYSPATH = 0x80058000
                item.GetDisplayName(0x80058000, out path); 
                return path;
            } catch {
                return null;
            }
        }
    }
"@
    [Picker]::Show()
    """
    
    cmd = ["powershell", "-NoProfile", "-Command", ps_script]
    
    # 隐藏 PowerShell 窗口 (仅限 Windows)
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    
    result = subprocess.run(
        cmd, 
        capture_output=True, 
        startupinfo=startupinfo
    )
    
    if not result.stdout:
        return None

    try:
        # 尝试多种编码解码输出
        path = result.stdout.decode('utf-8').strip()
    except UnicodeDecodeError:
        try:
            import locale
            path = result.stdout.decode(locale.getpreferredencoding(), errors='replace').strip()
        except Exception:
            path = result.stdout.decode('utf-8', errors='replace').strip()
            
    return path if path else None

def _pick_folder_macos() -> str | None:
    """使用 AppleScript 调用原生 macOS 文件夹选择器"""
    script = 'tell application "System Events" to activate' + '\n' + \
             'tell application "System Events" to return POSIX path of (choose folder with prompt "请选择项目根目录")'
    
    try:
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
        if not result.stdout:
            return None
        path = result.stdout.strip()
        return path if path else None
    except Exception:
        return None

def _pick_folder_linux() -> str | None:
    """尝试使用 Zenity 或 KDialog"""
    # Try zenity (GNOME/GTK)
    try:
        result = subprocess.run(
            ['zenity', '--file-selection', '--directory', '--title=请选择项目根目录'],
            capture_output=True, text=True
        )
        if result.stdout:
            path = result.stdout.strip()
            if path: return path
    except FileNotFoundError:
        pass
        
    # Try kdialog (KDE/Qt)
    try:
        result = subprocess.run(
            ['kdialog', '--getexistingdirectory'],
            capture_output=True, text=True
        )
        if result.stdout:
            path = result.stdout.strip()
            if path: return path
    except FileNotFoundError:
        pass
        
    return _pick_folder_tkinter()

def _pick_folder_tkinter() -> str | None:
    """通用回退方案：使用 Tkinter (Python 内置)"""
    try:
        import tkinter as tk
        from tkinter import filedialog
        
        root = tk.Tk()
        root.withdraw() # 隐藏主窗口
        root.attributes('-topmost', True) # 窗口置顶
        
        # 在 Windows 上 askdirectory 通常也是调用原生 API
        path = filedialog.askdirectory(title="请选择项目根目录")
        
        root.destroy()
        return path if path else None
    except Exception as e:
        logger.error(f"Tkinter picker failed: {e}")
        return None
