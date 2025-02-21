# Example Run

This example demonstrates running `bot.py` to spawn an instance called `TestVM`. The configuration values are filled in the `configuration.ini` file, and the logging mode is set to INFO. The script runs around 27 times before successfully spawning the instance.

## Configuration

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

## Shell Output

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

## Docker Run

```shell
$ docker compose up -d --build
[+] Running 2/2
 ⠿ Network oci-occ-fix_default  Created
 ⠿ Container oci-occ-fix       Started
$ docker logs -f oci-occ-fix
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
