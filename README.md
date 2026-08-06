# 🚀 SDC BOT V2

A powerful Discord VPS Management Bot built with Python, designed to create, manage, and monitor Linux VPS containers directly from Discord.

---

# ✨ Features

- ⚡ Instant VPS creation
- 🐧 Multiple Linux distributions
- 📊 Live system monitoring
- 🔒 Admin permission system
- 🛡️ Anti-Nuke protection
- 👤 User VPS management
- 💾 SQLite database support
- 🚀 Fast and lightweight

---

# 📋 Commands

# 👤 User Commands

"$about"

Displays information about the VPS engine, architecture, and supported Linux distributions.

"$myvps"

Shows all VPS instances assigned to your Discord account, including:

- VPS ID
- Operating System
- CPU
- RAM
- Disk
- Status

"$manage"

Displays the VPS management guide and connection information.

"$ping"

Shows the bot latency.

"$help"

Displays all available commands.

---

# 👑 Administrator Commands

«Only Bot Admins & Server Administrators can use these commands.»

"$create <ram> <cpu> <disk> <os> <@user>"

Creates a new VPS.

Example:

$create 1g 1 10g UBUNTU20.04 @User

# Supported Operating Systems:

- UBUNTU22.04
- UBUNTU20.04
- DEBIAN10
- DEBIAN

---

"$list"

Displays every VPS registered in the database.

---

"$system"

Displays host machine statistics:

- CPU Usage
- RAM Usage
- Disk Usage

---

"$start vps <vps_id>"

Starts a stopped VPS.

Example:

$start vps ABC123XYZ0

---

"$restart vps <vps_id>"

Restarts a running VPS.

---

"$deletevps <vps_id>"

Stops, deletes and removes a VPS from the database.

---

"$create-admin <@user>"

Grants bot administrator permissions.

---

"$delete-admin <@user>"

Removes bot administrator permissions.

---

"$antinuke <enable|disable>"

Enables or disables the built-in Anti-Nuke protection.

---

"$reset"

WARNING

Completely wipes every VPS and deletes the database.

The bot will require CONFIRM within 15 seconds before executing.

---

# 💻 Installation

Clone the repository:

## git clone https://github.com/SKYDO234/SDC-botv2.git

Move into the project folder:

cd SDC-botv2

Update packages:

apt update

Install Python:

apt install python3

Install pip:

apt install python3-pip

Install Node packages:

npm i

Install Python requirements:

pip install -r requirements.txt

If the above command does not work, run:

python3 -m pip install --break-system-packages -r requirements.txt

---

# ⚙️ Configuration

Open config.json and configure the following values:

- Discord Bot Token
- Bot Prefix
- Admin Discord ID

---

# ▶️ Start the Bot

python3 bot.py

---

# 🐧 Supported Linux Distributions

- Ubuntu 22.04
- Ubuntu 20.04
- Debian 10
- Debian

---

# 📜 License

This project is intended for educational and personal hosting purposes.

---

# ⭐ Developed by SKYDO_XD

If you enjoy this project, consider giving the repository a ⭐ Star on GitHub!
