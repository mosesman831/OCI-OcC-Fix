# Oracle Cloud Infrastructure Out of Capacity Error

Fix for Oracle Cloud Infrastructure Out of Capacity error.
[![Oracle Cloud Infrastructure](https://img.shields.io/badge/Oracle%20Cloud%20Infrastructure-Out%20of%20Capacity%20Fix-blueviolet?labelColor=black&style=flat-square&link=https://github.com/mosesman831/OCI-OcC-Fix)](https://github.com/mosesman831/OCI-OcC-Fix)
[![Currently](https://img.shields.io/badge/Currently-Working-blueviolet?labelColor=black&style=flat-square&link=https://github.com/mosesman831/OCI-OcC-Fix)](https://github.com/mosesman831/OCI-OcC-Fix)
[![GitHub release](https://img.shields.io/github/release/mosesman831/OCI-OcC-Fix?include_prereleases=&sort=semver&color=blueviolet&style=flat-square)](https://github.com/mosesman831/OCI-OcC-Fix/releases/)
[![dependency - Python](https://img.shields.io/badge/dependency-Python-blueviolet?style=flat-square)](https://github.com/mosesman831/OCI-OcC-Fix/releases/)


>[Made by Moses](https://github.com/mosesman831/OCI-OcC-Fix.git)
>### If you appreciate what I do please [![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/R6R1VPIGM)



#### Skip to Section
[Installation](#installation)
[Configuration](#configuration)
[How to use](#how-to-use)

# Installation
## One Command Install
```
git clone https://github.com/mosesman831/OCI-OcC-Fix.git && cd OCI-OcC-Fix && pip install -r requirements.txt
```
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
Install requirements and dependicies
```bash
pip install -r requirements.txt
```

## Using Releases
Open [Releases](https://github.com/mosesman831/OCI-OcC-Fix/releases) and download latest

Install required dependicies
```bash
pip install -r requirements.txt
```

## wget / cURL
Install unzip if not already installed.
```
sudo apt-get install unzip
```
**wget**
```bash
wget https://github.com/mosesman831/OCI-OcC-Fix/archive/refs/heads/main.zip && unzip main.zip && mv main OCI-OcC-Fix 
```
**cURL**
```bash
curl -X GET https://github.com/mosesman831/OCI-OcC-Fix/archive/refs/heads/main.zip && unzip main.zip && mv main OCI-OcC-Fix
```
Install required dependicies
```bash
pip install -r requirements.txt
```

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
> Pro Tip
> You could use `nano` to edit the files easier.

## Getting Telegram Bot ID
### Step 1
Open Telegram and message @BotFather
### Step 2
Send `/newbot`
### Step 3
Enter name and username
### Step 4
Get Bot ID
### Step 5
Message @Rose-Bot
### Step 6
Send `/id`
### Step 7
Get userid

## Getting Oracle Cloud cURL
### Step 1
Create an instance from from the OCI Console in the browser (Menu -> Compute -> Instances -> Create Instance)
### Step 2
Change image and shape.
### Step 3
Adjust Networking section, set "Do not assign a public IPv4 address" checkbox. If you don't have existing VNIC/subnet, please create VM.Standard.E2.1.Micro instance before doing everything.
### Step 4
Download and save the public and private SSH key.
### Step 5
Click `Ctrl + Shift + I` or `F12` to open browser's dev tools -> network tab
### Step 6
Click Create and see if you get the **Out of capacity** error. Now find /instances API call (red).
### Step 7
Right click on it -> copy as curl (bash/cmd). Paste the clipboard contents in any text editor.
### Step 8
Open bot.py in a a text editor.
### Step 9
Find the variables and replace the `xxxx` fields respectively.
```bot.py
availabilityDomains = ["xxxx"]
#e.g. availabilityDomains = ["KHsT:UK-MANCHESTER-1-AD-1","KHsT:UK-MANCHESTER-1-AD-2"]
displayName = 'xxxx'
#e.g. displayName = 'VPS1'
compartmentId = 'xxxx'
#e.g. compartmentId = 'ocid1.tenancy.oc1..aaaaaaaa...'
subnetId = 'xxxx'
#e.g. subnetId = 'ocid1.subnet.oc1.uk-manchester-1.aaaaaaa...'
ssh_authorized_keys = "xxxx"
#e.g. ssh_authorized_keys = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQDf... ssh-key-2024-03-15"
boot_volume_size_in_gbs="xxxx"
#Leave blank for default
#e.g. boot_volume_size_in_gbs="47"
boot_volume_id="xxxx"
#e.g. boot_volume_id="ocid1.bootvolume.oc1.uk-manchester-1.aaaaaaa..."
```
# How to use?
Run`bot.py` by double-clicking or running
```
python bot.py
``` 
```
python3 bot.py
```
## Run on SSH
### One Command SSH
```bash
tmux new && python3 bot.py
```

Use `tmux` to  keep window running even after logout.
```bash
tmux new
```
