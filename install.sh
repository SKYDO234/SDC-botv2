#!/bin/bash

# ============================================
#        SKYDO VPS BOT V2 INSTALLER
# ============================================

clear

# Colors
RED='\033[1;31m'
GREEN='\033[1;32m'
CYAN='\033[1;36m'
BLUE='\033[1;34m'
MAGENTA='\033[1;35m'
YELLOW='\033[1;33m'
WHITE='\033[1;37m'
NC='\033[0m'

echo -e "${CYAN}"
cat << "EOF"

███████╗██╗  ██╗██╗   ██╗██████╗  ██████╗     ██╗   ██╗████████╗
██╔════╝██║ ██╔╝╚██╗ ██╔╝██╔══██╗██╔═══██╗    ╚██╗ ██╔╝╚══██╔══╝
███████╗█████╔╝  ╚████╔╝ ██║  ██║██║   ██║     ╚████╔╝    ██║
╚════██║██╔═██╗   ╚██╔╝  ██║  ██║██║   ██║      ╚██╔╝     ██║
███████║██║  ██╗   ██║   ██████╔╝╚██████╔╝       ██║      ██║
╚══════╝╚═╝  ╚═╝   ╚═╝   ╚═════╝  ╚═════╝        ╚═╝      ╚═╝
      ╚═══╝  ╚═╝     ╚══════╝

██████╗  ██████╗ ████████╗    ██╗███╗   ██╗███████╗████████╗ █████╗ ██╗     ██╗     ███████╗██████╗
██╔══██╗██╔═══██╗╚══██╔══╝    ██║████╗  ██║██╔════╝╚══██╔══╝██╔══██╗██║     ██║     ██╔════╝██╔══██╗
██████╔╝██║   ██║   ██║       ██║██╔██╗ ██║███████╗   ██║   ███████║██║     ██║     █████╗  ██████╔╝
██╔══██╗██║   ██║   ██║       ██║██║╚██╗██║╚════██║   ██║   ██╔══██║██║     ██║     ██╔══╝  ██╔══██╗
██████╔╝╚██████╔╝   ██║       ██║██║ ╚████║███████║   ██║   ██║  ██║███████╗███████╗███████╗██║  ██║
╚═════╝  ╚═════╝    ╚═╝       ╚═╝╚═╝  ╚═══╝╚══════╝   ╚═╝   ╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝╚═╝  ╚═╝

EOF
echo -e "${NC}"

echo -e "${GREEN}============================================================${NC}"
echo -e "${WHITE}             SKYDO VPS BOT INSTALLER${NC}"
echo -e "${CYAN}         Professional Automatic Installer${NC}"
echo -e "${GREEN}============================================================${NC}"
echo

echo -e "${YELLOW}[1/6] Cloning Repository...${NC}"
git clone https://github.com/SKYDO234/SDC-botv2.git

echo -e "${YELLOW}[2/6] Opening Project...${NC}"
cd SDC-botv2 || cd SDC-botv2 || exit

echo -e "${YELLOW}[3/6] Updating Packages...${NC}"
apt update -y

echo -e "${YELLOW}[4/6] Installing Pip...${NC}"
apt install -y python3-pip

echo -e "${YELLOW}[5/6] Installing Python Requirements...${NC}"
python3 -m pip install --break-system-packages -r requirements.txt

echo
echo -e "${GREEN}============================================================${NC}"
echo -e "${CYAN}Before starting the bot:${NC}"
echo
echo -e "${WHITE}✔ Fill your TOKEN${NC}"
echo -e "${WHITE}✔ Fill your GUILD ID${NC}"
echo -e "${WHITE}✔ Fill your ADMIN ID${NC}"
echo
echo -e "${YELLOW}Edit:${NC} config.json"
echo
echo -e "${GREEN}When finished, type: yes${NC}"
echo -e "${GREEN}============================================================${NC}"

while true; do
    read -p "Have you filled config.json? (yes): " answer
    if [[ "$answer" == "yes" ]]; then
        break
    else
        echo -e "${RED}Please complete config.json first.${NC}"
    fi
done

echo
echo -e "${GREEN}Launching SKYDO VPS BOT...${NC}"
sleep 2

python3 bot.py
