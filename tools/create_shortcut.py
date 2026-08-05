import os
import sys
import subprocess

def create_desktop_shortcut():
    project_root = r"c:\Dev\GitHub\05_FileOperation"
    main_py = os.path.join(project_root, "src", "main.py")
    icon_ico = os.path.join(project_root, "src", "assets", "icon.ico")
    
    # Desktop path
    desktop_path = os.path.join(os.environ["USERPROFILE"], "Desktop")
    shortcut_path = os.path.join(desktop_path, "FileOps Hub.lnk")
    
    # Target pythonw.exe to avoid persistent console window if available
    python_exe = sys.executable
    pythonw_exe = os.path.join(os.path.dirname(python_exe), "pythonw.exe")
    if not os.path.exists(pythonw_exe):
        pythonw_exe = python_exe
        
    # Check dist EXE if built
    dist_exe = os.path.join(project_root, "dist", "IntegratedDataTool.exe")
    if os.path.exists(dist_exe):
        target_path = dist_exe
        args = ""
    else:
        target_path = pythonw_exe
        args = f'"{main_py}"'
        
    ps_script = f"""
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut('{shortcut_path}')
$Shortcut.TargetPath = '{target_path}'
$Shortcut.Arguments = '{args}'
$Shortcut.WorkingDirectory = '{project_root}'
$Shortcut.IconLocation = '{icon_ico}'
$Shortcut.Description = 'FileOps Hub - Seamless File Operations'
$Shortcut.Save()
"""
    
    ps_file = os.path.join(project_root, "tools", "make_shortcut.ps1")
    with open(ps_file, "w", encoding="utf-8") as f:
        f.write(ps_script)
        
    res = subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", ps_file], capture_output=True, text=True)
    if res.returncode == 0:
        print(f"Desktop shortcut successfully created: {shortcut_path}")
    else:
        print(f"Error creating shortcut: {res.stderr}")
        
    # Clean up ps file
    if os.path.exists(ps_file):
        os.remove(ps_file)

if __name__ == "__main__":
    create_desktop_shortcut()
