import discord
from discord.ext import commands
import asyncio
import json
from datetime import datetime, timedelta
import shlex
import logging
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

# Load environment variables
load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
BOT_NAME = os.getenv('BOT_NAME', 'UnixNodes')
PREFIX = os.getenv('PREFIX', '!')
YOUR_SERVER_IP = os.getenv('YOUR_SERVER_IP', '127.0.0.1')
MAIN_ADMIN_ID = int(os.getenv('MAIN_ADMIN_ID', '1210291131301101618'))
VPS_USER_ROLE_ID = int(os.getenv('VPS_USER_ROLE_ID', '1210291131301101618'))
HOST_MOTD = os.getenv('HOST_MOTD', '')
BOT_VERSION = os.getenv('BOT_VERSION', '8.0-DOCKER')
BOT_DEVELOPER = os.getenv('BOT_DEVELOPER', 'Hopingboyz')
BOT_THUMBNAIL_URL = os.getenv('BOT_THUMBNAIL_URL', 'https://i.imgur.com/Tv3clt0.jpeg')
BOT_ICON_URL = os.getenv('BOT_ICON_URL', 'https://i.imgur.com/Tv3clt0.jpeg')

DEFAULT_VPS_EXPIRATION_DAYS = int(os.getenv('DEFAULT_VPS_EXPIRATION_DAYS', '30'))
EXPIRATION_WARNING_DAYS = int(os.getenv('EXPIRATION_WARNING_DAYS', '1'))

# Docker Image Options mapped to standard base images
OS_OPTIONS = [
    {"label": "Ubuntu 22.04 LTS", "value": "ubuntu:22.04"},
    {"label": "Ubuntu 24.04 LTS", "value": "ubuntu:24.04"},
    {"label": "Debian 11 (Bullseye)", "value": "debian:11"},
    {"label": "Debian 12 (Bookworm)", "value": "debian:12"},
    {"label": "Alpine Linux (Latest)", "value": "alpine:latest"},
]

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
    cur.execute('''CREATE TABLE IF NOT EXISTS admins (user_id TEXT PRIMARY KEY)''')
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
        ssh_port INTEGER DEFAULT 22
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)''')
    settings_init = [('cpu_threshold', '90'), ('ram_threshold', '90')]
    for key, value in settings_init:
        cur.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (key, value))
    cur.execute('''CREATE TABLE IF NOT EXISTS port_allocations (user_id TEXT PRIMARY KEY, allocated_ports INTEGER DEFAULT 0)''')
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
            shared_json = json.dumps(vps.get('shared_with', []))
            history_json = json.dumps(vps.get('suspension_history', []))
            suspended_int = 1 if vps.get('suspended', False) else 0
            whitelisted_int = 1 if vps.get('whitelisted', False) else 0
            os_ver = vps.get('os_version', 'ubuntu:22.04')
            created_at = vps.get('created_at', datetime.now().isoformat())
            node_id = vps.get('node_id', 1)
            expiration_date = vps.get('expiration_date', None)
            root_password = vps.get('root_password', None)
            ssh_port = vps.get('ssh_port', 22)
            if 'id' not in vps or vps['id'] is None:
                cur.execute('''INSERT INTO vps (user_id, node_id, container_name, ram, cpu, storage, config, os_version, status, suspended, whitelisted, created_at, shared_with, suspension_history, expiration_date, root_password, ssh_port)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                            (user_id, node_id, vps['container_name'], vps['ram'], vps['cpu'], vps['storage'], vps['config'],
                             os_ver, vps['status'], suspended_int, whitelisted_int,
                             created_at, shared_json, history_json, expiration_date, root_password, ssh_port))
                vps['id'] = cur.lastrowid
            else:
                cur.execute('''UPDATE vps SET user_id = ?, node_id = ?, container_name = ?, ram = ?, cpu = ?, storage = ?, config = ?, os_version = ?, status = ?, suspended = ?, whitelisted = ?, shared_with = ?, suspension_history = ?, expiration_date = ?, root_password = ?, ssh_port = ?
                               WHERE id = ?''',
                            (user_id, node_id, vps['container_name'], vps['ram'], vps['cpu'], vps['storage'], vps['config'],
                             os_ver, vps['status'], suspended_int, whitelisted_int, shared_json, history_json, expiration_date, root_password, ssh_port, vps['id']))
    conn.commit()
    conn.close()
  
def save_vps_data_immediate():
    save_vps_data()

def get_available_host_port(node_id: int) -> Optional[int]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT host_port FROM port_forwards')
    used_ports = set(row[0] for row in cur.fetchall())
    conn.close()
    for _ in range(100):
        port = random.randint(20000, 50000)
        if port not in used_ports:
            return port
    return None

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

CPU_THRESHOLD = int(get_setting('cpu_threshold', 90))
RAM_THRESHOLD = int(get_setting('ram_threshold', 90))

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

COLOR_PRIMARY = 0x2c3e50
COLOR_SUCCESS = 0x27ae60
COLOR_ERROR = 0xe74c3c
COLOR_WARNING = 0xf39c12
COLOR_INFO = 0x3498db

def truncate_text(text, max_length=1024):
    if not text:
        return text
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."

def generate_strong_password(length=16):
    charset = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(charset) for _ in range(length))

def sanitize_username_for_container(username: str) -> str:
    sanitized = username.replace('_', '-').replace(' ', '-')
    sanitized = ''.join(c for c in sanitized if c.isalnum() or c == '-')
    sanitized = sanitized.strip('-').lower()
    return sanitized[:30]

def set_vps_password(container_name, password):
    for user_id, vps_list in vps_data.items():
        for vps in vps_list:
            if vps['container_name'] == container_name:
                vps['root_password'] = password
                save_vps_data_immediate()
                return True
    return False

# Docker CLI Helper
async def execute_docker(command: str, timeout=120, node_id: Optional[int] = None):
    full_command = f"docker {command}"
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
        error = stderr.decode().strip() if stderr else "Command failed"
        raise Exception(f"Docker execution error: {error}")
    return stdout.decode().strip() if stdout else True

async def configure_docker_ssh(container_name: str, password: str):
    """Installs OpenSSH server and sets up root login inside Docker container"""
    setup_script = f"""
    apt-get update && apt-get install -y openssh-server sudo || apk add --no-warning openssh sudo || yum install -y openssh-server
    mkdir -p /var/run/sshd
    echo 'root:{password}' | chpasswd
    sed -i 's/#PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
    sed -i 's/PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
    sed -i 's/#PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
    sed -i 's/PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
    ssh-keygen -A
    /usr/sbin/sshd || service ssh start || systemctl restart ssh || true
    """
    cmd = f"exec {container_name} sh -c \"{setup_script}\""
    await execute_docker(cmd)
    set_vps_password(container_name, password)

def create_embed(title, description="", color=COLOR_PRIMARY):
    embed = discord.Embed(title=f"🌟 {title}", description=truncate_text(description, 4096), color=color)
    embed.set_thumbnail(url=BOT_THUMBNAIL_URL)
    embed.set_footer(text=f"Made by Hopingboyz • v{BOT_VERSION}", icon_url=BOT_ICON_URL)
    embed.timestamp = datetime.now()
    return embed

def add_field(embed, name, value, inline=False):
    embed.add_field(name=f"➤ {name}", value=truncate_text(value, 1024), inline=inline)
    return embed

def create_success_embed(title, description=""): return create_embed(title, description, COLOR_SUCCESS)
def create_error_embed(title, description=""): return create_embed(title, description, COLOR_ERROR)
def create_info_embed(title, description=""): return create_embed(title, description, COLOR_INFO)
def create_warning_embed(title, description=""): return create_embed(title, description, COLOR_WARNING)

def is_admin():
    async def predicate(ctx):
        user_id = str(ctx.author.id)
        if user_id == str(MAIN_ADMIN_ID) or user_id in admin_data.get("admins", []):
            return True
        raise commands.CheckFailure("You need admin permissions to use this command.")
    return commands.check(predicate)

async def get_container_stats(container_name: str) -> Dict:
    try:
        out = await execute_docker(f"stats {container_name} --no-stream --format \"{{{{.CPUPerc}}}}|{{{{.MemUsage}}}}|{{{{.MemPerc}}}}\"")
        parts = out.split('|')
        cpu = parts[0]
        mem = parts[1]
        return {"status": "running", "cpu": cpu, "ram": mem, "disk": "N/A", "uptime": "Active"}
    except Exception:
        return {"status": "stopped", "cpu": "0%", "ram": "0MB / 0MB", "disk": "N/A", "uptime": "Offline"}

@bot.event
async def on_ready():
    logger.info(f'{bot.user} connected. Docker VPS Bot Ready!')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f"{BOT_NAME} Docker Manager"))

@bot.command(name='ping')
async def ping(ctx):
    latency = round(bot.latency * 1000)
    embed = create_success_embed("🏓 Pong!", f"Latency: `{latency}ms`")
    await ctx.send(embed=embed)

@bot.command(name="myvps")
async def my_vps(ctx):
    user_id = str(ctx.author.id)
    vps_list = vps_data.get(user_id, [])
    if not vps_list:
        await ctx.send(embed=create_error_embed("No VPS Found", "You do not own any Docker VPS."))
        return
    
    embed = create_info_embed("🖥️ My Docker VPS Dashboard", "Your current containers:")
    for v in vps_list:
        ssh_port = v.get('ssh_port', 22)
        info = f"Status: `{v.get('status')}`\nConfig: `{v.get('config')}`\nSSH Access: `ssh root@{YOUR_SERVER_IP} -p {ssh_port}`"
        add_field(embed, f"Container: {v['container_name']}", info, False)
    await ctx.send(embed=embed)

class OSSelectView(discord.ui.View):
    def __init__(self, ram: int, cpu: int, disk: int, user: discord.Member, ctx, expiry_days: int = 30):
        super().__init__(timeout=300)
        self.ram = ram
        self.cpu = cpu
        self.disk = disk
        self.user = user
        self.ctx = ctx
        self.expiry_days = expiry_days
        self.select = discord.ui.Select(
            placeholder="Select OS Docker Image",
            options=[discord.SelectOption(label=o["label"], value=o["value"]) for o in OS_OPTIONS]
        )
        self.select.callback = self.select_os
        self.add_item(self.select)

    async def select_os(self, interaction: discord.Interaction):
        if str(interaction.user.id) != str(self.ctx.author.id):
            await interaction.response.send_message("Access denied.", ephemeral=True)
            return
        os_version = self.select.values[0]
        self.select.disabled = True
        await interaction.response.edit_message(embed=create_info_embed("Deploying Docker Container", "Please wait..."), view=self)
        
        username = sanitize_username_for_container(self.user.name)
        vps_id = random.randint(1000, 9999)
        container_name = f"{username}-vps-{vps_id}"
        host_ssh_port = get_available_host_port(1) or random.randint(20000, 50000)
        root_password = generate_strong_password()

        try:
            # Run privileged Docker container with resource limits & mapped SSH port
            run_cmd = f"run -d --name {container_name} --privileged --memory={self.ram}g --cpus={self.cpu} -p {host_ssh_port}:22 {os_version} tail -f /dev/null"
            await execute_docker(run_cmd)
            
            # Setup SSH
            await configure_docker_ssh(container_name, root_password)

            vps_info = {
                "container_name": container_name,
                "node_id": 1,
                "ram": f"{self.ram}GB",
                "cpu": str(self.cpu),
                "storage": f"{self.disk}GB",
                "config": f"{self.ram}GB RAM / {self.cpu} CPU / {self.disk}GB Disk",
                "os_version": os_version,
                "status": "running",
                "suspended": False,
                "whitelisted": False,
                "created_at": datetime.now().isoformat(),
                "expiration_date": (datetime.now() + timedelta(days=self.expiry_days)).isoformat(),
                "root_password": root_password,
                "ssh_port": host_ssh_port
            }

            user_id = str(self.user.id)
            if user_id not in vps_data:
                vps_data[user_id] = []
            vps_data[user_id].append(vps_info)
            save_vps_data_immediate()

            success_embed = create_success_embed("Docker VPS Created!")
            add_field(success_embed, "Container Name", f"`{container_name}`", True)
            add_field(success_embed, "SSH Command", f"`ssh root@{YOUR_SERVER_IP} -p {host_ssh_port}`", False)
            add_field(success_embed, "Password", f"`{root_password}`", False)
            await interaction.followup.send(embed=success_embed)

        except Exception as e:
            await interaction.followup.send(embed=create_error_embed("Deployment Failed", str(e)))

@bot.command(name='create')
@is_admin()
async def create_vps(ctx, ram: int, cpu: int, disk: int, user: discord.Member, expiry_days: int = 30):
    embed = create_info_embed("VPS Creation", f"Creating Docker VPS for {user.mention}. Select OS image below:")
    view = OSSelectView(ram, cpu, disk, user, ctx, expiry_days)
    await ctx.send(embed=embed, view=view)

@bot.command(name='manage')
async def manage(ctx):
    user_id = str(ctx.author.id)
    vps_list = vps_data.get(user_id, [])
    if not vps_list:
        await ctx.send(embed=create_error_embed("No VPS", "You don't own any Docker VPS."))
        return
    
    view = ManageView(user_id, vps_list)
    embed = await view.get_initial_embed()
    await ctx.send(embed=embed, view=view)

class ManageView(discord.ui.View):
    def __init__(self, user_id, vps_list):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.vps_list = vps_list
        self.selected_index = 0
        self.add_action_buttons()

    async def get_initial_embed(self):
        vps = self.vps_list[self.selected_index]
        embed = create_embed("Docker VPS Management", f"Managing `{vps['container_name']}`")
        stats = await get_container_stats(vps['container_name'])
        add_field(embed, "Status", vps['status'].upper(), True)
        add_field(embed, "CPU Usage", stats['cpu'], True)
        add_field(embed, "RAM Usage", stats['ram'], True)
        add_field(embed, "SSH Port", str(vps.get('ssh_port', 22)), True)
        return embed

    def add_action_buttons(self):
        start = discord.ui.Button(label="▶ Start", style=discord.ButtonStyle.success)
        stop = discord.ui.Button(label="⏸ Stop", style=discord.ButtonStyle.secondary)
        restart = discord.ui.Button(label="🔄 Restart", style=discord.ButtonStyle.primary)
        
        start.callback = lambda i: self.control(i, "start")
        stop.callback = lambda i: self.control(i, "stop")
        restart.callback = lambda i: self.control(i, "restart")
        
        self.add_item(start)
        self.add_item(stop)
        self.add_item(restart)

    async def control(self, interaction: discord.Interaction, action: str):
        await interaction.response.defer(ephemeral=True)
        vps = self.vps_list[self.selected_index]
        name = vps['container_name']
        try:
            await execute_docker(f"{action} {name}")
            vps['status'] = "running" if action in ["start", "restart"] else "stopped"
            save_vps_data_immediate()
            await interaction.followup.send(embed=create_success_embed("Success", f"Executed {action} on {name}"), ephemeral=True)
        except Exception as e:
            await interaction.followup.send(embed=create_error_embed("Failed", str(e)), ephemeral=True)

if __name__ == '__main__':
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        logger.error("DISCORD_TOKEN not provided in .env!")
