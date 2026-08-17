<div align="center">

# 🚀 SDC BOT V2

### Powerful Discord VPS Management Bot

Create • Manage • Monitor Linux VPS directly from Discord

![Python](https://img.shields.io/badge/Python-3.10+-blue?style=for-the-badge&logo=python)
![Discord](https://img.shields.io/badge/Discord-Bot-5865F2?style=for-the-badge&logo=discord)
![Linux](https://img.shields.io/badge/Linux-Ubuntu%20%7C%20Debian-black?style=for-the-badge&logo=linux)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)

</div>

---

# ✨ Features

- 🚀 One Command VPS Creation
- 🐧 Multiple Linux Distributions
- 💻 Live Host System Monitoring
- 👤 User VPS Management
- 🔒 Admin Permission System
- 🛡️ Built-in Anti-Nuke Protection
- ⚡ Fast & Lightweight
- 💾 SQLite Database Support
- 📊 VPS Status Monitoring

---

# 🐧 Supported Operating Systems

| Operating System | Status |
|-----------------|--------|
| Ubuntu 22.04 | ✅ |
| Ubuntu 20.04 | ✅ |
| Debian 10 | ✅ |
| Debian | ✅ |

---

# 👤 User Commands

| Command | Description |
|---------|-------------|
| `$about` | Display VPS engine information |
| `$myvps` | View all your VPS instances |
| `$manage` | VPS management guide |
| `$ping` | Check bot latency |
| `$help` | Display all commands |

---

# 👑 Administrator Commands

| Command | Description |
|---------|-------------|
| `$create <ram> <cpu> <disk> <os> <@user>` | Create a VPS |
| `$list` | List every VPS |
| `$system` | Host CPU, RAM & Disk usage |
| `$start vps <id>` | Start VPS |
| `$restart vps <id>` | Restart VPS |
| `$deletevps <id>` | Delete VPS |
| `$create-admin <@user>` | Add Bot Admin |
| `$delete-admin <@user>` | Remove Bot Admin |
| `$antinuke <enable/disable>` | Enable or Disable Anti-Nuke |
| `$reset` | Wipe every VPS (Confirmation Required) |

---

# 📦 Manual Installation

### 1️⃣ Clone Repository

```bash
git clone https://github.com/SKYDO234/SDC-botv2.git

cd SDC-botv2
```

### 2️⃣ Update Packages

```bash
apt update
```

### 3️⃣ Install Python

```bash
apt install python3
```

### 4️⃣ Install Pip

```bash
apt install python3-pip
```

### 5️⃣ Install Node Modules

```bash
npm i
```

### 6️⃣ Install Python Requirements

```bash
pip install -r requirements.txt
```

If the above command fails:

```bash
python3 -m pip install --break-system-packages -r requirements.txt
```

---

# ⚙️ Configuration

Open **config.json** and edit:

```python
BOT_TOKEN = "YOUR_BOT_TOKEN"

PREFIX = "$"

ADMIN_ID = YOUR_DISCORD_ID
```

---

# ▶️ Start The Bot

```bash
python3 bot2.py
```

---

# 📊 VPS Information

Every VPS contains:

- 🆔 VPS ID
- 🐧 Operating System
- 💾 RAM
- 🖥 CPU
- 💿 Disk
- 📡 Status
- 👤 Owner

---

# ⚠️ Important

> The `$reset` command permanently deletes every VPS and the database.
>
> You must type **CONFIRM** within **15 seconds** before execution.

---

# 📁 Project Structure

```
SDC-botv2
│
├── bot.py
├── requirements.txt
├── database.db
├── README.md
└── ...
```

---

# ❤️ Credits

**Developer:** SKYDO234

Discord VPS Management System

---

<div align="center">

## ⭐ Star this repository if you like this project!

Made with ❤️ by **SKYDO234**

</div>
