# Linux Full Setup and Run Example

This example demonstrates the full setup and run process for the OCI-OcC-Fix project in a Linux (Ubuntu) terminal. It includes the one command quick install, editing the `configuration.ini` file with nano, and executing the script with `python3 bot.py`.

## Quick Install

```shell
$ git clone https://github.com/mosesman831/OCI-OcC-Fix.git && cd OCI-OcC-Fix && pip install -r requirements.txt
Cloning into 'OCI-OcC-Fix'...
remote: Enumerating objects: 100, done.
remote: Counting objects: 100% (100/100), done.
remote: Compressing objects: 100% (80/80), done.
remote: Total 100 (delta 20), reused 60 (delta 10), pack-reused 0
Receiving objects: 100% (100/100), 20.00 KiB | 1.00 MiB/s, done.
Resolving deltas: 100% (20/20), done.
Collecting requests
  Downloading requests-2.25.1-py2.py3-none-any.whl (61 kB)
Collecting oci
  Downloading oci-2.45.0-py2.py3-none-any.whl (1.8 MB)
Collecting pyTelegramBotAPI
  Downloading pyTelegramBotAPI-3.8.2.tar.gz (47 kB)
Collecting configparser
  Downloading configparser-5.0.2-py3-none-any.whl (19 kB)
Collecting python-dotenv
  Downloading python_dotenv-0.17.1-py2.py3-none-any.whl (18 kB)
Installing collected packages: requests, oci, pyTelegramBotAPI, configparser, python-dotenv
Successfully installed configparser-5.0.2 oci-2.45.0 pyTelegramBotAPI-3.8.2 python-dotenv-0.17.1 requests-2.25.1
```

## Edit Configuration

```shell
$ nano configuration.ini
```

Edit the `configuration.ini` file with the following values:

```ini
[OCI]
image_id = ocid1.image.oc1.eu-frankfurt-1.aaaaaaaaonnh....
availability_domains = ["KHsT:UK-MANCHESTER-1-AD-1","KHsT:UK-MANCHESTER-1-AD-2"]
compartment_id = ocid1.tenancy.oc1..aaaaaaaa...
subnet_id = ocid1.subnet.oc1.uk-manchester-1.aaaaaaa...
boot_volume_id = ocid1.bootvolume.oc1.uk-manchester-1.aaaaaaa...

[Instance]
display_name = TestVM
ssh_keys = ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQDf... ssh-key-2024-03-15
boot_volume_size = 50

[Telegram]
bot_token = 123456789:AAFmw4Vx0iA-xxxxxxxxx
uid = 987654321

[Machine]
type = ARM
shape = VM.Standard.A1.Flex
ocpus = 4
memory = 24

[Retry]
min_interval = 1
max_interval = 30
initial_retry_interval = 1
backoff_factor = 1.5

[Logging]
log_level = INFO
```

Save the file and exit nano.

## Execute Script

```shell
$ python3 bot.py
[INFO] 2023-03-15 10:00:00 - OCI-OcC-Fix Started
[INFO] 2023-03-15 10:00:00 - Account: example_account
[INFO] 2023-03-15 10:00:00 - User: example_user@example.com
[INFO] 2023-03-15 10:00:00 - Retry Interval: 1s
[INFO] 2023-03-15 10:00:00 - Machine: VM.Standard.A1.Flex
[WARNING] 2023-03-15 10:00:01 - Create failed in KHsT:UK-MANCHESTER-1-AD-1: Out of capacity
[INFO] 2023-03-15 10:00:01 - Next retry in 1.5s
[WARNING] 2023-03-15 10:00:02 - Create failed in KHsT:UK-MANCHESTER-1-AD-2: Out of capacity
[INFO] 2023-03-15 10:00:02 - Next retry in 2.25s
...
[INFO] 2023-03-15 10:01:00 - Instance created successfully! Public IP: 192.168.1.100
[INFO] 2023-03-15 10:01:00 - Instance Ready!
[INFO] 2023-03-15 10:01:00 - IP: 192.168.1.100
[INFO] 2023-03-15 10:01:00 - Retries: 27
```
