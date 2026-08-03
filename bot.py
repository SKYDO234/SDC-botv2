import discord
from discord.ext import commands
import asyncio
import subprocess
import json
from datetime import datetime, timedelta
import shlex
import logging
import shutil
import os
from typing import Optional, List, Dict, Any
import threading
import time
import sqlite3
import random
import requests
import string
import secrets
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Load environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
BOT_NAME = os.getenv('BOT_NAME', 'UnixNodes')
PREFIX = os.getenv('PREFIX', '!')
YOUR_SERVER_IP = os.getenv('YOUR_SERVER_IP', '127.0.0.1')
MAIN_ADMIN_ID = int(os.getenv('MAIN_ADMIN_ID', '1210291131301101618'))
VPS_USER_ROLE_ID = int(os.getenv('VPS_USER_ROLE_ID', '1210291131301101618'))
DEFAULT_STORAGE_POOL = os.getenv('DEFAULT_STORAGE_POOL', 'default')
HOST_MOTD = os.getenv('HOST_MOTD', 'bash <(curl -fsSL https://raw.githubusercontent.com/hopingboyz/linux/main/atyro-water-mark.sh)')
BOT_VERSION = os.getenv('BOT_VERSION', '8.0-DUAL')
BOT_DEVELOPER = os.getenv('BOT_DEVELOPER', 'Hopingboz')
BOT_THUMBNAIL_URL = os.getenv('BOT_THUMBNAIL_URL', 'https://i.imgur.com/Tv3clt0.jpeg')
BOT_ICON_URL = os.getenv('BOT_ICON_URL', 'https://i.imgur.com/Tv3clt0.jpeg')

# VPS Expiration Settings
DEFAULT_VPS_EXPIRATION_DAYS = int(os.getenv('DEFAULT_VPS_EXPIRATION_DAYS', '30'))
EXPIRATION_WARNING_DAYS = int(os.getenv('EXPIRATION_WARNING_DAYS', '1'))

# SSH Configuration
SSH_FIX_SCRIPT = """#!/bin/bash
cat > /etc/ssh/sshd_config << 'SSHEOF'
Port 22
AddressFamily any
ListenAddress 0.0.0.0
ListenAddress ::
PasswordAuthentication yes
PubkeyAuthentication yes
PermitRootLogin yes
PermitEmptyPasswords no
ChallengeResponseAuthentication no
UsePAM yes
MaxAuthTries 6
MaxSessions 10
SyslogFacility AUTH
LogLevel INFO
X11Forwarding yes
X11DisplayOffset 10
PrintMotd no
PrintLastLog yes
TCPKeepAlive yes
PermitUserEnvironment no
Subsystem sftp /usr/lib/openssh/sftp-server
SSHEOF
systemctl restart ssh 2>/dev/null || service ssh restart 2>/dev/null || /etc/init.d/ssh restart 2>/dev/null || true
"""

# OS Options for VPS Creation and Reinstall
OS_OPTIONS = [
    {"label": "Ubuntu 20.04 LTS", "value": "ubuntu:20.04"},
    {"label": "Ubuntu 22.04 LTS", "value": "ubuntu:22.04"},
    {"label": "Ubuntu 24.04 LTS", "value": "ubuntu:24.04"},
    {"label": "Debian 10 (Buster)", "value": "images:debian/10"},
    {"label": "Debian 11 (Bullseye)", "value": "images:debian/11"},
    {"label": "Debian 12 (Bookworm)", "value": "images:debian/12"},
    {"label": "Debian 13 (Trixie)", "value": "images:debian/13"},
]

# Configure logging to file and console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(f'{BOT_NAME.lower()}_vps_bot')

# Database setup
def get_db():
    conn = sqlite3.connect('vps.db')
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS admins (
        user_id TEXT PRIMARY KEY
    )''')
    cur.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (str(MAIN_ADMIN_ID),))
    cur.execute('''CREATE TABLE IF NOT EXISTS nodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        location TEXT,
        total_vps INTEGER,
        tags TEXT DEFAULT '[]',
        api_key TEXT,
        url TEXT,
        is_local INTEGER DEFAULT 0
    )''')
    cur.execute('SELECT COUNT(*) FROM nodes WHERE is_local = 1')
    if cur.fetchone()[0] == 0:
        cur.execute('INSERT INTO nodes (name, location, total_vps, tags, api_key, url, is_local) VALUES (?, ?, ?, ?, ?, ?, ?)',
                    ('Local Node', 'Local', 100, '[]', None, None, 1))
    cur.execute('''CREATE TABLE IF NOT EXISTS vps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        node_id INTEGER NOT NULL DEFAULT 1,
        container_name TEXT UNIQUE NOT NULL,
        ram TEXT NOT NULL,
        cpu TEXT NOT NULL,
        storage TEXT NOT NULL,
        config TEXT NOT NULL,
        os_version TEXT DEFAULT 'ubuntu:22.04',
        status TEXT DEFAULT 'stopped',
        suspended INTEGER DEFAULT 0,
        whitelisted INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        shared_with TEXT DEFAULT '[]',
        suspension_history TEXT DEFAULT '[]',
        expiration_date TEXT DEFAULT NULL,
        root_password TEXT DEFAULT NULL,
        backend_type TEXT DEFAULT 'lxc'
    )''')
    # Migrations
    cur.execute('PRAGMA table_info(vps)')
    info = cur.fetchall()
    columns = [col[1] for col in info]
    if 'os_version' not in columns:
        cur.execute("ALTER TABLE vps ADD COLUMN os_version TEXT DEFAULT 'ubuntu:22.04'")
    if 'node_id' not in columns:
        cur.execute("ALTER TABLE vps ADD COLUMN node_id INTEGER DEFAULT 1")
    if 'expiration_date' not in columns:
        cur.execute("ALTER TABLE vps ADD COLUMN expiration_date TEXT DEFAULT NULL")
    if 'root_password' not in columns:
        cur.execute("ALTER TABLE vps ADD COLUMN root_password TEXT DEFAULT NULL")
    if 'backend_type' not in columns:
        cur.execute("ALTER TABLE vps ADD COLUMN backend_type TEXT DEFAULT 'lxc'")
    cur.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )''')
    settings_init = [
        ('cpu_threshold', '90'),
        ('ram_threshold', '90'),
    ]
    for key, value in settings_init:
        cur.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (key, value))
    cur.execute('''CREATE TABLE IF NOT EXISTS port_allocations (
        user_id TEXT PRIMARY KEY,
        allocated_ports INTEGER DEFAULT 0
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS port_forwards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        vps_container TEXT NOT NULL,
        vps_port INTEGER NOT NULL,
        host_port INTEGER NOT NULL,
        created_at TEXT NOT NULL
    )''')
    conn.commit()
    conn.close()

def get_setting(key: str, default: Any = None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT value FROM settings WHERE key = ?', (key,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key: str, value: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()

def get_nodes() -> List[Dict]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM nodes')
    rows = cur.fetchall()
    conn.close()
    nodes = [dict(row) for row in rows]
    for node in nodes:
        node['tags'] = json.loads(node['tags'])
        node['is_local'] = int(node.get('is_local', 1)) == 1
    return nodes

def get_node(node_id: int) -> Optional[Dict]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM nodes WHERE id = ?', (node_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        node = dict(row)
        node['tags'] = json.loads(node['tags'])
        node['is_local'] = int(node.get('is_local', 1)) == 1
        return node
    return None

def get_vps_by_id(vps_id: int) -> Optional[Dict]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM vps WHERE id = ?', (vps_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        vps = dict(row)
        vps['shared_with'] = json.loads(vps.get('shared_with', '[]'))
        vps['suspension_history'] = json.loads(vps.get('suspension_history', '[]'))
        vps['suspended'] = bool(vps.get('suspended', 0))
        vps['whitelisted'] = bool(vps.get('whitelisted', 0))
        vps['os_version'] = vps.get('os_version', 'ubuntu:22.04')
        vps['backend_type'] = vps.get('backend_type', 'lxc')
        return vps
    return None

def get_current_vps_count(node_id: int) -> int:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM vps WHERE node_id = ?', (node_id,))
    count = cur.fetchone()[0]
    conn.close()
    return count

def get_vps_data() -> Dict[str, List[Dict[str, Any]]]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM vps')
    rows = cur.fetchall()
    conn.close()
    data = {}
    for row in rows:
        user_id = row['user_id']
        if user_id not in data:
            data[user_id] = []
        vps = dict(row)
        vps['shared_with'] = json.loads(vps['shared_with'])
        vps['suspension_history'] = json.loads(vps['suspension_history'])
        vps['suspended'] = bool(vps['suspended'])
        vps['whitelisted'] = bool(vps['whitelisted'])
        vps['os_version'] = vps.get('os_version', 'ubuntu:22.04')
        vps['backend_type'] = vps.get('backend_type', 'lxc')
        data[user_id].append(vps)
    return data

def get_admins() -> List[str]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT user_id FROM admins')
    rows = cur.fetchall()
    conn.close()
    return [row['user_id'] for row in rows]

def save_vps_data():
    conn = get_db()
    cur = conn.cursor()
    for user_id, vps_list in vps_data.items():
        for vps in vps_list:
            shared_json = json.dumps(vps['shared_with'])
            history_json = json.dumps(vps['suspension_history'])
            suspended_int = 1 if vps['suspended'] else 0
            whitelisted_int = 1 if vps.get('whitelisted', False) else 0
            os_ver = vps.get('os_version', 'ubuntu:22.04')
            created_at = vps.get('created_at', datetime.now().isoformat())
            node_id = vps.get('node_id', 1)
            expiration_date = vps.get('expiration_date', None)
            root_password = vps.get('root_password', None)
            backend_type = vps.get('backend_type', 'lxc')
            if 'id' not in vps or vps['id'] is None:
                cur.execute('''INSERT INTO vps (user_id, node_id, container_name, ram, cpu, storage, config, os_version, status, suspended, whitelisted, created_at, shared_with, suspension_history, expiration_date, root_password, backend_type)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                            (user_id, node_id, vps['container_name'], vps['ram'], vps['cpu'], vps['storage'], vps['config'],
                             os_ver, vps['status'], suspended_int, whitelisted_int,
                             created_at, shared_json, history_json, expiration_date, root_password, backend_type))
                vps['id'] = cur.lastrowid
            else:
                cur.execute('''UPDATE vps SET user_id = ?, node_id = ?, container_name = ?, ram = ?, cpu = ?, storage = ?, config = ?, os_version = ?, status = ?, suspended = ?, whitelisted = ?, shared_with = ?, suspension_history = ?, expiration_date = ?, root_password = ?, backend_type = ?
                               WHERE id = ?''',
                            (user_id, node_id, vps['container_name'], vps['ram'], vps['cpu'], vps['storage'], vps['config'],
                             os_ver, vps['status'], suspended_int, whitelisted_int, shared_json, history_json, expiration_date, root_password, backend_type, vps['id']))
    conn.commit()
    conn.close()

def save_admin_data():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('DELETE FROM admins')
    for admin_id in admin_data['admins']:
        cur.execute('INSERT INTO admins (user_id) VALUES (?)', (admin_id,))
    conn.commit()
    conn.close()

# Port forwarding functions
def get_user_allocation(user_id: str) -> int:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT allocated_ports FROM port_allocations WHERE user_id = ?', (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 0

def get_user_used_ports(user_id: str) -> int:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM port_forwards WHERE user_id = ?', (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0]

def allocate_ports(user_id: str, amount: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('INSERT OR REPLACE INTO port_allocations (user_id, allocated_ports) VALUES (?, COALESCE((SELECT allocated_ports FROM port_allocations WHERE user_id = ?), 0) + ?)', (user_id, user_id, amount))
    conn.commit()
    conn.close()

def deallocate_ports(user_id: str, amount: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('UPDATE port_allocations SET allocated_ports = GREATEST(0, allocated_ports - ?) WHERE user_id = ?', (amount, user_id))
    conn.commit()
    conn.close()

def get_available_host_port(node_id: int) -> Optional[int]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT host_port FROM port_forwards WHERE vps_container IN (SELECT container_name FROM vps WHERE node_id = ?)', (node_id,))
    used_ports = set(row[0] for row in cur.fetchall())
    conn.close()
    for _ in range(100):
        port = random.randint(20000, 50000)
        if port not in used_ports:
            return port
    return None

async def create_port_forward(user_id: str, container: str, vps_port: int, node_id: int) -> Optional[int]:
    host_port = get_available_host_port(node_id)
    if not host_port:
        return None
    try:
        backend = find_backend_for_container(container)
        if backend == 'docker':
            # Docker port forwarding standard iptables simulation/proxy
            cmd = f"run -d --name proxy_{container}_{host_port} -p {host_port}:{vps_port} alpine/socat TCP-LISTEN:{vps_port},fork,reuseaddr TCP:127.0.0.1:{vps_port}"
            await execute_backend(container, cmd, node_id=node_id, backend='docker')
        else:
            await execute_lxc(container, f"config device add {container} tcp_proxy_{host_port} proxy listen=tcp:0.0.0.0:{host_port} connect=tcp:127.0.0.1:{vps_port}", node_id=node_id)
            await execute_lxc(container, f"config device add {container} udp_proxy_{host_port} proxy listen=udp:0.0.0.0:{host_port} connect=udp:127.0.0.1:{vps_port}", node_id=node_id)
        
        conn = get_db()
        cur = conn.cursor()
        cur.execute('INSERT INTO port_forwards (user_id, vps_container, vps_port, host_port, created_at) VALUES (?, ?, ?, ?, ?)',
                    (user_id, container, vps_port, host_port, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        return host_port
    except Exception as e:
        logger.error(f"Failed to create port forward: {e}")
        return None

async def remove_port_forward(forward_id: int, is_admin: bool = False) -> tuple[bool, Optional[str]]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT user_id, vps_container, host_port FROM port_forwards WHERE id = ?', (forward_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return False, None
    user_id, container, host_port = row
    node_id = find_node_id_for_container(container)
    backend = find_backend_for_container(container)
    try:
        if backend == 'docker':
            await execute_backend(container, f"rm -f proxy_{container}_{host_port}", node_id=node_id, backend='docker')
        else:
            await execute_lxc(container, f"config device remove {container} tcp_proxy_{host_port}", node_id=node_id)
            await execute_lxc(container, f"config device remove {container} udp_proxy_{host_port}", node_id=node_id)
        cur.execute('DELETE FROM port_forwards WHERE id = ?', (forward_id,))
        conn.commit()
        conn.close()
        return True, user_id
    except Exception as e:
        logger.error(f"Failed to remove port forward {forward_id}: {e}")
        conn.close()
        return False, None

def get_user_forwards(user_id: str) -> List[Dict]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM port_forwards WHERE user_id = ? ORDER BY created_at DESC', (user_id,))
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]

async def recreate_port_forwards(container_name: str) -> int:
    node_id = find_node_id_for_container(container_name)
    backend = find_backend_for_container(container_name)
    readded_count = 0
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT vps_port, host_port FROM port_forwards WHERE vps_container = ?', (container_name,))
    rows = cur.fetchall()
    for row in rows:
        vps_port = row['vps_port']
        host_port = row['host_port']
        try:
            if backend == 'docker':
                cmd = f"run -d --name proxy_{container_name}_{host_port} -p {host_port}:{vps_port} alpine/socat TCP-LISTEN:{vps_port},fork,reuseaddr TCP:127.0.0.1:{vps_port}"
                await execute_backend(container_name, cmd, node_id=node_id, backend='docker')
            else:
                await execute_lxc(container_name, f"config device add {container_name} tcp_proxy_{host_port} proxy listen=tcp:0.0.0.0:{host_port} connect=tcp:127.0.0.1:{vps_port}", node_id=node_id)
                await execute_lxc(container_name, f"config device add {container_name} udp_proxy_{host_port} proxy listen=udp:0.0.0.0:{host_port} connect=udp:127.0.0.1:{vps_port}", node_id=node_id)
            logger.info(f"Re-added port forward {host_port}->{vps_port} for {container_name}")
            readded_count += 1
        except Exception as e:
            logger.error(f"Failed to re-add port forward {host_port}->{vps_port} for {container_name}: {e}")
    conn.close()
    return readded_count

def find_node_id_for_container(container_name: str) -> int:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT node_id FROM vps WHERE container_name = ?', (container_name,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 1

def find_backend_for_container(container_name: str) -> str:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT backend_type FROM vps WHERE container_name = ?', (container_name,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row and row[0] else 'lxc'

# Initialize database
init_db()

# Load data at startup
vps_data = get_vps_data()
admin_data = {'admins': get_admins()}

_auto_save_pending = False

def mark_for_save():
    global _auto_save_pending
    _auto_save_pending = True

async def auto_save_task():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            global _auto_save_pending
            if _auto_save_pending:
                save_vps_data()
                _auto_save_pending = False
                logger.debug("Auto-saved VPS data")
        except Exception as e:
            logger.error(f"Error in auto-save task: {e}")
        await asyncio.sleep(2)

def save_vps_data_immediate():
    save_vps_data()
    mark_for_save()

# Global settings from DB
CPU_THRESHOLD = int(get_setting('cpu_threshold', 90))
RAM_THRESHOLD = int(get_setting('ram_threshold', 90))

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

resource_monitor_active = True

# ═══════════════════════════════════════════════════════════════════════════
# MODERN UI/UX SYSTEM
# ═══════════════════════════════════════════════════════════════════════════

COLOR_PRIMARY = 0x2c3e50      
COLOR_SUCCESS = 0x27ae60      
COLOR_ERROR = 0xe74c3c        
COLOR_WARNING = 0xf39c12      
COLOR_INFO = 0x3498db         
COLOR_NETWORK = 0x16a085      
COLOR_EXPIRED = 0xc0392b      
COLOR_ACTIVE = 0x16a085       
COLOR_SUSPENDED = 0x95a5a6    
COLOR_NODE = 0x8e44ad         

def truncate_text(text, max_length=1024):
    if not text:
        return text
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."

def generate_strong_password(length=16):
    charset = string.ascii_letters + string.digits + "!@#$%^&*"
    password = ''.join(secrets.choice(charset) for _ in range(length))
    return password

def sanitize_username_for_container(username: str) -> str:
    sanitized = username.replace('_', '-').replace(' ', '-')
    sanitized = ''.join(c for c in sanitized if c.isalnum() or c == '-')
    sanitized = sanitized.strip('-').lower()
    sanitized = sanitized[:30]
    return sanitized

def get_vps_password(container_name):
    for user_id, vps_list in vps_data.items():
        for vps in vps_list:
            if vps['container_name'] == container_name:
                return vps.get('root_password', None)
    return None

def set_vps_password(container_name, password):
    for user_id, vps_list in vps_data.items():
        for vps in vps_list:
            if vps['container_name'] == container_name:
                vps['root_password'] = password
                save_vps_data_immediate()
                return True
    return False

# Dual-Backend Command Execution Helper
async def execute_backend(container_name: str, command: str, timeout=120, node_id: Optional[int] = None, backend: str = "lxc"):
    if backend == "docker":
        return await execute_docker(container_name, command, timeout=timeout, node_id=node_id)
    else:
        return await execute_lxc(container_name, command, timeout=timeout, node_id=node_id)

async def execute_docker(container_name: str, command: str, timeout=120, node_id: Optional[int] = None):
    if node_id is None:
        node_id = find_node_id_for_container(container_name)
    node = get_node(node_id)
    if not node:
        raise Exception(f"Node {node_id} not found")
    
    full_command = f"docker {command}"
    if node['is_local']:
        try:
            cmd = shlex.split(full_command)
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            if proc.returncode != 0:
                error = stderr.decode().strip() if stderr else "Docker Command failed"
                raise Exception(f"Local Docker command failed: {error}\nCommand: {full_command}")
            return stdout.decode().strip() if stdout else True
        except Exception as e:
            logger.error(f"Docker Error: {full_command} - {str(e)}")
            raise
    else:
        url = f"{node['url']}/api/execute_docker"
        data = {"command": full_command}
        params = {"api_key": node["api_key"]}
        response = requests.post(url, json=data, params=params, timeout=timeout)
        if response.status_code != 200:
            raise Exception(f"Remote Docker execution failed on {node['name']}")
        return response.json().get("stdout", True)

async def configure_ssh(container_name, node_id, password, backend="lxc"):
    try:
        ssh_config_content = """Port 22
AddressFamily any
ListenAddress 0.0.0.0
ListenAddress ::
PasswordAuthentication yes
PubkeyAuthentication yes
PermitRootLogin yes
PermitEmptyPasswords no
ChallengeResponseAuthentication no
UsePAM yes
MaxAuthTries 6
MaxSessions 10
SyslogFacility AUTH
LogLevel INFO
X11Forwarding yes
X11DisplayOffset 10
PrintMotd no
PrintLastLog yes
TCPKeepAlive yes
PermitUserEnvironment no
Subsystem sftp /usr/lib/openssh/sftp-server"""

        config_cmd = ssh_config_content.replace('\n', '\\n')
        
        if backend == "docker":
            await execute_docker(container_name, f'exec {container_name} bash -c "echo -e \\"{config_cmd}\\" > /etc/ssh/sshd_config"', node_id=node_id)
            restart_cmd = "service ssh restart || service sshd restart || true"
            await execute_docker(container_name, f'exec {container_name} bash -c "{restart_cmd}"', node_id=node_id)
            await execute_docker(container_name, f"exec {container_name} bash -c \"echo 'root:{password}' | chpasswd\"", node_id=node_id)
        else:
            await execute_lxc(container_name, f'exec {container_name} -- bash -c "echo -e \\"{config_cmd}\\" > /etc/ssh/sshd_config"', node_id=node_id)
            restart_cmd = "systemctl restart ssh 2>/dev/null || service ssh restart 2>/dev/null || /etc/init.d/ssh restart 2>/dev/null || true"
            await execute_lxc(container_name, f'exec {container_name} -- bash -c "{restart_cmd}"', node_id=node_id)
            await execute_lxc(container_name, f"exec {container_name} -- bash -c \"echo 'root:{password}' | chpasswd\"", node_id=node_id)
            
        set_vps_password(container_name, password)
        return True, password
    except Exception as e:
        logger.error(f"Failed to configure SSH for {container_name}: {e}")
        return False, str(e)

def create_embed(title, description="", color=COLOR_PRIMARY):
    embed = discord.Embed(
        title=f"🌟 {title}",
        description=truncate_text(description, 4096),
        color=color
    )
    embed.set_thumbnail(url=BOT_THUMBNAIL_URL)
    embed.set_footer(
        text=f"Made by Hopingboyz • v{BOT_VERSION} • {datetime.now().strftime('%H:%M:%S')}",
        icon_url=BOT_ICON_URL
    )
    embed.timestamp = datetime.now()
    return embed

def add_field(embed, name, value, inline=False):
    embed.add_field(
        name=f"➤ {name}",
        value=truncate_text(value, 1024),
        inline=inline
    )
    return embed

def create_success_embed(title, description=""):
    return create_embed(title, description, COLOR_SUCCESS)

def create_error_embed(title, description=""):
    return create_embed(title, description, COLOR_ERROR)

def create_info_embed(title, description=""):
    return create_embed(title, description, COLOR_INFO)

def create_warning_embed(title, description=""):
    return create_embed(title, description, COLOR_WARNING)

def create_progress_bar(value, max_value=100, length=15):
    if max_value == 0:
        percentage = 0
    else:
        percentage = int((value / max_value) * 100)
    filled = int((percentage / 100) * length)
    bar = "🟩" * filled + "⬜" * (length - filled)
    return f"{bar} `{percentage}%`"

def format_expiration(vps):
    if not vps.get('expiration_date'):
        return "🔵 No expiration"
    
    exp_dt = datetime.fromisoformat(vps['expiration_date'])
    days = (exp_dt - datetime.now()).days
    
    if days < 0:
        return f"🔴 **EXPIRED** (`{abs(days)}d ago`)"
    elif days <= EXPIRATION_WARNING_DAYS:
        return f"🟡 **EXPIRING** (`{days}d left`)"
    else:
        return f"🟢 **ACTIVE** (`{days}d left`)"

def is_admin():
    async def predicate(ctx):
        user_id = str(ctx.author.id)
        if user_id == str(MAIN_ADMIN_ID) or user_id in admin_data.get("admins", []):
            return True
        raise commands.CheckFailure("You need admin permissions to use this command. Contact support.")
    return commands.check(predicate)

def is_main_admin():
    async def predicate(ctx):
        if str(ctx.author.id) == str(MAIN_ADMIN_ID):
            return True
        raise commands.CheckFailure("Only the main admin can use this command.")
    return commands.check(predicate)

# LXC command execution with multi-node support
async def execute_lxc(container_name: str, command: str, timeout=120, node_id: Optional[int] = None):
    if node_id is None:
        node_id = find_node_id_for_container(container_name)
    node = get_node(node_id)
    
    if not node:
        raise Exception(f"Node {node_id} not found")
    
    full_command = f"lxc {command}"
    
    if node['is_local']:
        try:
            cmd = shlex.split(full_command)
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise asyncio.TimeoutError(f"Command timed out after {timeout} seconds")
            
            if proc.returncode != 0:
                error = stderr.decode().strip() if stderr else "Command failed with no error output"
                raise Exception(f"Local LXC command failed: {error}\nCommand: {full_command}")
            return stdout.decode().strip() if stdout else True
        except Exception as e:
            logger.error(f"LXC Error: {full_command} - {str(e)}")
            raise
    else:
        url = f"{node['url']}/api/execute"
        data = {"command": full_command}
        params = {"api_key": node["api_key"]}
        try:
            response = requests.post(url, json=data, params=params, timeout=timeout)
            if response.status_code != 200:
                raise Exception(f"Remote execution failed on {node['name']}")
            res = response.json()
            if res.get("returncode", 1) != 0:
                stderr = res.get("stderr", "Command failed")
                raise Exception(f"Remote LXC command failed on {node['name']}: {stderr}")
            return res.get("stdout", True)
        except Exception as e:
            logger.error(f"Unexpected error on node {node['name']}: {str(e)}")
            raise

async def apply_lxc_config(container_name: str, node_id: int):
    try:
        await execute_lxc(container_name, f"config set {container_name} security.nesting true", node_id=node_id)
        await execute_lxc(container_name, f"config set {container_name} security.privileged true", node_id=node_id)
        await execute_lxc(container_name, f"config set {container_name} security.syscalls.intercept.mknod true", node_id=node_id)
        await execute_lxc(container_name, f"config set {container_name} security.syscalls.intercept.setxattr true", node_id=node_id)
        await execute_lxc(container_name, f"config set {container_name} linux.kernel_modules overlay,loop,nf_nat,ip_tables,ip6_tables,netlink_diag,br_netfilter", node_id=node_id)
        try:
            await execute_lxc(container_name, f"config device add {container_name} fuse unix-char path=/dev/fuse", node_id=node_id)
        except:
            pass
        raw_lxc_config = (
            "lxc.apparmor.profile = unconfined\n"
            "lxc.apparmor.allow_nesting = 1\n"
            "lxc.apparmor.allow_incomplete = 1\n"
            "lxc.cap.drop =\n"
            "lxc.cgroup.devices.allow = a\n"
            "lxc.cgroup2.devices.allow = a\n"
            "lxc.mount.auto = proc:rw sys:rw cgroup:rw shmounts:rw\n"
            "lxc.mount.entry = /dev/fuse dev/fuse none bind,create=file 0 0\n"
        )
        await execute_lxc(container_name, f"config set {container_name} raw.lxc '{raw_lxc_config}'", node_id=node_id)
    except Exception as e:
        logger.error(f"Failed to apply LXC config to {container_name}: {e}")

async def apply_internal_permissions(container_name: str, node_id: int):
    try:
        await asyncio.sleep(5)
        commands = [
            "mkdir -p /etc/sysctl.d/",
            "echo 'net.ipv4.ip_unprivileged_port_start=0' > /etc/sysctl.d/99-custom.conf",
            "echo 'net.ipv4.ping_group_range=0 2147483647' >> /etc/sysctl.d/99-custom.conf",
            "echo 'fs.inotify.max_user_watches=524288' >> /etc/sysctl.d/99-custom.conf",
            "echo 'kernel.unprivileged_userns_clone=1' >> /etc/sysctl.d/99-custom.conf",
            "sysctl -p /etc/sysctl.d/99-custom.conf || true"
        ]
        for cmd in commands:
            try:
                await execute_lxc(container_name, f"exec {container_name} -- bash -c \"{cmd}\"", node_id=node_id)
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Failed internal permissions on {container_name}: {e}")

async def get_or_create_vps_role(guild):
    global VPS_USER_ROLE_ID
    me = guild.me
    if not me or not me.guild_permissions.manage_roles:
        return None
    role_name = f"{BOT_NAME} VPS User"
    if VPS_USER_ROLE_ID:
        role = guild.get_role(VPS_USER_ROLE_ID)
        if role and role < me.top_role:
            return role
        VPS_USER_ROLE_ID = None
    role = discord.utils.get(guild.roles, name=role_name)
    if role:
        if role >= me.top_role:
            try:
                await role.delete(reason="Role above bot, recreating")
            except discord.Forbidden:
                return None
            role = None
        else:
            VPS_USER_ROLE_ID = role.id
            return role
    try:
        role = await guild.create_role(
            name=role_name,
            color=discord.Color.dark_purple(),
            permissions=discord.Permissions.none(),
            reason=f"{BOT_NAME} VPS User role"
        )
        await role.edit(position=me.top_role.position - 1)
        VPS_USER_ROLE_ID = role.id
        return role
    except Exception as e:
        logger.error(f"Failed to create VPS role: {e}")
        return None

def get_host_cpu_usage():
    try:
        import platform
        if platform.system() == "Windows":
            import psutil
            return psutil.cpu_percent(interval=1)
        else:
            if shutil.which("mpstat"):
                result = subprocess.run(['mpstat', '1', '1'], capture_output=True, text=True, timeout=10)
                output = result.stdout
                for line in output.split('\n'):
                    if 'all' in line and '%' in line:
                        return 100.0 - float(line.split()[-1])
            return 0.0
    except Exception:
        return 0.0

def get_host_ram_usage():
    try:
        import platform
        if platform.system() == "Windows":
            import psutil
            return psutil.virtual_memory().percent
        else:
            result = subprocess.run(['free', '-m'], capture_output=True, text=True, timeout=10)
            lines = result.stdout.splitlines()
            if len(lines) > 1:
                mem = lines[1].split()
                return (int(mem[2]) / int(mem[1]) * 100)
            return 0.0
    except Exception:
        return 0.0

def get_host_disk_usage():
    try:
        total, used, free = shutil.disk_usage("/")
        return f"{used // (2**30)}GB/{total // (2**30)}GB ({(used/total)*100:.1f}%)"
    except Exception:
        return "Unknown"

async def get_host_stats(node_id: int) -> Dict:
    node = get_node(node_id)
    if node['is_local']:
        return {
            "cpu": get_host_cpu_usage(),
            "ram": get_host_ram_usage(),
            "disk": get_host_disk_usage()
        }
    else:
        url = f"{node['url']}/api/get_host_stats"
        params = {"api_key": node["api_key"]}
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            stats = response.json()
            stats['disk'] = stats.get('disk', 'Unknown')
            return stats
        except Exception:
            return {"cpu": 0.0, "ram": 0.0, "disk": "Unknown"}

def check_vps_expiration():
    try:
        warned_users = set()
        for user_id, vps_list in vps_data.items():
            for vps in vps_list:
                if vps.get('expiration_date'):
                    expiration_dt = datetime.fromisoformat(vps['expiration_date'])
                    days_remaining = (expiration_dt - datetime.now()).days
                    hours_remaining = ((expiration_dt - datetime.now()).total_seconds() / 3600)
                    container_name = vps['container_name']
                    node_id = vps.get('node_id', 1)
                    backend = vps.get('backend_type', 'lxc')
                    
                    if days_remaining < 0 and not vps.get('suspended', False):
                        try:
                            if backend == 'docker':
                                asyncio.run(execute_docker(container_name, f"stop {container_name}", node_id=node_id))
                            else:
                                asyncio.run(execute_lxc(container_name, f"stop {container_name}", node_id=node_id))
                            vps['status'] = 'stopped'
                            vps['suspended'] = True
                            vps['suspension_history'].append({
                                'time': datetime.now().isoformat(),
                                'reason': f'Auto-suspended due to expiration',
                                'by': 'Expiration Monitor'
                            })
                            save_vps_data_immediate()
                        except Exception as e:
                            logger.error(f"Failed to auto-suspend VPS {container_name}: {e}")
    except Exception as e:
        logger.error(f"Error in VPS expiration check: {e}")

def resource_monitor():
    last_expiration_check = time.time()
    while resource_monitor_active:
        try:
            if time.time() - last_expiration_check > 3600:
                check_vps_expiration()
                last_expiration_check = time.time()
            nodes = get_nodes()
            for node in nodes:
                if node['is_local']:
                    stats = asyncio.run(get_host_stats(node['id']))
                    cpu, ram = stats['cpu'], stats['ram']
                    if cpu > CPU_THRESHOLD or ram > RAM_THRESHOLD:
                        logger.warning(f"Node {node['name']} exceeded threshold.")
            time.sleep(60)
        except Exception as e:
            logger.error(f"Error in resource monitor: {e}")
            time.sleep(60)

monitor_thread = threading.Thread(target=resource_monitor, daemon=True)
monitor_thread.start()

async def get_container_stats(container_name: str, node_id: Optional[int] = None) -> Dict:
    backend = find_backend_for_container(container_name)
    if node_id is None:
        node_id = find_node_id_for_container(container_name)
    node = get_node(node_id)
    if node['is_local']:
        if backend == 'docker':
            status = await get_docker_status_local(container_name)
            return {"status": status, "cpu": 0.0, "ram": {"used": 0, "total": 0, "pct": 0.0}, "disk": "Docker Managed", "uptime": "Up"}
        else:
            status = await get_container_status_local(container_name)
            cpu = await get_container_cpu_pct_local(container_name)
            ram = await get_container_ram_local(container_name)
            disk = await get_container_disk_local(container_name)
            uptime = await get_container_uptime_local(container_name)
            return {"status": status, "cpu": cpu, "ram": ram, "disk": disk, "uptime": uptime}
    return {"status": "unknown", "cpu": 0.0, "ram": {"used": 0, "total": 0, "pct": 0.0}, "disk": "Unknown", "uptime": "Unknown"}

async def get_docker_status_local(container_name: str):
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "inspect", "-f", "{{.State.Status}}", container_name,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return stdout.decode().strip().lower()
    except Exception:
        return "unknown"

async def get_container_status_local(container_name: str):
    try:
        proc = await asyncio.create_subprocess_exec(
            "lxc", "info", container_name,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        for line in stdout.decode().splitlines():
            if line.startswith("Status: "):
                return line.split(": ", 1)[1].strip().lower()
        return "unknown"
    except Exception:
        return "unknown"

async def get_container_cpu_pct_local(container_name: str):
    try:
        proc = await asyncio.create_subprocess_exec(
            "lxc", "exec", container_name, "--", "top", "-bn1",
          stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        for line in stdout.decode().splitlines():
            if '%Cpu(s):' in line:
                cpu_data = line.split('%Cpu(s):')[1].strip()
                parts = [float(item.split()[0].strip()) for item in cpu_data.split(',') if item.split()[0].strip().replace('.','',1).isdigit()]
                if len(parts) >= 8:
                    return sum(parts[:3]) + sum(parts[4:])
        return 0.0
    except Exception:
        return 0.0

async def get_container_ram_local(container_name: str):
    try:
        proc = await asyncio.create_subprocess_exec(
            "lxc", "exec", container_name, "--", "free", "-m",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        lines = stdout.decode().splitlines()
        if len(lines) > 1:
            parts = lines[1].split()
            total, used = int(parts[1]), int(parts[2])
            return {'used': used, 'total': total, 'pct': (used / total * 100) if total > 0 else 0.0}
        return {'used': 0, 'total': 0, 'pct': 0.0}
    except Exception:
        return {'used': 0, 'total': 0, 'pct': 0.0}

async def get_container_disk_local(container_name: str):
    try:
        proc = await asyncio.create_subprocess_exec(
            "lxc", "exec", container_name, "--", "df", "-h", "/",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        lines = stdout.decode().splitlines()
        for line in lines:
            if '/dev/' in line and ' /' in line:
                parts = line.split()
                if len(parts) >= 5:
                    return f"{parts[2]}/{parts[1]} ({parts[4]})"
        return "Unknown"
    except Exception:
        return "Unknown"

async def get_container_uptime_local(container_name: str):
    try:
        proc = await asyncio.create_subprocess_exec(
            "lxc", "exec", container_name, "--", "uptime",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return stdout.decode().strip() if stdout else "Unknown"
    except Exception:
        return "Unknown"

async def get_container_networks(container_name: str, node_id: Optional[int] = None) -> Dict[str, str]:
    backend = find_backend_for_container(container_name)
    try:
        if node_id is None:
            node_id = find_node_id_for_container(container_name)
        if backend == 'docker':
            proc = await asyncio.create_subprocess_exec(
                "docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", container_name,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            ip = stdout.decode().strip()
            return {"eth0": ip} if ip else {}
        else:
            proc = await asyncio.create_subprocess_exec(
                "lxc", "exec", container_name, "--", "ip", "addr", "show",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            networks = {}
            if proc.returncode == 0:
                current_interface = None
                for line in stdout.decode().strip().split('\n'):
                    if line and line[0].isdigit():
                        parts = line.split(':')
                        if len(parts) >= 2:
                            current_interface = parts[1].strip()
                    elif 'inet ' in line and current_interface:
                        parts = line.strip().split()
                        if len(parts) >= 2 and parts[0] == 'inet':
                            ip = parts[1].split('/')[0]
                            if ip != "127.0.0.1" and current_interface != "lo":
                                networks[current_interface] = ip
            return networks
    except Exception as e:
        logger.error(f"Error networks: {e}")
        return {}

def get_uptime():
    try:
        import platform
        if platform.system() == "Windows":
            return "Windows Host"
        else:
            result = subprocess.run(['uptime'], capture_output=True, text=True, timeout=5)
            return result.stdout.strip()
    except Exception:
        return "Unknown"

DEFAULT_STORAGE_POOL = os.getenv('DEFAULT_STORAGE_POOL', 'default')

@bot.event
async def on_ready():
    logger.info(f'{bot.user} online! Running Dual Backend Engine.')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f"{BOT_NAME} VPS Manager"))
    if not bot.loop.is_running():
        bot.loop.create_task(auto_save_task())

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=create_error_embed("Missing Argument", f"Usage: `{PREFIX}help`"))
    elif isinstance(error, commands.BadArgument):
        await ctx.send(embed=create_error_embed("Invalid Argument", "Check input parameters."))
    elif isinstance(error, commands.CheckFailure):
        await ctx.send(embed=create_error_embed("Access Denied", str(error)))
      else:
          logger.error(f"Error: {error}")
          await ctx.send(embed=create_error_embed("System Error", "An internal error occurred."))

@bot.command(name='ping')
async def ping(ctx):
    latency = round(bot.latency * 1000)
    embed = create_success_embed("🏓 Pong!", "Bot responding smoothly.")
    add_field(embed, "Latency", f"`{latency}ms`", inline=True)
    add_field(embed, "Engine", "LXC + Docker Native Dual Engine", inline=True)
    await ctx.send(embed=embed)

@bot.command(name='uptime')
async def uptime(ctx):
    embed = create_info_embed("Host Uptime", get_uptime())
    await ctx.send(embed=embed)

@bot.command(name='thresholds')
@is_admin()
async def thresholds(ctx):
    embed = create_info_embed("Resource Thresholds", f"**CPU:** {CPU_THRESHOLD}%\n**RAM:** {RAM_THRESHOLD}%")
    await ctx.send(embed=embed)

@bot.command(name='set-threshold')
@is_admin()
async def set_threshold(ctx, cpu: int, ram: int):
    global CPU_THRESHOLD, RAM_THRESHOLD
    CPU_THRESHOLD, RAM_THRESHOLD = cpu, ram
    set_setting('cpu_threshold', str(cpu))
    set_setting('ram_threshold', str(ram))
    await ctx.send(embed=create_success_embed("Thresholds Updated", f"CPU: {cpu}% | RAM: {ram}%"))

@bot.command(name='set-status')
@is_admin()
async def set_status(ctx, activity_type: str, *, name: str):
    types = {'playing': discord.ActivityType.playing, 'watching': discord.ActivityType.watching, 'listening': discord.ActivityType.listening}
    if activity_type.lower() in types:
        await bot.change_presence(activity=discord.Activity(type=types[activity_type.lower()], name=name))
        await ctx.send(embed=create_success_embed("Status Updated", f"Set to {activity_type}: {name}"))

@bot.command(name="myvps")
async def my_vps(ctx):
    user_id = str(ctx.author.id)
    vps_list = vps_data.get(user_id, [])

    if not vps_list:
        embed = create_error_embed("❌ No VPS Found", f"You don’t have any **{BOT_NAME} VPS** yet.")
        await ctx.send(embed=embed)
        return

    embed = create_info_embed(title="🖥️ My VPS Dashboard", description="Your active server instances")
    vps_cards = []

    for i, vps in enumerate(vps_list, start=1):
        node = get_node(vps.get("node_id"))
        node_name = node["name"] if node else "Unknown"
        backend = vps.get("backend_type", "lxc").upper()

        status = "⛔ SUSPENDED" if vps.get("suspended") else ("🟢 RUNNING" if vps.get("status") == "running" else "🔴 STOPPED")
        
        card = (
            f"**{i}.** `{vps['container_name']}` ({backend})\n"
            f"{status} • `{vps.get('config', 'Custom')}`\n"
            f"⚙️ `{vps.get('ram')}` RAM • `{vps.get('cpu')}` CPU • `{vps.get('storage')}` Disk\n"
            f"📍 Node: `{node_name}`"
        )
        vps_cards.append(card)

    vps_text = "\n\n".join(vps_cards)
    for i in range(0, len(vps_text), 1024):
        embed.add_field(name="🖥️ Active Nodes", value=vps_text[i:i + 1024], inline=False)

    await ctx.send(embed=embed)

@bot.command(name='lxc-list')
@is_admin()
async def lxc_list(ctx, node_id: int = 1):
    try:
        result = await execute_lxc("", "list", node_id=node_id)
        embed = create_info_embed(f"LXC List - Node {node_id}", f"```\n{result}\n```")
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(embed=create_error_embed("Error", str(e)))

@bot.command(name='docker-list')
@is_admin()
async def docker_list(ctx, node_id: int = 1):
    try:
        result = await execute_docker("", "ps -a", node_id=node_id)
        embed = create_info_embed(f"Docker List - Node {node_id}", f"```\n{result}\n```")
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(embed=create_error_embed("Error", str(e)))

# Selection Flow Views
class BackendSelectView(discord.ui.View):
    def __init__(self, ram: int, cpu: int, disk: int, user: discord.Member, ctx, expiry_days: int = None):
        super().__init__(timeout=300)
        self.ram = ram
        self.cpu = cpu
        self.disk = disk
        self.user = user
        self.ctx = ctx
        self.expiry_days = expiry_days or DEFAULT_VPS_EXPIRATION_DAYS

    @discord.ui.button(label="LXC Container", style=discord.ButtonStyle.primary, emoji="⚡")
    async def select_lxc(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = NodeSelectView(self.ram, self.cpu, self.disk, self.user, self.ctx, self.expiry_days, backend="lxc")
        await interaction.response.edit_message(embed=create_info_embed("Select Node", "Select target deployment node for LXC:"), view=view)

    @discord.ui.button(label="Docker Container", style=discord.ButtonStyle.success, emoji="🐳")
    async def select_docker(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = NodeSelectView(self.ram, self.cpu, self.disk, self.user, self.ctx, self.expiry_days, backend="docker")
        await interaction.response.edit_message(embed=create_info_embed("Select Node", "Select target deployment node for Docker:"), view=view)

class NodeSelectView(discord.ui.View):
    def __init__(self, ram: int, cpu: int, disk: int, user: discord.Member, ctx, expiry_days: int, backend: str):
        super().__init__(timeout=300)
        self.ram, self.cpu, self.disk, self.user, self.ctx = ram, cpu, disk, user, ctx
        self.expiry_days, self.backend = expiry_days, backend
        
        options = []
        for n in get_nodes():
            if get_current_vps_count(n['id']) < n['total_vps']:
                options.append(discord.SelectOption(label=n['name'], value=str(n['id']), description=f"Location: {n['location']}"))
        if options:
            self.select = discord.ui.Select(placeholder="Choose target node", options=options)
            self.select.callback = self.select_node
            self.add_item(self.select)

    async def select_node(self, interaction: discord.Interaction):
        node_id = int(self.select.values[0])
        os_view = OSSelectView(self.ram, self.cpu, self.disk, self.user, self.ctx, node_id, self.expiry_days, self.backend)
        await interaction.response.edit_message(embed=create_info_embed("Select OS Image", "Choose Operating System:"), view=os_view)

class OSSelectView(discord.ui.View):
    def __init__(self, ram: int, cpu: int, disk: int, user: discord.Member, ctx, node_id: int, expiry_days: int, backend: str):
        super().__init__(timeout=300)
        self.ram, self.cpu, self.disk, self.user, self.ctx = ram, cpu, disk, user, ctx
        self.node_id, self.expiry_days, self.backend = node_id, expiry_days, backend
        
        opts = [discord.SelectOption(label=o["label"], value=o["value"]) for o in OS_OPTIONS]
        if backend == 'docker':
            opts = [
                discord.SelectOption(label="Ubuntu 22.04 Docker", value="ubuntu:22.04"),
                discord.SelectOption(label="Debian 12 Docker", value="debian:12"),
                discord.SelectOption(label="Alpine Linux", value="alpine:latest")
            ]
        self.select = discord.ui.Select(placeholder="Select OS distribution", options=opts)
        self.select.callback = self.select_os
        self.add_item(self.select)

    async def select_os(self, interaction: discord.Interaction):
        os_version = self.select.values[0]
        await interaction.response.edit_message(embed=create_info_embed("Provisioning Engine", f"Building `{self.backend.upper()}` instance..."), view=None)

        user_id = str(self.user.id)
        sanitized_username = sanitize_username_for_container(self.user.name.lower())
        
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT MAX(id) FROM vps")
        global_vps_id = (cur.fetchone()[0] or 0) + 1
        conn.close()
        
        container_name = f"{sanitized_username}-{self.backend}-{global_vps_id}"
        root_password = generate_strong_password()
        
        try:
            if self.backend == 'docker':
                # Docker provisioning pipeline
                docker_cmd = f"run -d --name {container_name} --memory={self.ram}g --cpus={self.cpu} --privileged {os_version} tail -f /dev/null"
                await execute_docker(container_name, docker_cmd, node_id=self.node_id)
                # Ensure SSH installed inside Docker base image
                await execute_docker(container_name, f"exec {container_name} bash -c 'apt-get update && apt-get install -y openssh-server' || true", node_id=self.node_id)
            else:
                # LXC provisioning pipeline
                ram_mb = self.ram * 1024
                await execute_lxc(container_name, f"init {os_version} {container_name} -s {DEFAULT_STORAGE_POOL}", node_id=self.node_id)
                await execute_lxc(container_name, f"config set {container_name} limits.memory {ram_mb}MB", node_id=self.node_id)
                await execute_lxc(container_name, f"config set {container_name} limits.cpu {self.cpu}", node_id=self.node_id)
                await execute_lxc(container_name, f"config device set {container_name} root size={self.disk}GB", node_id=self.node_id)
                await apply_lxc_config(container_name, self.node_id)
                await execute_lxc(container_name, f"start {container_name}", node_id=self.node_id)
                await apply_internal_permissions(container_name, self.node_id)

            await configure_ssh(container_name, self.node_id, root_password, backend=self.backend)

            vps_info = {
                "container_name": container_name,
                "node_id": self.node_id,
                "ram": f"{self.ram}GB",
                "cpu": str(self.cpu),
                "storage": f"{self.disk}GB",
                "config": f"{self.ram}GB RAM / {self.cpu} CPU",
                "os_version": os_version,
                "status": "running",
                "suspended": False,
                "whitelisted": False,
                "suspension_history": [],
                "created_at": datetime.now().isoformat(),
                "shared_with": [],
                "expiration_date": (datetime.now() + timedelta(days=self.expiry_days)).isoformat(),
                "root_password": root_password,
                "backend_type": self.backend,
                "id": global_vps_id
            }
            if user_id not in vps_data:
                vps_data[user_id] = []
            vps_data[user_id].append(vps_info)
            save_vps_data_immediate()

            success_embed = create_success_embed("Instance Deployed Successfully")
            add_field(success_embed, "Instance Name", f"`{container_name}`", True)
            add_field(success_embed, "Engine", self.backend.upper(), True)
            add_field(success_embed, "Root Password", f"`{root_password}`", False)
            await self.ctx.send(embed=success_embed)

        except Exception as e:
            await self.ctx.send(embed=create_error_embed("Deployment Failed", str(e)))

@bot.command(name='create')
@is_admin()
async def create_vps(ctx, ram: int, cpu: int, disk: int, user: discord.Member, expiry_days: int = None):
    embed = create_info_embed("Deployment Engine", f"Configuring node specifications for {user.mention}.\nChoose deployment backend engine below:")
    view = BackendSelectView(ram, cpu, disk, user, ctx, expiry_days)
    await ctx.send(embed=embed, view=view)

# Additional Management Commands
@bot.command(name='docker-cmd')
@is_admin()
async def docker_cmd(ctx, container_name: str, *, command: str):
    try:
        res = await execute_docker(container_name, f"exec {container_name} {command}")
        await ctx.send(embed=create_info_embed("Docker Exec", f"```\n{res}\n```"))
    except Exception as e:
        await ctx.send(embed=create_error_embed("Docker Exec Failed", str(e)))

@bot.command(name='lxc-cmd')
@is_admin()
async def lxc_cmd(ctx, container_name: str, *, command: str):
    try:
        res = await execute_lxc(container_name, f"exec {container_name} -- {command}")
        await ctx.send(embed=create_info_embed("LXC Exec", f"```\n{res}\n```"))
    except Exception as e:
        await ctx.send(embed=create_error_embed("LXC Exec Failed", str(e)))

@bot.command(name='delete')
@is_admin()
async def delete_vps(ctx, container_name: str):
    backend = find_backend_for_container(container_name)
    node_id = find_node_id_for_container(container_name)
    try:
        if backend == 'docker':
            await execute_docker(container_name, f"rm -f {container_name}", node_id=node_id)
        else:
            await execute_lxc(container_name, f"delete {container_name} --force", node_id=node_id)
            
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM vps WHERE container_name = ?", (container_name,))
        conn.commit()
        conn.close()
        
        # Remove from runtime memory
        for uid in vps_data:
            vps_data[uid] = [v for v in vps_data[uid] if v['container_name'] != container_name]
        save_vps_data_immediate()
        
        await ctx.send(embed=create_success_embed("Deleted Successfully", f"Container `{container_name}` has been completely purged."))
    except Exception as e:
        await ctx.send(embed=create_error_embed("Deletion Error", str(e)))

@bot.command(name='stop')
async def stop_vps_cmd(ctx, container_name: str):
    backend = find_backend_for_container(container_name)
    node_id = find_node_id_for_container(container_name)
    try:
        await execute_backend(container_name, f"stop {container_name}", node_id=node_id, backend=backend)
        for uid in vps_data:
            for v in vps_data[uid]:
                if v['container_name'] == container_name:
                    v['status'] = 'stopped'
        save_vps_data_immediate()
        await ctx.send(embed=create_success_embed("Stopped", f"Container `{container_name}` stopped successfully."))
    except Exception as e:
        await ctx.send(embed=create_error_embed("Error", str(e)))

@bot.command(name='start')
async def start_vps_cmd(ctx, container_name: str):
    backend = find_backend_for_container(container_name)
    node_id = find_node_id_for_container(container_name)
    try:
        await execute_backend(container_name, f"start {container_name}", node_id=node_id, backend=backend)
        for uid in vps_data:
            for v in vps_data[uid]:
                if v['container_name'] == container_name:
                    v['status'] = 'running'
        save_vps_data_immediate()
        await ctx.send(embed=create_success_embed("Started", f"Container `{container_name}` started successfully."))
    except Exception as e:
        await ctx.send(embed=create_error_embed("Error", str(e)))

@bot.command(name='restart')
async def restart_vps_cmd(ctx, container_name: str):
    backend = find_backend_for_container(container_name)
    node_id = find_node_id_for_container(container_name)
    try:
        await execute_backend(container_name, f"restart {container_name}", node_id=node_id, backend=backend)
        await ctx.send(embed=create_success_embed("Restarted", f"Container `{container_name}` restarted successfully."))
    except Exception as e:
        await ctx.send(embed=create_error_embed("Error", str(e)))

# Start Bot Instance
if __name__ == '__main__':
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        logger.error("No DISCORD_TOKEN specified in environment or .env variables.")
