import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

# ====== CONFIG (dorkar hole change korben) ======
PROJECT_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = PROJECT_DIR / "config" / "settings.py"
PORT = "8000"
EXTRA_HOSTS = ["localhost", "127.0.0.1"]
# =================================================


def get_python_exe():
    """.venv ba venv thakle sheta use kore, na thakle system Python."""
    for name in (".venv", "venv"):
        exe = PROJECT_DIR / name / "Scripts" / "python.exe"
        if exe.exists():
            print(f"Virtualenv use korchi: {exe}")
            return str(exe)
    print("Virtualenv paoya jayni, system Python use korchi.")
    return sys.executable


def get_local_ip(retries=30, delay=2):
    """Network ready na hole kichukkhon wait kore retry kore."""
    for _ in range(retries):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))  # asholey data pathay na, shudhu route dekhe
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
        except OSError:
            pass
        finally:
            s.close()
        print("Network ekhono ready na, wait korchi...")
        time.sleep(delay)
    return None


def update_allowed_hosts(ip):
    text = SETTINGS_PATH.read_text(encoding="utf-8")
    hosts = EXTRA_HOSTS + [ip]
    new_line = "ALLOWED_HOSTS = [" + ", ".join(f"'{h}'" for h in hosts) + "]"

    pattern = re.compile(r"^ALLOWED_HOSTS\s*=\s*\[.*?\]", re.DOTALL | re.MULTILINE)
    if pattern.search(text):
        new_text = pattern.sub(new_line, text, count=1)
    else:
        new_text = text + "\n" + new_line + "\n"

    if new_text != text:
        SETTINGS_PATH.write_text(new_text, encoding="utf-8")
        print(f"ALLOWED_HOSTS update hoyeche: {hosts}")
    else:
        print("ALLOWED_HOSTS age thekei thik ache.")


def main():
    ip = get_local_ip()
    if not ip:
        print("IP paoya jayni. Network check korun.")
        sys.exit(1)

    print(f"Current IP: {ip}")
    update_allowed_hosts(ip)

    os.chdir(PROJECT_DIR)
    python_exe = get_python_exe()
    print(f"Server cholche: http://{ip}:{PORT}")
    subprocess.run([python_exe, "manage.py", "runserver", f"0.0.0.0:{PORT}"])


if __name__ == "__main__":
    main()