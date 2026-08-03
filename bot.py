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
HOST_MOTD = os.getenv('HOST_MOTD', 'bash <(curl -fsSL https://raw.githubusercontent.com/hopingboyz/linux/main/atyro-water-mark.sh)')
BOT_VERSION = os.getenv('BOT_VERSION', '7.0-PRO')
BOT_DEVELOPER = os.getenv('BOT_DEVELOPER', 'Hopingboz')
BOT_THUMBNAIL_URL = os.getenv('BOT_THUMBNAIL_URL', 'https://i.imgur.com/Tv3clt0.jpeg')
BOT_ICON_URL = os.getenv('BOT_ICON_URL', 'https://i.imgur.com/Tv3clt0.jpeg')

# VPS Expiration Settings
DEFAULT_VPS_EXPIRATION_DAYS = int(os.getenv('DEFAULT_VPS_EXPIRATION_DAYS', '30'))
EXPIRATION_WARNING_DAYS = int(os.getenv('EXPIRATION_WARNING_DAYS', '1'))

# OS Options for VPS Creation and Reinstall (Docker Images)
OS_OPTIONS = [
    {"label": "Ubuntu 20.04 LTS", "value": "ubuntu:20.04"},
    {"label": "Ubuntu 22.04 LTS", "value": "ubuntu:22.04"},
    {"label": "Ubuntu 24.04 LTS", "value": "ubuntu:24.04"},
    {"label": "Debian 10 (Buster)", "value": "debian:10"},
    {"label": "Debian 11 (Bullseye)", "value": "debian:11"},
    {"label": "Debian 12 (Bookworm)", "value": "debian:12"},
    {"label": "Debian 13 (Trixie)", "value": "debian:testing"},
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
        root_password TEXT DEFAULT NULL
    )''')
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
            if 'id' not in vps or vps['id'] is None:
                cur.execute('''INSERT INTO vps (user_id, node_id, container_name, ram, cpu, storage, config, os_version, status, suspended, whitelisted, created_at, shared_with, suspension_history, expiration_date, root_password)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                            (user_id, node_id, vps['container_name'], vps['ram'], vps['cpu'], vps['storage'], vps['config'],
                             os_ver, vps['status'], suspended_int, whitelisted_int,
                             created_at, shared_json, history_json, expiration_date, root_password))
                vps['id'] = cur.lastrowid
            else:
                cur.execute('''UPDATE vps SET user_id = ?, node_id = ?, container_name = ?, ram = ?, cpu = ?, storage = ?, config = ?, os_version = ?, status = ?, suspended = ?, whitelisted = ?, shared_with = ?, suspension_history = ?, expiration_date = ?, root_password = ?
                               WHERE id = ?''',
                            (user_id, node_id, vps['container_name'], vps['ram'], vps['cpu'], vps['storage'], vps['config'],
                             os_ver, vps['status'], suspended_int, whitelisted_int, shared_json, history_json, expiration_date, root_password, vps['id']))
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
    try:
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
    return 0

def find_node_id_for_container(container_name: str) -> int:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT node_id FROM vps WHERE container_name = ?', (container_name,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 1

init_db()

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

CPU_THRESHOLD = int(get_setting('cpu_threshold', 90))
RAM_THRESHOLD = int(get_setting('ram_threshold', 90))

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

resource_monitor_active = True

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

# Exact SSH setup logic adapted for Docker Engine
async def configure_ssh(container_name, node_id, password):
    try:
        # Install OpenSSH server inside Docker container
        setup_deps_cmd = "apt-get update && apt-get install -y openssh-server sudo bash"
        await execute_docker(container_name, f"exec -u 0 {container_name} bash -c \"{setup_deps_cmd}\"", node_id=node_id)

        # SSH Configuration matching provided specification
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
        
        await execute_docker(container_name, 
            f'exec -u 0 {container_name} bash -c "mkdir -p /run/sshd && echo -e \\"{config_cmd}\\" > /etc/ssh/sshd_config"',
            node_id=node_id)
        logger.info(f"SSH config file written on {container_name}")
        
        restart_cmd = "service ssh restart 2>/dev/null || /etc/init.d/ssh restart 2>/dev/null || /usr/sbin/sshd &"
        await execute_docker(container_name,
            f'exec -u 0 {container_name} bash -c "{restart_cmd}"',
            node_id=node_id)
        logger.info(f"SSH service restarted on {container_name}")
        
        await execute_docker(container_name,
            f"exec -u 0 {container_name} bash -c \"echo 'root:{password}' | chpasswd\"",
            node_id=node_id)
        logger.info(f"Root password set for {container_name}")
        
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

def create_vps_card(vps, index):
    node = get_node(vps.get('node_id', 1))
    status_emoji = "🟢" if (vps.get('status') == 'running' and not vps.get('suspended')) else "🟡" if vps.get('suspended') else "🔴"
    node_emoji = "📍" if (node and node.get('is_local')) else "🌐"
    
    card = (
        f"**#{index}** `{vps['container_name']}`\n"
        f"{status_emoji} {vps.get('status', 'unknown').upper()}"
    )
    if vps.get('suspended'):
        card += " (SUSPENDED)"
    
    card += (
        f"\n⚙️ **Config:** {vps.get('config', 'Custom')}\n"
        f"💾 **RAM:** {vps['ram']} | **CPU:** {vps['cpu']} | **Disk:** {vps['storage']}\n"
        f"{node_emoji} **Node:** {node['name'] if node else 'Unknown'}\n"
        f"⏰ **Expiration:** {format_expiration(vps)}"
    )
    return card

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

# Docker Command Execution replacing LXC
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
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise asyncio.TimeoutError(f"Command timed out after {timeout} seconds")
            
            if proc.returncode != 0:
                error = stderr.decode().strip() if stderr else "Command failed with no error output"
                raise Exception(f"Local Docker command failed: {error}\nCommand: {full_command}")
            return stdout.decode().strip() if stdout else True
        except asyncio.TimeoutError as te:
            logger.error(f"Docker command timed out: {full_command} - {str(te)}")
            raise
        except Exception as e:
            logger.error(f"Docker Error: {full_command} - {str(e)}")
            raise
    else:
        url = f"{node['url']}/api/execute"
        data = {"command": full_command}
        params = {"api_key": node["api_key"]}
        try:
            response = requests.post(url, json=data, params=params, timeout=timeout)
            
            if response.status_code != 200:
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_detail = response.json()
                    if 'detail' in error_detail:
                        error_msg = error_detail['detail']
                    elif 'error' in error_detail:
                        error_msg = error_detail['error']
                    elif 'stderr' in error_detail:
                        error_msg = error_detail['stderr']
                except:
                    pass
                raise Exception(f"Remote execution failed on {node['name']}: {error_msg}\nCommand: {full_command}")
            
            res = response.json()
            if res.get("returncode", 1) != 0:
                stderr = res.get("stderr", "Command failed")
                logger.warning(f"Remote command failed on node {node['name']}: {stderr}")
                raise Exception(f"Remote Docker command failed on {node['name']}: {stderr}\nCommand: {full_command}")
            
            return res.get("stdout", True)
            
        except requests.exceptions.ConnectionError:
            logger.debug(f"Node {node['name']} unreachable at {node['url']} - network connection failed")
            raise Exception(f"Node {node['name']} is unreachable (network error). The remote node may be offline.")
        except requests.exceptions.Timeout:
            logger.warning(f"Remote execution timed out on node {node['name']}")
            raise Exception(f"Remote execution timed out on {node['name']} (timeout after {timeout}s)")
        except requests.exceptions.RequestException as e:
            logger.warning(f"Remote execution error on node {node['name']}: {str(e)}")
            raise Exception(f"Remote execution failed on {node['name']}: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error executing command on node {node['name']}: {str(e)}")
            raise

async def apply_internal_permissions(container_name: str, node_id: int):
    try:
        await asyncio.sleep(2)
        commands = [
            "mkdir -p /etc/sysctl.d/",
            "echo 'net.ipv4.ip_unprivileged_port_start=0' > /etc/sysctl.d/99-custom.conf",
            "sysctl -p /etc/sysctl.d/99-custom.conf || true"
        ]
        for cmd in commands:
            try:
                await execute_docker(container_name, f"exec -u 0 {container_name} bash -c \"{cmd}\"", node_id=node_id)
            except Exception as cmd_error:
                logger.warning(f"Command failed in {container_name}: {cmd} - {cmd_error}")
        logger.info(f"Internal permissions applied to {container_name}")
    except Exception as e:
        logger.error(f"Failed to apply internal permissions to {container_name}: {e}")

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
        logger.info(f"Created VPS role: {role.id}")
        return role
    except Exception as e:
        logger.error(f"Failed to create VPS role: {e}")
        return None

def get_host_cpu_usage():
    try:
        import platform
        system = platform.system()
        
        if system == "Windows":
            try:
                import psutil
                return psutil.cpu_percent(interval=1)
            except ImportError:
                return 0.0
        else:
            if shutil.which("mpstat"):
                result = subprocess.run(['mpstat', '1', '1'], capture_output=True, text=True, timeout=10)
                output = result.stdout
                for line in output.split('\n'):
                    if 'all' in line and '%' in line:
                        parts = line.split()
                        idle = float(parts[-1])
                        return 100.0 - idle
            else:
                result = subprocess.run(['top', '-bn1'], capture_output=True, text=True, timeout=10)
                output = result.stdout
                for line in output.split('\n'):
                    if '%Cpu(s):' in line:
                        cpu_data = line.split('%Cpu(s):')[1].strip()
                        parts = []
                        for item in cpu_data.split(','):
                            val = item.split()[0].strip()
                            try:
                                parts.append(float(val))
                            except ValueError:
                                parts.append(0.0)
                        
                        if len(parts) >= 8:
                            return parts[0] + parts[1] + parts[2] + parts[4] + parts[5] + parts[6] + parts[7]
            return 0.0
    except Exception as e:
        logger.debug(f"Error getting CPU usage: {e}")
        return 0.0

def get_host_ram_usage():
    try:
        import platform
        system = platform.system()
        
        if system == "Windows":
            try:
                import psutil
                mem = psutil.virtual_memory()
                return mem.percent
            except ImportError:
                return 0.0
        else:
            result = subprocess.run(['free', '-m'], capture_output=True, text=True, timeout=10)
            lines = result.stdout.splitlines()
            if len(lines) > 1:
                mem = lines[1].split()
                total = int(mem[1])
                used = int(mem[2])
                return (used / total * 100) if total > 0 else 0.0
            return 0.0
    except Exception as e:
        logger.debug(f"Error getting RAM usage: {e}")
        return 0.0

def get_host_disk_usage():
    try:
        import shutil
        total, used, free = shutil.disk_usage("/")
        return f"{(used/total)*100:.1f}%"
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
        except requests.exceptions.ConnectionError:
            logger.debug(f"Remote node {node['name']} unreachable - returning default stats")
            return {"cpu": 0.0, "ram": 0.0, "disk": "Unknown"}
        except Exception as e:
            logger.debug(f"Failed to get stats from remote node {node['name']}: {e}")
            return {"cpu": 0.0, "ram": 0.0, "disk": "Unknown"}

def check_vps_expiration():
    global bot
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
                    
                    if days_remaining < 0:
                        if not vps.get('suspended', False):
                            try:
                                asyncio.run(execute_docker(container_name, f"stop {container_name}", node_id=node_id))
                                vps['status'] = 'stopped'
                                vps['suspended'] = True
                                vps['suspension_history'].append({
                                    'time': datetime.now().isoformat(),
                                    'reason': f'Auto-suspended due to VPS expiration on {expiration_dt.strftime("%Y-%m-%d")}',
                                    'by': 'Expiration Monitor'
                                })
                                save_vps_data_immediate()
                                logger.warning(f"VPS {container_name} auto-suspended due to expiration")
                                
                                try:
                                    owner = asyncio.run(bot.fetch_user(int(user_id)))
                                    dm_embed = create_error_embed("🔴 VPS Expired and Suspended",
                                        f"Your VPS `{container_name}` has expired and been suspended.\n\n"
                                        f"**Expiration Date:** {expiration_dt.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                                        f"Contact an admin to renew your VPS.")
                                    asyncio.run(owner.send(embed=dm_embed))
                                except Exception as e:
                                    logger.debug(f"Failed to notify user {user_id}: {e}")
                            except Exception as e:
                                logger.error(f"Failed to auto-suspend VPS {container_name}: {e}")
                    
                    elif 0 < hours_remaining <= (EXPIRATION_WARNING_DAYS * 24):
                        if user_id not in warned_users:
                            try:
                                owner = asyncio.run(bot.fetch_user(int(user_id)))
                                dm_embed = create_warning_embed("⏰ VPS Expiring Soon",
                                    f"Your VPS `{container_name}` will expire in {days_remaining} day(s)!\n\n"
                                    f"**Expiration Date:** {expiration_dt.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                                    f"Contact an admin to renew your VPS before it's automatically suspended.")
                                asyncio.run(owner.send(embed=dm_embed))
                                warned_users.add(user_id)
                                logger.info(f"Sent expiration warning to user {user_id}")
                            except Exception as e:
                                logger.debug(f"Failed to notify user {user_id}: {e}")
    except Exception as e:
        logger.error(f"Error in VPS expiration check: {e}")

def resource_monitor():
    global resource_monitor_active
    last_expiration_check = time.time()
    expiration_check_interval = 3600
    
    while resource_monitor_active:
        try:
            if time.time() - last_expiration_check > expiration_check_interval:
                check_vps_expiration()
                last_expiration_check = time.time()
            
            nodes = get_nodes()
            for node in nodes:
                if node['is_local']:
                    stats = asyncio.run(get_host_stats(node['id']))
                    cpu = stats['cpu']
                    ram = stats['ram']
                    logger.info(f"Node {node['name']}: CPU {cpu:.1f}%, RAM {ram:.1f}%")
                    if cpu > CPU_THRESHOLD or ram > RAM_THRESHOLD:
                        logger.warning(f"Node {node['name']} exceeded thresholds (CPU: {CPU_THRESHOLD}%, RAM: {RAM_THRESHOLD}%). Manual intervention required.")
                else:
                    logger.debug(f"Skipping remote node {node['name']} - remote nodes monitored on-demand only")
            
            time.sleep(60)
        except Exception as e:
            logger.error(f"Error in resource monitor: {e}")
            time.sleep(60)

monitor_thread = threading.Thread(target=resource_monitor, daemon=True)
monitor_thread.start()

async def get_container_stats(container_name: str, node_id: Optional[int] = None) -> Dict:
    if node_id is None:
        node_id = find_node_id_for_container(container_name)
    node = get_node(node_id)
    if node['is_local']:
        status = await get_container_status_local(container_name)
        cpu = await get_container_cpu_pct_local(container_name)
        ram = await get_container_ram_local(container_name)
        disk = await get_container_disk_local(container_name)
        uptime = await get_container_uptime_local(container_name)
        return {"status": status, "cpu": cpu, "ram": ram, "disk": disk, "uptime": uptime}
    else:
        url = f"{node['url']}/api/get_container_stats"
        data = {"container": container_name}
        params = {"api_key": node["api_key"]}
        try:
            response = requests.post(url, json=data, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError:
            logger.debug(f"Remote node {node['name']} unreachable for container {container_name}")
            return {"status": "unknown", "cpu": 0.0, "ram": {"used": 0, "total": 0, "pct": 0.0}, "disk": "Unknown", "uptime": "Unknown"}
        except Exception as e:
            logger.debug(f"Failed to get container stats from remote node {node['name']}: {e}")
            return {"status": "unknown", "cpu": 0.0, "ram": {"used": 0, "total": 0, "pct": 0.0}, "disk": "Unknown", "uptime": "Unknown"}

async def get_container_status_local(container_name: str):
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "inspect", "-f", "{{.State.Status}}", container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        status = stdout.decode().strip().lower()
        return "running" if status == "running" else "stopped"
    except Exception:
        return "unknown"

async def get_container_cpu_pct_local(container_name: str):
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "stats", "--no-stream", "--format", "{{.CPUPerc}}", container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        val = stdout.decode().strip().replace('%', '')
        return float(val) if val else 0.0
    except Exception as e:
        logger.error(f"Error getting container CPU for {container_name}: {e}")
        return 0.0

async def get_container_ram_local(container_name: str):
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", container_name, "free", "-m",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        lines = stdout.decode().splitlines()
        if len(lines) > 1:
            parts = lines[1].split()
            total = int(parts[1])
            used = int(parts[2])
            pct = (used / total * 100) if total > 0 else 0.0
            return {'used': used, 'total': total, 'pct': pct}
        return {'used': 0, 'total': 0, 'pct': 0.0}
    except Exception as e:
        logger.error(f"Error getting RAM for {container_name}: {e}")
        return {'used': 0, 'total': 0, 'pct': 0.0}

async def get_container_disk_local(container_name: str):
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", container_name, "df", "-h", "/",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        lines = stdout.decode().splitlines()
        for line in lines:
            if '/' in line:
                parts = line.split()
                if len(parts) >= 5:
                    used = parts[2]
                    size = parts[1]
                    perc = parts[4]
                    return f"{used}/{size} ({perc})"
        return "Unknown"
    except Exception:
        return "Unknown"

async def get_container_uptime_local(container_name: str):
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "inspect", "-f", "{{.State.StartedAt}}", container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return stdout.decode().strip() if stdout else "Unknown"
    except Exception:
        return "Unknown"

async def get_container_networks(container_name: str, node_id: Optional[int] = None) -> Dict[str, str]:
    try:
        if node_id is None:
            node_id = find_node_id_for_container(container_name)
        
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", container_name, "ip", "addr", "show",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        networks = {}
        
        if proc.returncode == 0:
            output = stdout.decode().strip()
            lines = output.split('\n')
            current_interface = None
            
            for line in lines:
                if line and line[0].isdigit():
                    parts = line.split(':')
                    if len(parts) >= 2:
                        current_interface = parts[1].strip()
                elif 'inet ' in line and current_interface:
                    parts = line.strip().split()
                    if len(parts) >= 2 and parts[0] == 'inet':
                        ip_with_cidr = parts[1]
                        ip = ip_with_cidr.split('/')[0]
                        if ip != "127.0.0.1" and current_interface != "lo":
                            networks[current_interface] = ip
        return networks
    except Exception as e:
        logger.error(f"Error getting networks for {container_name}: {e}")
        return {}

def get_uptime():
    try:
        import platform
        system = platform.system()
        
        if system == "Windows":
            try:
                result = subprocess.run(['net', 'statistics', 'server'], capture_output=True, text=True, timeout=5)
                output = result.stdout
                for line in output.split('\n'):
                    if 'Statistics since' in line:
                        return line.strip()
                return "Unknown"
            except:
                return "Unknown"
        else:
            result = subprocess.run(['uptime'], capture_output=True, text=True, timeout=5)
            return result.stdout.strip()
    except Exception as e:
        logger.debug(f"Error getting uptime: {e}")
        return "Unknown"
  
# Bot events
@bot.event
async def on_ready():
    logger.info(f'{bot.user} has connected to Discord!')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f"{BOT_NAME} VPS Manager"))
    logger.info(f"{BOT_NAME} Bot is ready!")
    if not bot.loop.is_running():
        bot.loop.create_task(auto_save_task())

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=create_error_embed("Missing Argument", f"Please check command usage with `{PREFIX}help`."))
    elif isinstance(error, commands.BadArgument):
        await ctx.send(embed=create_error_embed("Invalid Argument", "Please check your input and try again."))
    elif isinstance(error, commands.CheckFailure):
        error_msg = str(error) if str(error) else "You need admin permissions for this command. Contact support."
        await ctx.send(embed=create_error_embed("Access Denied", error_msg))
    elif isinstance(error, discord.NotFound):
        await ctx.send(embed=create_error_embed("Error", "The requested resource was not found. Please try again."))
    else:
        logger.error(f"Command error: {error}")
        await ctx.send(embed=create_error_embed("System Error", "An unexpected error occurred. Support has been notified."))

# Bot commands
@bot.command(name='ping')
async def ping(ctx):
    latency = round(bot.latency * 1000)
    embed = create_success_embed(
        "🏓 Pong!",
        f"Bot is responding perfectly!"
    )
    add_field(embed, "Latency", f"`{latency}ms`", inline=True)
    add_field(embed, "Status", "✅ Online", inline=True)
    add_field(embed, "Bot", f"`{BOT_NAME} v{BOT_VERSION}`", inline=True)
    await ctx.send(embed=embed)

@bot.command(name='uptime')
async def uptime(ctx):
    up = get_uptime()
    embed = create_info_embed("Host Uptime", up)
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
    if cpu < 0 or ram < 0:
        await ctx.send(embed=create_error_embed("Invalid Thresholds", "Thresholds must be non-negative."))
        return
    CPU_THRESHOLD = cpu
    RAM_THRESHOLD = ram
    set_setting('cpu_threshold', str(cpu))
    set_setting('ram_threshold', str(ram))
    embed = create_success_embed("Thresholds Updated", f"**CPU:** {cpu}%\n**RAM:** {ram}%")
    await ctx.send(embed=embed)

@bot.command(name='set-status')
@is_admin()
async def set_status(ctx, activity_type: str, *, name: str):
    types = {
        'playing': discord.ActivityType.playing,
        'watching': discord.ActivityType.watching,
        'listening': discord.ActivityType.listening,
        'streaming': discord.ActivityType.streaming,
    }
    if activity_type.lower() not in types:
        await ctx.send(embed=create_error_embed("Invalid Type", "Valid types: playing, watching, listening, streaming"))
        return
    await bot.change_presence(activity=discord.Activity(type=types[activity_type.lower()], name=name))
    embed = create_success_embed("Status Updated", f"Set to {activity_type}: {name}")
    await ctx.send(embed=embed)

@bot.command(name="myvps")
async def my_vps(ctx):
    user_id = str(ctx.author.id)
    vps_list = vps_data.get(user_id, [])

    if not vps_list:
        embed = create_error_embed(
            "❌ No VPS Found",
            f"You don’t have any **{BOT_NAME} VPS** yet."
        )
        embed.add_field(
            name="🚀 Quick Actions",
            value=(
                f"• `{PREFIX}manage` – Manage VPS\n"
                f"• Contact an admin to request a VPS"
            ),
            inline=False
        )
        await ctx.send(embed=embed)
        return

    embed = create_info_embed(
        title="🖥️ My VPS Dashboard",
        description="Your personal VPS overview"
    )

    total_vps = len(vps_list)
    running = suspended = whitelisted = 0
    vps_cards = []

    for i, vps in enumerate(vps_list, start=1):
        node = get_node(vps.get("node_id"))
        node_name = node["name"] if node else "Unknown"

        config = vps.get("config", "Custom")
        ram = vps.get("ram", "0GB")
        cpu = vps.get("cpu", "0")
        storage = vps.get("storage", "0GB")

        if vps.get("suspended"):
            status = "⛔ SUSPENDED"
            suspended += 1
        elif vps.get("status") == "running":
            status = "🟢 RUNNING"
            running += 1
        else:
            status = "🔴 STOPPED"

        if vps.get("whitelisted"):
            whitelisted += 1

        card = (
            f"**{i}.** `{vps['container_name']}`\n"
            f"{status} • `{config}`\n"
            f"⚙️ `{ram}` RAM • `{cpu}` CPU • `{storage}` Disk\n"
            f"📍 Node: `{node_name}`"
        )
        
        if vps.get('expiration_date'):
            expiration_dt = datetime.fromisoformat(vps['expiration_date'])
            days_remaining = (expiration_dt - datetime.now()).days
            
            if days_remaining < 0:
                expiration_badge = "🔴 EXPIRED"
            elif days_remaining <= EXPIRATION_WARNING_DAYS:
                expiration_badge = "🟡 EXPIRING"
            else:
                expiration_badge = "🟢 ACTIVE"
            
            card += f"\n⏰ {expiration_badge} • Expires: `{expiration_dt.strftime('%Y-%m-%d')}`"
        
        vps_cards.append(card)

    embed.add_field(
        name="📊 Summary",
        value=(
            f"🖥️ `{total_vps}` VPS\n"
            f"🟢 `{running}` Running\n"
            f"⛔ `{suspended}` Suspended\n"
            f"✅ `{whitelisted}` Whitelisted"
        ),
        inline=True
    )

    embed.add_field(
        name="⚡ Quick Actions",
        value=(
            f"`{PREFIX}manage`\n"
            f"`{PREFIX}reinstall`\n"
            f"`{PREFIX}status`"
        ),
        inline=True
    )

    embed.add_field(
        name="🧭 Tip",
        value="Use **manage** to control your VPS",
        inline=True
    )

    vps_text = "\n\n".join(vps_cards)
    for i in range(0, len(vps_text), 1024):
        embed.add_field(
            name="🖥️ Your VPS",
            value=vps_text[i:i + 1024],
            inline=False
        )

    embed.set_footer(text=f"Made by SKYDO • VPS Control Panel")
    embed.timestamp = ctx.message.created_at

    await ctx.send(embed=embed)

@bot.command(name='docker-list')
@is_admin()
async def docker_list(ctx, node_id: int = 1):
    try:
        result = await execute_docker("", "ps -a", node_id=node_id)
        node = get_node(node_id)
        embed = create_info_embed(f"Docker Containers List on {node['name']}", result)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(embed=create_error_embed("Error", str(e)))

class NodeSelectView(discord.ui.View):
    def __init__(self, ram: int, cpu: int, disk: int, user: discord.Member, ctx, expiry_days: int = None):
        super().__init__(timeout=300)
        self.ram = ram
        self.cpu = cpu
        self.disk = disk
        self.user = user
        self.ctx = ctx
        self.expiry_days = expiry_days if expiry_days and expiry_days > 0 else DEFAULT_VPS_EXPIRATION_DAYS
        nodes = get_nodes()
        options = []
        for n in nodes:
            current_count = get_current_vps_count(n['id'])
            if current_count < n['total_vps']:
                node_type = "📍 Local" if n['is_local'] else "🌐 Remote"
                options.append(discord.SelectOption(label=f"{n['name']} {node_type}", value=str(n['id']), description=f"{n['location']} - Available: {n['total_vps'] - current_count}"))
        if not options:
            self.add_item(discord.ui.Select(placeholder="No available nodes", disabled=True))
        else:
            self.select = discord.ui.Select(placeholder="Select a Node for the VPS", options=options)
            self.select.callback = self.select_node
            self.add_item(self.select)

    async def select_node(self, interaction: discord.Interaction):
        if str(interaction.user.id) != str(self.ctx.author.id):
            await interaction.response.send_message(embed=create_error_embed("Access Denied", "Only the command author can select."), ephemeral=True)
            return
        node_id = int(self.select.values[0])
        self.select.disabled = True
        await interaction.response.edit_message(view=self)
        os_view = OSSelectView(self.ram, self.cpu, self.disk, self.user, self.ctx, node_id, self.expiry_days)
        await interaction.followup.send(embed=create_info_embed("Select OS", "Choose the OS for the VPS."), view=os_view)

class OSSelectView(discord.ui.View):
    def __init__(self, ram: int, cpu: int, disk: int, user: discord.Member, ctx, node_id: int, expiry_days: int = None):
        super().__init__(timeout=300)
        self.ram = ram
        self.cpu = cpu
        self.disk = disk
        self.user = user
        self.ctx = ctx
        self.node_id = node_id
        self.expiry_days = expiry_days if expiry_days and expiry_days > 0 else DEFAULT_VPS_EXPIRATION_DAYS
        self.select = discord.ui.Select(
            placeholder="Select an OS for the VPS",
            options=[discord.SelectOption(label=o["label"], value=o["value"]) for o in OS_OPTIONS]
        )
        self.select.callback = self.select_os
        self.add_item(self.select)

    async def select_os(self, interaction: discord.Interaction):
        if str(interaction.user.id) != str(self.ctx.author.id):
            await interaction.response.send_message(embed=create_error_embed("Access Denied", "Only the command author can select."), ephemeral=True)
            return
        os_version = self.select.values[0]
        self.select.disabled = True
        creating_embed = create_info_embed("Creating VPS", f"Deploying {os_version} VPS for {self.user.mention} on node {self.node_id}...")
        
        # EPHEMERAL RESPONSE: Seen ONLY by the creator/admin running command
        await interaction.response.send_message(embed=creating_embed, ephemeral=True)
        
        user_id = str(self.user.id)
        username = self.user.name.lower().replace(" ", "-")[:15]
        
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT MAX(id) FROM vps")
        max_id = cur.fetchone()[0] or 0
        global_vps_id = max_id + 1
        conn.close()
        
        sanitized_username = sanitize_username_for_container(username)
        container_name = f"{sanitized_username}-vps-{global_vps_id}"
        ram_mb = self.ram * 1024
        try:
            # Create isolated Docker container with root privileges & systemd setup
            docker_cmd = (
                f"run -d --name {container_name} "
                f"--privileged "
                f"--memory={ram_mb}m "
                f"--cpus={self.cpu} "
                f"--restart=always "
                f"{os_version} /bin/bash"
            )
            await execute_docker(container_name, docker_cmd, node_id=self.node_id)
            await apply_internal_permissions(container_name, self.node_id)
            
            root_password = generate_strong_password()
            
            success, result = await configure_ssh(container_name, self.node_id, root_password)
            if not success:
                logger.warning(f"SSH configuration partially failed: {result}")
            
            if HOST_MOTD:
                try:
                    await execute_docker(container_name, f"exec -u 0 {container_name} bash -c \"{HOST_MOTD}\"", node_id=self.node_id)
                    logger.info(f"HOST_MOTD executed on {container_name}")
                except Exception as e:
                    logger.warning(f"HOST_MOTD execution failed for {container_name}: {e}")
            
            config_str = f"{self.ram}GB RAM / {self.cpu} CPU / {self.disk}GB Disk"
            vps_info = {
                "container_name": container_name,
                "node_id": self.node_id,
                "ram": f"{self.ram}GB",
                "cpu": str(self.cpu),
                "storage": f"{self.disk}GB",
                "config": config_str,
                "os_version": os_version,
                "status": "running",
                "suspended": False,
                "whitelisted": False,
                "suspension_history": [],
                "created_at": datetime.now().isoformat(),
                "shared_with": [],
                "expiration_date": (datetime.now() + timedelta(days=self.expiry_days)).isoformat(),
                "root_password": root_password,
                "id": global_vps_id
            }
            if user_id not in vps_data:
                vps_data[user_id] = []
            vps_data[user_id].append(vps_info)
            save_vps_data_immediate()
            if self.ctx.guild:
                vps_role = await get_or_create_vps_role(self.ctx.guild)
                if vps_role:
                    try:
                        await self.user.add_roles(vps_role, reason=f"{BOT_NAME} VPS ownership granted")
                    except discord.Forbidden:
                        logger.warning(f"Failed to assign VPS role to {self.user.name}")
            
            success_embed = create_success_embed("VPS Created Successfully")
            add_field(success_embed, "Owner", self.user.mention, True)
            add_field(success_embed, "VPS ID", f"#{global_vps_id}", True)
            add_field(success_embed, "Container", f"`{container_name}`", True)
            add_field(success_embed, "Node", get_node(self.node_id)['name'], True)
            add_field(success_embed, "Resources", f"**RAM:** {self.ram}GB\n**CPU:** {self.cpu} Cores\n**Storage:** {self.disk}GB", False)
            add_field(success_embed, "OS", os_version, True)
            add_field(success_embed, "SSH Configuration", "✅ Configured (PasswordAuth enabled)", True)
            add_field(success_embed, "SSH & Password", "✅ SSH configured for password authentication\n🔐 Root password generated and sent via DM\n📧 Check your DMs for SSH credentials!", False)
            add_field(success_embed, "Features", "Privileged Docker Container, Nesting, Systemd Support", False)
            
            # Send confirmation exclusively via ephemeral followup
            await interaction.followup.send(embed=success_embed, ephemeral=True)
            
            dm_embed = create_success_embed("🎉 VPS Created Successfully!", f"Your new VPS is ready to use!")
            vps_details = f"""
**VPS ID:** #{global_vps_id}
**Container:** `{container_name}`
**Configuration:** {config_str}
**Operating System:** {os_version}
**Status:** 🟢 Running
**Created:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Expiration:** {(datetime.now() + timedelta(days=self.expiry_days)).strftime('%Y-%m-%d %H:%M:%S')} ({self.expiry_days} days)
"""
            add_field(dm_embed, "📊 VPS Details", vps_details.strip(), False)
            
            try:
                networks = await asyncio.wait_for(
                    get_container_networks(container_name, self.node_id),
                    timeout=3.0
                )
            except asyncio.TimeoutError:
                logger.warning(f"Timeout getting networks for {container_name}")
                networks = {}
            
            if networks:
                ssh_access_info = "**🖥️ Available Connection Points:**\n"
                for interface, ip in sorted(networks.items()):
                    ssh_access_info += f"└─ **{interface}:** `ssh root@{ip}`\n"
                ssh_access_info += f"\n**🔑 Login Credentials:**\n"
                ssh_access_info += f"**Username:** `root`\n"
                ssh_access_info += f"**Password:** `{root_password}`\n"
                ssh_access_info += f"\n**⚠️ Important:** Save this password securely!"
            else:
                ssh_access_info = "**🔑 Login Credentials:**\n"
                ssh_access_info += f"**Username:** `root`\n"
                ssh_access_info += f"**Password:** `{root_password}`\n"
                ssh_access_info += f"\n**📡 Network Setup:**\n"
                ssh_access_info += "Your VPS is initializing its network interfaces.\n"
                ssh_access_info += "They will be available in a few seconds.\n"
                ssh_access_info += f"\n**⚠️ Important:** Save this password securely!"
            
            add_field(dm_embed, "🔐 SSH Credentials & Access", ssh_access_info, False)
            
            features_info = """✅ **SSH:** Password authentication enabled
✅ **SFTP:** File transfer available
✅ **Root:** Full root access granted
✅ **Container:** High performance Docker environment"""
            add_field(dm_embed, "⚙️ Features & Capabilities", features_info, False)

            support_info = (
f"""**Need Help?**
• Use `{PREFIX}manage` to start/stop/reinstall your VPS
• Click 🔐 in manage to regenerate password
• Contact admin for issues or upgrades""" )
            add_field(dm_embed, "📞 Support & Management", support_info, False)
            
            try:
                await self.user.send(embed=dm_embed)
            except discord.Forbidden:
                await self.ctx.send(embed=create_info_embed("Notification Failed", f"Couldn't send DM to {self.user.mention}. Please ensure DMs are enabled."))
        except Exception as e:
            error_embed = create_error_embed("Creation Failed", f"Error: {str(e)}")
            await interaction.followup.send(embed=error_embed, ephemeral=True)

@bot.command(name='create')
@is_admin()
async def create_vps(ctx, ram: int, cpu: int, disk: int, user: discord.Member, expiry_days: int = None):
    if ram <= 0 or cpu <= 0 or disk <= 0:
        await ctx.send(embed=create_error_embed("Invalid Specs", "RAM, CPU, and Disk must be positive integers."))
        return
    
    if expiry_days is not None and expiry_days <= 0:
        await ctx.send(embed=create_error_embed("Invalid Expiry Days", "Expiry days must be a positive integer."))
        return
    
    expiry_text = f" with {expiry_days} days expiry" if expiry_days else f" with {DEFAULT_VPS_EXPIRATION_DAYS} days expiry (default)"
    embed = create_info_embed("VPS Creation", f"Creating VPS for {user.mention} with {ram}GB RAM, {cpu} CPU cores, {disk}GB Disk{expiry_text}.\nSelect node below.")
    view = NodeSelectView(ram, cpu, disk, user, ctx, expiry_days)
    
    # Send creation menu ephemerally/privately so it isn't visible to everyone
    await ctx.author.send(embed=embed, view=view)

class ReinstallOSSelectView(discord.ui.View):
    def __init__(self, parent_view, container_name, owner_id, actual_idx, ram_gb, cpu, storage_gb, node_id):
        super().__init__(timeout=300)
        self.parent_view = parent_view
        self.container_name = container_name
        self.owner_id = owner_id
        self.actual_idx = actual_idx
        self.ram_gb = ram_gb
        self.cpu = cpu
        self.storage_gb = storage_gb
        self.node_id = node_id
        self.select = discord.ui.Select(
            placeholder="Select an OS for the reinstall",
            options=[discord.SelectOption(label=o["label"], value=o["value"]) for o in OS_OPTIONS]
        )
        self.select.callback = self.select_os
        self.add_item(self.select)

    async def select_os(self, interaction: discord.Interaction):
        os_version = self.select.values[0]
        self.select.disabled = True
        creating_embed = create_info_embed("Reinstalling VPS", f"Deploying {os_version} for `{self.container_name}`...")
        await interaction.response.edit_message(embed=creating_embed, view=self)
        ram_mb = self.ram_gb * 1024
        
        new_password = generate_strong_password()
        
        try:
            docker_cmd = (
                f"run -d --name {self.container_name} "
                f"--privileged "
                f"--memory={ram_mb}m "
                f"--cpus={self.cpu} "
                f"--restart=always "
                f"{os_version} /bin/bash"
            )
            await execute_docker(self.container_name, docker_cmd, node_id=self.node_id)
            await apply_internal_permissions(self.container_name, self.node_id)
            
            success, result = await configure_ssh(self.container_name, self.node_id, new_password)
            if not success:
                logger.warning(f"SSH configuration partially failed: {result}")
            
            if HOST_MOTD:
                try:
                    await execute_docker(self.container_name, f"exec -u 0 {self.container_name} bash -c \"{HOST_MOTD}\"", node_id=self.node_id)
                    logger.info(f"HOST_MOTD executed on {self.container_name}")
                except Exception as e:
                    logger.warning(f"HOST_MOTD execution failed for {self.container_name}: {e}")
            
            target_vps = vps_data[self.owner_id][self.actual_idx]
            target_vps["os_version"] = os_version
            target_vps["status"] = "running"
            target_vps["suspended"] = False
            target_vps["created_at"] = datetime.now().isoformat()
            target_vps["root_password"] = new_password
            config_str = f"{self.ram_gb}GB RAM / {self.cpu} CPU / {self.storage_gb}GB Disk"
            target_vps["config"] = config_str
            if not target_vps.get('expiration_date'):
                target_vps['expiration_date'] = (datetime.now() + timedelta(days=DEFAULT_VPS_EXPIRATION_DAYS)).isoformat()
            save_vps_data_immediate()
            
            success_embed = create_success_embed("Reinstall Complete", f"VPS `{self.container_name}` has been successfully reinstalled!")
            add_field(success_embed, "Resources", f"**RAM:** {self.ram_gb}GB\n**CPU:** {self.cpu} Cores\n**Storage:** {self.storage_gb}GB", False)
            add_field(success_embed, "OS", os_version, True)
            add_field(success_embed, "SSH Configuration", "✅ Configured (PasswordAuth enabled)\n🔐 New password generated and sent via DM", True)
            add_field(success_embed, "Features", "Privileged Docker Container, Nesting, Systemd Support", False)
            await interaction.followup.send(embed=success_embed, ephemeral=True)
            
            try:
                owner = await bot.fetch_user(int(self.owner_id))
                dm_embed = create_success_embed("🔄 VPS Reinstalled Successfully!", f"Your VPS `{self.container_name}` is ready with a new operating system!")
                
                vps_details = f"""
**Container:** `{self.container_name}`
**New OS:** {os_version}
**Configuration:** {self.ram_gb}GB RAM / {self.cpu} CPU / {self.storage_gb}GB Disk
**Status:** 🟢 Running
**Reinstalled:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
                add_field(dm_embed, "📊 VPS Details", vps_details.strip(), False)
                
                try:
                    networks = await asyncio.wait_for(
                        get_container_networks(self.container_name, self.node_id),
                        timeout=3.0
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout getting networks for {self.container_name}")
                    networks = {}
                
                if networks:
                    ssh_access_info = "**🖥️ Available Connection Points:**\n"
                    for interface, ip in sorted(networks.items()):
                        ssh_access_info += f"└─ **{interface}:** `ssh root@{ip}`\n"
                    ssh_access_info += f"\n**🔑 New Login Credentials:**\n"
                    ssh_access_info += f"**Username:** `root`\n"
                    ssh_access_info += f"**Password:** `{new_password}`\n"
                    ssh_access_info += f"\n**⚠️ Important:** Save this password securely!"
                else:
                    ssh_access_info = "**🔑 New Login Credentials:**\n"
                    ssh_access_info += f"**Username:** `root`\n"
                    ssh_access_info += f"**Password:** `{new_password}`\n"
                    ssh_access_info += f"\n**📡 Network Setup:**\n"
                    ssh_access_info += "Your VPS is initializing its network interfaces.\n"
                    ssh_access_info += "They will be available in a few seconds.\n"
                    ssh_access_info += f"\n**⚠️ Important:** Save this password securely!"
                
                add_field(dm_embed, "🔐 SSH Credentials & Access", ssh_access_info, False)
                
                features_info = """✅ **SSH:** Password authentication enabled
✅ **SFTP:** File transfer available
✅ **Root:** Full root access granted
✅ **Fresh:** Clean OS installation ready to use"""
                add_field(dm_embed, "⚙️ Features & Capabilities", features_info, False)
                
                support_info = f"""**Need Help?**
• Use `{PREFIX}manage` to manage your VPS
• Click 🔐 in manage to regenerate password
• Contact admin for issues or upgrades"""
                add_field(dm_embed, "📞 Support & Management", support_info, False)
                             
                await owner.send(embed=dm_embed)
            except Exception as e:
                logger.warning(f"Failed to send reinstall DM to {self.owner_id}: {e}")
            
            self.stop()
        except Exception as e:
            error_embed = create_error_embed("Reinstall Failed", f"Error: {str(e)}")
            await interaction.followup.send(embed=error_embed, ephemeral=True)
            self.stop()

class ManageView(discord.ui.View):
    def __init__(self, user_id, vps_list, is_shared=False, owner_id=None, is_admin=False, actual_index: Optional[int] = None):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.vps_list = vps_list[:]
        self.selected_index = None
        self.is_shared = is_shared
        self.owner_id = owner_id or user_id
        self.is_admin = is_admin
        self.actual_index = actual_index
        self.indices = list(range(len(vps_list)))
        if self.is_shared and self.actual_index is None:
            raise ValueError("actual_index required for shared views")
        if len(vps_list) > 1:
            options = [
                discord.SelectOption(
                    label=f"VPS {i+1} ({v.get('config', 'Custom')})",
                    description=f"Status: {v.get('status', 'unknown')}",
                    value=str(i)
                ) for i, v in enumerate(vps_list)
            ]
            self.select = discord.ui.Select(placeholder="Select a VPS to manage", options=options)
            self.select.callback = self.select_vps
            self.add_item(self.select)
            self.initial_embed = create_embed("VPS Management", "Select a VPS from the dropdown menu below.", 0x1a1a1a)
            add_field(self.initial_embed, "Available VPS", "\n".join([f"**VPS {i+1}:** `{v['container_name']}` - Status: `{v.get('status', 'unknown').upper()}`" for i, v in enumerate(vps_list)]), False)
        else:
            self.selected_index = 0
            self.initial_embed = None
            self.add_action_buttons()

    async def get_initial_embed(self):
        if self.initial_embed is not None:
            return self.initial_embed
        self.initial_embed = await self.create_vps_embed(self.selected_index)
        return self.initial_embed

    async def create_vps_embed(self, index):
        vps = self.vps_list[index]
        node = get_node(vps['node_id'])
        node_name = node['name'] if node else "Unknown"
        status = vps.get('status', 'unknown')
        suspended = vps.get('suspended', False)
        whitelisted = vps.get('whitelisted', False)
        status_color = 0x00ff88 if status == 'running' and not suspended else 0xffaa00 if suspended else 0xff3366
        container_name = vps['container_name']
        stats = await get_container_stats(container_name, vps['node_id'])
        
        status_text = f"{status.upper()}"
        if suspended:
            status_text += " (SUSPENDED)"
        if whitelisted:
            status_text += " (WHITELISTED)"
        owner_text = ""
        if self.is_admin and self.owner_id != self.user_id:
            try:
                owner_user = await bot.fetch_user(int(self.owner_id))
                owner_text = f"\n**Owner:** {owner_user.mention}"
            except:
                owner_text = f"\n**Owner ID:** {self.owner_id}"
        embed = create_embed(
            f"VPS Management - VPS {index + 1}",
            f"Managing container: `{container_name}` on node {node_name}{owner_text}",
            status_color
        )
        resource_info = f"**Configuration:** {vps.get('config', 'Custom')}\n"
        resource_info += f"**Status:** `{status_text}`\n"
        resource_info += f"**RAM:** {vps['ram']}\n"
        resource_info += f"**CPU:** {vps['cpu']} Cores\n"
        resource_info += f"**Storage:** {vps['storage']}\n"
        resource_info += f"**OS:** {vps.get('os_version', 'ubuntu:22.04')}\n"
        resource_info += f"**Uptime:** {stats['uptime']}"
        add_field(embed, "📊 Allocated Resources", resource_info, False)
        
        if vps.get('expiration_date'):
            expiration_dt = datetime.fromisoformat(vps['expiration_date'])
            days_remaining = (expiration_dt - datetime.now()).days
            
            if days_remaining < 0:
                expiration_status = "🔴 EXPIRED"
            elif days_remaining <= EXPIRATION_WARNING_DAYS:
                expiration_status = "🟡 EXPIRING SOON"
            else:
                expiration_status = "🟢 ACTIVE"
            
            expiration_info = f"**Status:** {expiration_status}\n"
            expiration_info += f"**Expires:** {expiration_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
            expiration_info += f"**Days Left:** {max(0, days_remaining)} days"
            add_field(embed, "⏰ Expiration", expiration_info, False)
        else:
            add_field(embed, "⏰ Expiration", "No expiration date set", False)
        
        if suspended:
            add_field(embed, "⚠️ Suspended", "This VPS is suspended. Contact an admin to unsuspend.", False)
        if whitelisted:
            add_field(embed, "✅ Whitelisted", "This VPS is exempt from auto-suspension.", False)
        
        cpu_usage = f"{stats.get('cpu', 0):.1f}%" if stats.get('cpu') is not None else "Unknown"
        ram_data = stats.get('ram', {})
        ram_used = ram_data.get('used', 0) if isinstance(ram_data, dict) else 0
        ram_total = ram_data.get('total', 0) if isinstance(ram_data, dict) else 0
        ram_pct = ram_data.get('pct', 0.0) if isinstance(ram_data, dict) else 0.0
        ram_str = f"{ram_used}/{ram_total} MB ({ram_pct:.1f}%)" if ram_total > 0 else "Unknown"
        disk_usage = stats.get('disk', 'Unknown')

        live_stats = f"**CPU Usage:** {cpu_usage}\n**Memory:** {ram_str}\n**Disk:** {disk_usage}"
        add_field(embed, "📈 Live Usage", live_stats, False)
        add_field(embed, "🎮 Controls", "Use the buttons below to manage your VPS", False)
        return embed

    def add_action_buttons(self):
        if not self.is_shared and not self.is_admin:
            reinstall_button = discord.ui.Button(label="🔄 Reinstall", style=discord.ButtonStyle.danger)
            reinstall_button.callback = lambda inter: self.action_callback(inter, 'reinstall')
            self.add_item(reinstall_button)
        start_button = discord.ui.Button(label="▶ Start", style=discord.ButtonStyle.success)
        start_button.callback = lambda inter: self.action_callback(inter, 'start')
        stop_button = discord.ui.Button(label="⏸ Stop", style=discord.ButtonStyle.secondary)
        stop_button.callback = lambda inter: self.action_callback(inter, 'stop')
        ssh_button = discord.ui.Button(label="🔑 SSH", style=discord.ButtonStyle.primary)
        ssh_button.callback = lambda inter: self.action_callback(inter, 'ssh')
        password_button = discord.ui.Button(label="🔐 Regen Password", style=discord.ButtonStyle.primary)
        password_button.callback = lambda inter: self.action_callback(inter, 'regen_password')
        stats_button = discord.ui.Button(label="📊 Stats", style=discord.ButtonStyle.secondary)
        stats_button.callback = lambda inter: self.action_callback(inter, 'stats')
        self.add_item(start_button)
        self.add_item(stop_button)
        self.add_item(ssh_button)
        self.add_item(password_button)
        self.add_item(stats_button)

    async def select_vps(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.user_id and not self.is_admin:
            await interaction.response.send_message(embed=create_error_embed("Access Denied", "This is not your VPS!"), ephemeral=True)
            return
        self.selected_index = int(self.select.values[0])
        await interaction.response.defer()
        new_embed = await self.create_vps_embed(self.selected_index)
        self.clear_items()
        self.add_action_buttons()
        await interaction.edit_original_response(embed=new_embed, view=self)

    async def action_callback(self, interaction: discord.Interaction, action: str):
        try:
            await interaction.response.defer(ephemeral=True)
        except:
            return
        
        if str(interaction.user.id) != self.user_id and not self.is_admin:
            await interaction.followup.send(embed=create_error_embed("Access Denied", "This is not your VPS!"), ephemeral=True)
            return
        if self.selected_index is None:
            await interaction.followup.send(embed=create_error_embed("No VPS Selected", "Please select a VPS first."), ephemeral=True)
            return
        actual_idx = self.actual_index if self.is_shared else self.indices[self.selected_index]
        target_vps = vps_data[self.owner_id][actual_idx]
        suspended = target_vps.get('suspended', False)
        if suspended and not self.is_admin and action != 'stats':
            await interaction.followup.send(embed=create_error_embed("Access Denied", "This VPS is suspended. Contact an admin to unsuspend."), ephemeral=True)
            return
        container_name = target_vps["container_name"]
        node_id = target_vps['node_id']
        
        if action == 'stats':
            try:
                stats = await get_container_stats(container_name, node_id)
                stats_embed = create_info_embed("📈 Live Statistics", f"Real-time stats for `{container_name}`")
                add_field(stats_embed, "Status", f"`{stats['status'].upper()}`", True)
                add_field(stats_embed, "CPU", f"{stats['cpu']:.1f}%", True)
                add_field(stats_embed, "Memory", f"{stats['ram']['used']}/{stats['ram']['total']} MB ({stats['ram']['pct']:.1f}%)", True)
                add_field(stats_embed, "Disk", stats['disk'], True)
                add_field(stats_embed, "Uptime", stats['uptime'], True)
                await interaction.followup.send(embed=stats_embed, ephemeral=True)
            except Exception as e:
                await interaction.followup.send(embed=create_error_embed("Stats Failed", str(e)), ephemeral=True)
            return
            
        if action == 'reinstall':
            if self.is_shared or self.is_admin:
                await interaction.followup.send(embed=create_error_embed("Access Denied", "Only the VPS owner can reinstall!"), ephemeral=True)
                return
            if suspended:
                await interaction.followup.send(embed=create_error_embed("Cannot Reinstall", "Unsuspend the VPS first."), ephemeral=True)
                return
            ram_gb = int(target_vps['ram'].replace('GB', ''))
            cpu = int(target_vps['cpu'])
            storage_gb = int(target_vps['storage'].replace('GB', ''))
            confirm_embed = create_warning_embed("Reinstall Warning",
                f"⚠️ **WARNING:** This will erase all data on VPS `{container_name}` and reinstall a fresh OS.\n\n"
                f"This action cannot be undone. Continue?")
            class ConfirmView(discord.ui.View):
                def __init__(self, parent_view, container_name, owner_id, actual_idx, ram_gb, cpu, storage_gb, node_id):
                    super().__init__(timeout=60)
                    self.parent_view = parent_view
                    self.container_name = container_name
                    self.owner_id = owner_id
                    self.actual_idx = actual_idx
                    self.ram_gb = ram_gb
                    self.cpu = cpu
                    self.storage_gb = storage_gb
                    self.node_id = node_id

                @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
                async def confirm(self, inter: discord.Interaction, item: discord.ui.Button):
                    await inter.response.defer(ephemeral=True)
                    try:
                        await inter.followup.send(embed=create_info_embed("Deleting Container", f"Forcefully removing container `{self.container_name}`..."), ephemeral=True)
                        await execute_docker(self.container_name, f"rm -f {self.container_name}", node_id=self.node_id)
                        os_view = ReinstallOSSelectView(self.parent_view, self.container_name, self.owner_id, self.actual_idx, self.ram_gb, self.cpu, self.storage_gb, self.node_id)
                        await inter.followup.send(embed=create_info_embed("Select OS", "Choose the new OS for reinstallation."), view=os_view, ephemeral=True)
                    except Exception as e:
                        await inter.followup.send(embed=create_error_embed("Delete Failed", f"Error: {str(e)}"), ephemeral=True)

                @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
                async def cancel(self, inter: discord.Interaction, item: discord.ui.Button):
                    new_embed = await self.parent_view.create_vps_embed(self.parent_view.selected_index)
                    await inter.response.edit_message(embed=new_embed, view=self.parent_view)

            await interaction.followup.send(embed=confirm_embed, view=ConfirmView(self, container_name, self.owner_id, actual_idx, ram_gb, cpu, storage_gb, node_id), ephemeral=True)
            return
        
        if action == 'regen_password':
            new_password = generate_strong_password()
            success, result = await configure_ssh(container_name, node_id, new_password)
            if success:
                try:
                    owner = await bot.fetch_user(int(self.owner_id))
                    await owner.send(embed=create_success_embed("🔐 Password Regenerated", f"New root password for `{container_name}` is: `{new_password}`"))
                    await interaction.followup.send(embed=create_success_embed("Password Regenerated", "Sent new password to DMs."), ephemeral=True)
                except:
                    await interaction.followup.send(embed=create_success_embed("Password Regenerated", f"New Password: `{new_password}`"), ephemeral=True)
            else:
                await interaction.followup.send(embed=create_error_embed("Password Regeneration Failed", result), ephemeral=True)
            return

        if action == 'ssh':
            networks = await get_container_networks(container_name, node_id)
            pwd = get_vps_password(container_name) or "Not set"
            ssh_info = f"**Password:** `{pwd}`\n\n"
            if networks:
                for iface, ip in networks.items():
                    ssh_info += f"• `{iface}`: `ssh root@{ip}`\n"
            else:
                ssh_info += "No active network interfaces detected."
            await interaction.followup.send(embed=create_info_embed("🔑 SSH Details", ssh_info), ephemeral=True)
            return

        suspended = target_vps.get('suspended', False)
        if suspended:
            target_vps['suspended'] = False
            save_vps_data_immediate()
            
        if action == 'start':
            try:
                current_status = target_vps.get('status', 'stopped')
                if current_status == 'running':
                    await interaction.followup.send(embed=create_info_embed("Already Running", f"VPS `{container_name}` is already running."), ephemeral=True)
                    return
                
                await execute_docker(container_name, f"start {container_name}", node_id=node_id)
                target_vps["status"] = "running"
                save_vps_data_immediate()
                await apply_internal_permissions(container_name, node_id)
                await interaction.followup.send(embed=create_success_embed("VPS Started", f"VPS `{container_name}` is now running."), ephemeral=True)
            except Exception as e:
                await interaction.followup.send(embed=create_error_embed("Start Failed", str(e)), ephemeral=True)
            return

        if action == 'stop':
            try:
                await execute_docker(container_name, f"stop {container_name}", node_id=node_id)
                target_vps["status"] = "stopped"
                save_vps_data_immediate()
                await interaction.followup.send(embed=create_success_embed("VPS Stopped", f"VPS `{container_name}` has been stopped."), ephemeral=True)
            except Exception as e:
                await interaction.followup.send(embed=create_error_embed("Stop Failed", str(e)), ephemeral=True)
            return

@bot.command(name='manage')
async def manage(ctx):
    user_id = str(ctx.author.id)
    vps_list = vps_data.get(user_id, [])
    if not vps_list:
        await ctx.send(embed=create_error_embed("No VPS Found", "You do not own any VPS containers."))
        return
    view = ManageView(user_id, vps_list)
    initial_embed = await view.get_initial_embed()
    await ctx.send(embed=initial_embed, view=view)

@bot.command(name='reinstall')
async def reinstall(ctx):
    user_id = str(ctx.author.id)
    vps_list = vps_data.get(user_id, [])
    if not vps_list:
        await ctx.send(embed=create_error_embed("No VPS Found", "You do not own any VPS containers."))
        return
    view = ManageView(user_id, vps_list)
    initial_embed = await view.get_initial_embed()
    await ctx.send(embed=initial_embed, view=view)

# Run the bot
if __name__ == '__main__':
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        logger.error("DISCORD_TOKEN is missing in the environment variables.")
