
# OCI OcC v2.1.0-BETA
> [!TIP]
> This is currently in beta, you might experience bugs.
> Please report any issues in ISSUES.

Fix for Oracle Cloud Infrastructure Out of Capacity error.
[![Oracle Cloud Infrastructure](https://img.shields.io/badge/Oracle%20Cloud%20Infrastructure-Out%20of%20Capacity%20Fix-blueviolet?labelColor=black&style=flat-square&link=https://github.com/mosesman831/OCI-OcC-Fix)](https://github.com/mosesman831/OCI-OcC-Fix)
[![Version](https://img.shields.io/badge/Version-2.1.0BETA-blueviolet?labelColor=black&style=flat-square&link=https://github.com/mosesman831/OCI-OcC-Fix)](https://github.com/mosesman831/OCI-OcC-Fix)
[![GitHub release](https://img.shields.io/github/release/mosesman831/OCI-OcC-Fix?include_prereleases=&sort=semver&color=blueviolet&style=flat-square)](https://github.com/mosesman831/OCI-OcC-Fix/releases/)
[![dependency - Python](https://img.shields.io/badge/dependency-Python-blueviolet?style=flat-square)](https://github.com/mosesman831/OCI-OcC-Fix/releases/)


>[Made by Moses](https://github.com/mosesman831/OCI-OcC-Fix.git)
>### If you appreciate what I do please [![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/R6R1VPIGM)



#### Skip to Section
[Installation](#installation)
[Configuration](#configuration)
[How to use](#how-to-use)
[In Use](#in-use)
[Show your support❤️](#show-your-support-%EF%B8%8F)
[Contributors](#contributors)



# Installation
## One Command Install
```
git clone https://github.com/mosesman831/OCI-OcC-Fix.git && cd OCI-OcC-Fix && pip install -r requirements.txt
```
> [!TIP]
> Use the One Command Install to setup quickly
## Using Git
### Step 1
Run Git Clone.
```bash
git clone https://github.com/mosesman831/OCI-OcC-Fix.git
```
### Step 2
Enter the folder.
```bash
cd OCI-OcC-Fix
```
### Step 3
Install requirements and dependencies
```bash
pip install -r requirements.txt
```

## Using Releases
Open [Releases](https://github.com/mosesman831/OCI-OcC-Fix/releases) and download V2 Beta

Install required dependencies
```bash
pip install -r requirements.txt
```

## wget
Install unzip if not already installed.
```
sudo apt-get install unzip
```
**wget**
```bash
wget https://github.com/mosesman831/OCI-OcC-Fix/archive/refs/heads/main.zip && unzip main.zip && mv OCI-OcC-Fix-main OCI-OcC-Fix && rm main.zip
```
Install required dependencies
```bash
pip install -r requirements.txt
```

## Docker
### Step 1
Build the Docker Container
```bash
sudo docker compose build
```
### Step 2
Start Docker Containers
```bash
sudo docker compose up -d
```

### Step 3
View Container Logs
```bash
sudo docker logs -f <cotainer>
```

## Run on 3rd Party containers
Not yet added.


# Configuration
## Getting Oracle Cloud API
### Step 1
Open [Oracle Cloud](cloud.oracle.com) and log in.
### Step 2
Click profile icon and then "My Profile / User Settings"
### Step 3
Find API keys, click "Add API Key" button
### Step 4
Click "Download Private Key" and then "Add". Save the file as `oci_private_key.pem`
### Step 5
Copy the contents from the Text Box and save it to file `config`.
> [!TIP]
> You could use `nano` to edit the files easier.

## Getting Telegram Bot ID
### Step 1
Open Telegram and message @BotFather
### Step 2
Send `/newbot`
### Step 3
Enter name and username
### Step 4
Message @Rose-Bot to get User ID ("uid")
### Step 5
Send `/id`
### Step 6
Get userid

## Getting Oracle Cloud cURL
### Step 1
Create an instance from the OCI Console in the browser (Menu -> Compute -> Instances -> Create Instance)
### Step 2
Change image and shape.
### Step 3
Adjust the Networking section, and set the "Do not assign a public IPv4 address" checkbox. If you don't have an existing VNIC/subnet, please create a VM.Standard.E2.1.Micro instance before doing everything.
### Step 4
Download and save the public and private SSH keys.
### Step 5
Click Ctrl + Shift + I or F12 to open browser's dev tools -> network tab
### Step 6
Click Create and see if you get the Out of capacity error. Now find /instances API call (red).
### Step 7
Right-click on it -> copy as curl (bash/cmd). Paste the clipboard contents in any text editor.
### Step 8
Create a `.env` file in the same directory as your script and add the following environment variables:
```
OCI_IMAGE_ID=your_image_id
OCI_AVAILABILITY_DOMAINS=your_availability_domains
OCI_DISPLAY_NAME=your_display_name
OCI_COMPARTMENT_ID=your_compartment_id
OCI_SUBNET_ID=your_subnet_id
OCI_SSH_AUTHORIZED_KEYS=your_ssh_keys
OCI_BOOT_VOLUME_SIZE_IN_GBS=your_volume_size
OCI_BOOT_VOLUME_ID=your_volume_id
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_UID=your_uid
MACHINE_TYPE=ARM
```
# How to use?
Run `bot.py` by double-clicking or running
```py
python bot.py
``` 
```py
python3 bot.py
```
## Run on SSH
### One Command SSH
```bash
tmux new && python3 bot.py
```
### Tmux
Use `tmux` to  keep window running even after logout.
```bash
tmux new
```

# In Use

## Success
### Success Picture in Console
Prerelease Prototype
![Success Picture](https://github.com/mosesman831/OCI-OcC-Fix/blob/main/.github/images/success.png?raw=true)


# Show your support ❤️
### If you appreciate what I do, please 

### Star this project
### or
### Support me on Ko-fi!

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/R6R1VPIGM)

#### Thanks for supporting!

# Contributors

<!-- ALL-CONTRIBUTORS-LIST:START - Do not remove or modify this section -->
<!-- prettier-ignore-start -->
<!-- markdownlint-disable -->
<table>
  <tbody>
    <tr>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/Unlifate"><img src="https://avatars.githubusercontent.com/u/4685835?v=4?s=100" width="100px;" alt="Peter Eisenschmidt"/><br /><sub><b>Peter Eisenschmidt</b></sub></a><br /><a href="#code-Unlifate" title="Code">💻</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/aldacco"><img src="https://avatars.githubusercontent.com/u/86637158?v=4?s=100" width="100px;" alt="aldacco"/><br /><sub><b>aldacco</b></sub></a><br /><a href="#code-aldacco" title="Code">💻</a> <a href="#doc-aldacco" title="Documentation">📖</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://zege.rs"><img src="https://avatars.githubusercontent.com/u/110392702?v=4?s=100" width="100px;" alt="Joery Zegers"/><br /><sub><b>Joery Zegers</b></sub></a><br /><a href="#code-Joery" title="Code">💻</a></td>
    </tr>
  </tbody>
</table>

<!-- markdownlint-restore -->
<!-- prettier-ignore-end -->

<!-- ALL-CONTRIBUTORS-LIST:END -->


---
