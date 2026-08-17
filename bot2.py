import os
import sys
import json
import time
import re
import asyncio
import logging
from datetime import datetime
import discord
from discord.ext import commands
import docker
import psutil

# ---------------------------------------------------------
# LOGGING SETUP
# ---------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

CONFIG_FILE = "config.json"
DB_FILE = "vps_db.json"

# Load / Initialize Configuration
if not os.path.exists(CONFIG_FILE):
    default_config = {
        "TOKEN": "YOUR_DISCORD_BOT_TOKEN_HERE",
        "PREFIX": "$",
        "ADMIN_IDS": [],
        "ANTINUKE_ENABLED": True,
        "DEFAULT_DATA_DIR": "./vps_data"
    }
    with open(CONFIG_FILE, "w") as f:
        json.dump(default_config, f, indent=4)
    logging.info(f"Created initial {CONFIG_FILE}. Please populate it.")

with open(CONFIG_FILE, "r") as f:
    config = json.load(f)

# Force default data directory to local folder if pointing to system paths
if config.get("DEFAULT_DATA_DIR") == "/var/lib/discord_vps_data":
    config["DEFAULT_DATA_DIR"] = "./vps_data"
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

# Initialize Database
def load_db():
    if not os.path.exists(DB_FILE):
        return {"vps": {}, "admins": config.get("ADMIN_IDS", []), "antinuke": config.get("ANTINUKE_ENABLED", True)}
    try:
        with open(DB_FILE, "r") as f:
            data = json.load(f)
            if "admins" not in data:
                data["admins"] = config.get("ADMIN_IDS", [])
            if "antinuke" not in data:
                data["antinuke"] = config.get("ANTINUKE_ENABLED", True)
            return data
    except json.JSONDecodeError:
        return {"vps": {}, "admins": config.get("ADMIN_IDS", []), "antinuke": config.get("ANTINUKE_ENABLED", True)}

def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=4)

# Initialize Docker Client Safely
try:
    docker_client = docker.from_env()
    logging.info("Connected to Docker daemon successfully.")
except Exception as err:
    logging.error(f"Failed to connect to Docker daemon: {err}")
    docker_client = None

# Bot Setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=config.get("PREFIX", "$"), intents=intents)

# ---------------------------------------------------------
# UTILITY HELPER FUNCTIONS
# ---------------------------------------------------------
def parse_size_to_bytes(size_str: str) -> int:
    """Parses strings like '512m', '1g', '20g' into bytes with safety checks."""
    size_str = size_str.lower().strip()
    match = re.match(r"^(\d+)([mg])$", size_str)
    if not match:
        raise ValueError("Invalid format. Use numbers followed by 'm' or 'g' (e.g., 512m, 2g).")
    num, unit = match.groups()
    num = int(num)
    
    if unit == "m":
        bytes_val = num * 1024 * 1024
    elif unit == "g":
        bytes_val = num * 1024 * 1024 * 1024

    # Minimum memory safeguard (at least 256MB to avoid Docker 6MB API crash)
    if bytes_val < 256 * 1024 * 1024:
        raise ValueError("Memory allocation too small. Please specify at least `256m` or `1g`.")

    return bytes_val

def is_admin():
    async def predicate(ctx):
        db = load_db()
        admins = db.get("admins", [])
        if ctx.author.id in admins or ctx.author.guild_permissions.administrator:
            return True
        await ctx.send("❌ **Access Denied:** You do not have permission to execute this administrative command.")
        return False
    return commands.check(predicate)

# ---------------------------------------------------------
# TMATE ENGINE PIPELINE (FIXED REAL SSH KEY GENERATION)
# ---------------------------------------------------------
def _setup_tmate_sync(container_id: str) -> str:
    """Synchronous package setup + foreground tmate stdout stream reader."""
    container = docker_client.containers.get(container_id)
    
    # Step 1: Install packages synchronously and wait for completion
    install_cmd = (
        "bash -c 'export DEBIAN_FRONTEND=noninteractive && "
        "apt-get update -qq && "
        "apt-get install -y -qq tmate openssh-client curl >/dev/null 2>&1'"
    )
    res = container.exec_run(install_cmd)
    if res.exit_code != 0:
        raise RuntimeError(f"Failed to install dependencies: {res.output.decode('utf-8', errors='ignore')}")

    # Step 2: Run tmate in foreground mode and read output stream
    exec_stream = container.exec_run("tmate -F", stream=True)
    
    start_time = time.time()
    for line in exec_stream.output:
        line_str = line.decode("utf-8", errors="ignore").strip()
        if "ssh session:" in line_str.lower():
            return line_str.split("ssh session:")[-1].strip()
        
        if time.time() - start_time > 30:
            break

    raise TimeoutError("Failed to capture tmate SSH session key.")

async def setup_tmate_container(container) -> str:
    return await asyncio.to_thread(_setup_tmate_sync, container.id)

# ---------------------------------------------------------
# OS PROVISIONING PIPELINE
# ---------------------------------------------------------
def _build_and_run_sync(os_type: str, ram_bytes: int, cpu_cores: int, disk_bytes: int, container_name: str):
    os_upper = os_type.upper()
    data_dir = os.path.abspath(config.get("DEFAULT_DATA_DIR", "./vps_data"))
    os.makedirs(data_dir, exist_ok=True)
    nano_cpus = int(cpu_cores * 1_000_000_000)

    image_map = {
        "UBUNTU22.04": "ubuntu:22.04",
        "UBUNTU20.04": "ubuntu:20.04",
        "DEBIAN10": "debian:10",
        "DEBIAN": "debian:10"
    }

    if os_upper not in image_map:
        raise ValueError(f"Unsupported OS version: {os_type}")

    image_tag = image_map[os_upper]

    try:
        docker_client.images.get(image_tag)
    except docker.errors.ImageNotFound:
        logging.info(f"Image {image_tag} not found locally. Pulling from Docker Hub...")
        docker_client.images.pull(image_tag)

    devices = ["/dev/kvm:/dev/kvm"] if os.path.exists("/dev/kvm") else None

    container = docker_client.containers.run(
        image=image_tag,
        name=container_name,
        command="tail -f /dev/null",
        detach=True,
        tty=True,
        stdin_open=True,
        mem_limit=ram_bytes,
        nano_cpus=nano_cpus,
        devices=devices,
        volumes={f"{data_dir}/{container_name}": {"bind": "/data", "mode": "rw"}},
        cap_add=["NET_ADMIN", "SYS_ADMIN"]
    )
    return container

async def build_and_run_vps(os_type: str, ram_bytes: int, cpu_cores: int, disk_bytes: int, container_name: str):
    return await asyncio.to_thread(_build_and_run_sync, os_type, ram_bytes, cpu_cores, disk_bytes, container_name)

# ---------------------------------------------------------
# BOT EVENTS
# ---------------------------------------------------------
@bot.event
async def on_ready():
    logging.info(f"Bot logged in as {bot.user.name} ({bot.user.id})")
    print("==================================================")
    print(f"   DOCKER VPS CONTROLLER BOT IS ONLINE           ")
    print(f"   Prefix: {bot.command_prefix}                  ")
    print("==================================================")

# ---------------------------------------------------------
# USER COMMANDS
# ---------------------------------------------------------
@bot.command(name="about")
async def cmd_about(ctx):
    embed = discord.Embed(
        title="⚡ Master Docker VPS Controller Engine",
        description="Enterprise-grade Discord bot for managing isolated Docker environments.",
        color=discord.Color.blue()
    )
    embed.add_field(name="Engine Architecture", value="Docker Engine + tmate SSH Relay", inline=True)
    embed.add_field(name="Supported Distributions", value="Ubuntu 22.04, Ubuntu 20.04, Debian 10", inline=True)
    embed.set_footer(text="SkydoVPS Systems Engine • Powerful & Secure")
    await ctx.send(embed=embed)

@bot.command(name="myvps")
async def cmd_myvps(ctx):
    db = load_db()
    user_vps = [(vps_id, info) for vps_id, info in db.get("vps", {}).items() if info.get("owner_id") == ctx.author.id]

    if not user_vps:
        await ctx.send("❌ **No active VPS found.** You currently do not own any running instances.")
        return

    embed = discord.Embed(title="🖥️ Your Managed Virtual Private Servers", color=discord.Color.green())
    for vps_id, info in user_vps:
        embed.add_field(
            name=f"Instance ID: {vps_id}",
            value=(
                f"**OS:** `{info['os']}` | **Status:** `{info.get('status', 'RUNNING')}`\n"
                f"**CPU Cores:** `{info['cpu']}` | **RAM:** `{info['ram']}` | **Disk:** `{info['disk']}`\n"
                f"**SSH Key/Token:** Check your Direct Messages"
            ),
            inline=False
        )
    await ctx.send(embed=embed)

@bot.command(name="manage")
async def cmd_manage(ctx):
    embed = discord.Embed(title="⚙️ User VPS Management Console", color=discord.Color.gold())
    embed.description = "Use `$myvps` to inspect active instances and SSH details sent to your Direct Messages."
    await ctx.send(embed=embed)

@bot.command(name="ping")
async def cmd_ping(ctx):
    await ctx.send(f"🏓 **Pong!** Websocket Latency: `{round(bot.latency * 1000, 2)}ms`")

# ---------------------------------------------------------
# ADMIN COMMANDS
# ---------------------------------------------------------
@bot.command(name="create")
@is_admin()
async def cmd_create(ctx, ram: str, cpu: int, disk: str, os_type: str, user: discord.Member):
    """Command structure: $create ram cpu disk os user_id"""
    if not docker_client:
        await ctx.send("❌ **Error:** Docker engine daemon is unaccessible.")
        return

    try:
        ram_bytes = parse_size_to_bytes(ram)
        disk_bytes = parse_size_to_bytes(disk)
    except ValueError as e:
        await ctx.send(f"❌ **Parameter Error:** {e}")
        return

    valid_os_list = ["UBUNTU22.04", "UBUNTU20.04", "DEBIAN10", "DEBIAN"]
    os_upper = os_type.upper()
    if os_upper not in valid_os_list:
        await ctx.send(f"❌ **Invalid OS Selection:** Supported options are `{', '.join(valid_os_list)}`.")
        return

    status_msg = await ctx.send(f"⏳ **[1/3]** Launching `{os_upper}` container for {user.mention}...")

    container_name = f"vps_{user.id}_{int(time.time())}"

    try:
        container = await asyncio.wait_for(
            build_and_run_vps(os_upper, ram_bytes, cpu, disk_bytes, container_name),
            timeout=60.0
        )

        await status_msg.edit(content=f"⏳ **[2/3]** Container online. Configuring tmate SSH relay server...")

        tmate_ssh = await asyncio.wait_for(
            setup_tmate_container(container),
            timeout=60.0
        )

        await status_msg.edit(content=f"⏳ **[3/3]** VPS Ready! Sending credentials to {user.mention}...")

        db = load_db()
        vps_id = container.id[:10]
        db["vps"][vps_id] = {
            "container_id": container.id,
            "container_name": container_name,
            "owner_id": user.id,
            "owner_tag": str(user),
            "ram": ram,
            "cpu": cpu,
            "disk": disk,
            "os": os_upper,
            "status": "RUNNING",
            "created_at": datetime.utcnow().isoformat()
        }
        save_db(db)

        dm_embed = discord.Embed(
            title="🚀 Your Docker Virtual Private Server is Online!",
            color=discord.Color.green(),
            description="Your VPS instance has been deployed by an Administrator."
        )
        dm_embed.add_field(name="Instance ID", value=f"`{vps_id}`", inline=True)
        dm_embed.add_field(name="Allocated RAM", value=f"`{ram}`", inline=True)
        dm_embed.add_field(name="Allocated vCPU", value=f"`{cpu} Core(s)`", inline=True)
        dm_embed.add_field(name="Disk Storage", value=f"`{disk}`", inline=True)
        dm_embed.add_field(name="OS Distribution", value=f"`{os_upper}`", inline=True)
        dm_embed.add_field(
            name="🔑 Live tmate Interactive SSH Command",
            value=f"```bash\n{tmate_ssh}\n```",
            inline=False
        )

        dm_sent = True
        try:
            await user.send(embed=dm_embed)
        except discord.Forbidden:
            dm_sent = False

        final_msg = f"✅ **VPS Created Successfully!**\n**ID:** `{vps_id}`\n**Assigned To:** {user.mention}"
        if not dm_sent:
            final_msg += "\n⚠️ **Warning:** Could not DM user (Direct Messages closed)."

        await status_msg.edit(content=final_msg)

    except asyncio.TimeoutError:
        logging.error("Operation timed out during container provision/tmate handshake.")
        await status_msg.edit(content="❌ **Deployment Timed Out:** tmate relay network took too long to respond.")
    except Exception as err:
        logging.error(f"Error provisioning VPS: {err}", exc_info=True)
        await status_msg.edit(content=f"❌ **VPS Deployment Failed:** `{err}`")

@bot.command(name="list")
@is_admin()
async def cmd_list(ctx):
    db = load_db()
    all_vps = db.get("vps", {})

    if not all_vps:
        await ctx.send("📄 **No active VPS instances registered in database.**")
        return

    embed = discord.Embed(title="📋 Master Administrative VPS List", color=discord.Color.dark_purple())
    for vps_id, data in all_vps.items():
        embed.add_field(
            name=f"ID: {vps_id} | Owner: {data.get('owner_tag', 'Unknown')}",
            value=f"**OS:** `{data['os']}` | **Specs:** {data['cpu']} CPU / {data['ram']} RAM / {data['disk']} Disk",
            inline=False
        )
    await ctx.send(embed=embed)

@bot.command(name="system")
@is_admin()
async def cmd_system(ctx):
    cpu_usage = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    embed = discord.Embed(title="📊 Host Node Hardware Resource Telemetry", color=discord.Color.dark_blue())
    embed.add_field(name="CPU Utilization", value=f"`{cpu_usage}%`", inline=True)
    embed.add_field(name="RAM Usage", value=f"`{round(ram.used/(1024**3), 2)}GB / {round(ram.total/(1024**3), 2)}GB ({ram.percent}%)`", inline=False)
    embed.add_field(name="Disk Usage", value=f"`{round(disk.used/(1024**3), 2)}GB / {round(disk.total/(1024**3), 2)}GB ({disk.percent}%)`", inline=False)
    await ctx.send(embed=embed)

@bot.command(name="deletevps")
@is_admin()
async def cmd_deletevps(ctx, vps_id: str):
    db = load_db()
    all_vps = db.get("vps", {})

    if vps_id not in all_vps:
        await ctx.send(f"❌ **VPS ID `{vps_id}` not found.**")
        return

    cid = all_vps[vps_id]["container_id"]
    try:
        container = docker_client.containers.get(cid)
        container.remove(force=True)
    except Exception as e:
        logging.warning(f"Container removal warning: {e}")

    del db["vps"][vps_id]
    save_db(db)
    await ctx.send(f"🗑️ **VPS `{vps_id}` has been completely destroyed.**")

@bot.command(name="start")
@is_admin()
async def cmd_start_vps(ctx, action: str, vps_id: str):
    if action.lower() != "vps":
        return
    db = load_db()
    if vps_id not in db.get("vps", {}):
        await ctx.send(f"❌ **VPS ID `{vps_id}` not found.**")
        return

    cid = db["vps"][vps_id]["container_id"]
    try:
        container = docker_client.containers.get(cid)
        container.start()
        db["vps"][vps_id]["status"] = "RUNNING"
        save_db(db)
        await ctx.send(f"🟢 **VPS `{vps_id}` started successfully.**")
    except Exception as e:
        await ctx.send(f"❌ **Failed to start VPS:** `{e}`")

@bot.command(name="restart")
@is_admin()
async def cmd_restart_vps(ctx, action: str, vps_id: str):
    if action.lower() != "vps":
        return
    db = load_db()
    if vps_id not in db.get("vps", {}):
        await ctx.send(f"❌ **VPS ID `{vps_id}` not found.**")
        return

    cid = db["vps"][vps_id]["container_id"]
    try:
        container = docker_client.containers.get(cid)
        container.restart()
        db["vps"][vps_id]["status"] = "RUNNING"
        save_db(db)
        await ctx.send(f"🔄 **VPS `{vps_id}` restarted successfully.**")
    except Exception as e:
        await ctx.send(f"❌ **Failed to restart VPS:** `{e}`")

@bot.command(name="antinuke")
@is_admin()
async def cmd_antinuke(ctx, mode: str):
    db = load_db()
    if mode.lower() == "enable":
        db["antinuke"] = True
        save_db(db)
        await ctx.send("🛡️ **Anti-Nuke Shield Status:** `ENABLED`")
    elif mode.lower() == "disable":
        db["antinuke"] = False
        save_db(db)
        await ctx.send("⚠️ **Anti-Nuke Shield Status:** `DISABLED`")

@bot.command(name="create-admin")
@is_admin()
async def cmd_create_admin(ctx, user: discord.Member):
    db = load_db()
    if user.id not in db["admins"]:
        db["admins"].append(user.id)
        save_db(db)
        await ctx.send(f"👑 **Admin privileges granted to {user.mention}.**")

@bot.command(name="delete-admin")
@is_admin()
async def cmd_delete_admin(ctx, user: discord.Member):
    db = load_db()
    if user.id in db["admins"]:
        db["admins"].remove(user.id)
        save_db(db)
        await ctx.send(f"🚫 **Admin privileges revoked from {user.mention}.**")

@bot.command(name="reset")
@is_admin()
async def cmd_reset(ctx):
    confirm_msg = await ctx.send("⚠️ **CRITICAL WARNING:** Reply with `CONFIRM` within 15 seconds to wipe all containers and database records.")
    
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel and m.content == "CONFIRM"

    try:
        await bot.wait_for("message", check=check, timeout=15.0)
    except asyncio.TimeoutError:
        await confirm_msg.edit(content="❌ **Reset operation timed out and cancelled.**")
        return

    db = load_db()
    for vps_id, info in list(db.get("vps", {}).items()):
        try:
            c = docker_client.containers.get(info["container_id"])
            c.remove(force=True)
        except Exception:
            pass

    db["vps"] = {}
    save_db(db)
    await ctx.send("💥 **System Reset Complete.**")

if __name__ == "__main__":
    bot_token = config.get("TOKEN")
    if not bot_token or bot_token == "YOUR_DISCORD_BOT_TOKEN_HERE":
        print("❌ CRITICAL ERROR: Update config.json with your valid bot token.")
        sys.exit(1)
    
    bot.run(bot_token)
