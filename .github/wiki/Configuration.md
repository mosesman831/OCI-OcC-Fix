# Configuration

## File Setup

Configure settings using the guide below in configuration.ini

### OCI Configuration ([OCI] Section)
#### Step 1
Create an instance from the OCI Console in the browser (Menu -> Compute -> Instances -> Create Instance)
#### Step 2
Change image and shape.
#### Step 3
Adjust the Networking section, and set the "Do not assign a public IPv4 address" checkbox. If you don't have an existing VNIC/subnet, please create a VM.Standard.E2.1.Micro instance before doing anything.
#### Step 4
Download and save the public and private SSH keys.
#### Step 5
Click `Ctrl + Shift + I` or `F12` to open browser's dev tools -> network tab
#### Step 6
Click Create and see if you get the **Out of capacity** error. Now find /instances API call (red).
#### Step 7
Right-click on it -> copy as curl (bash/cmd). Paste the clipboard contents in any text editor.
#### Step 8
Open configuration.ini in a text editor.
#### Step 9
Find the variables and replace the fields respectively.

```ini
[OCI]
; EXAMPLE: ocid1.image.oc1.eu-frankfurt-1.aaaaaaaaonnh.... | Base image OCID
image_id = 
; EXAMPLE: ["KHsT:UK-MANCHESTER-1-AD-1","KHsT:UK-MANCHESTER-1-AD-2"] | Your region's availability domains
availability_domains = 
; EXAMPLE: ocid1.tenancy.oc1..aaaaaaaa... | Target compartment OCID
compartment_id = 
; EXAMPLE: ocid1.subnet.oc1.uk-manchester-1.aaaaaaa... | Network subnet OCID
subnet_id = 
; EXAMPLE: ocid1.bootvolume.oc1.uk-manchester-1.aaaaaaa... | (Optional) Existing boot volume OCID
boot_volume_id = 
```
### Instance Settings ([Instance] Section)
#### Settings
Change the settings to accommodate required instance settings.
```ini
[Instance]
; EXAMPLE: OCI-ARM-01 | Unique instance name
display_name = 
; EXAMPLE: ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQDf... ssh-key-2024-03-15 | Your public SSH key
ssh_keys = 
; EXAMPLE: 50 | Boot volume size in GB (47-200)
boot_volume_size = 
```
### Telegram Integration ([Telegram] Section)
#### Step 1
Open Telegram and message @BotFather
#### Step 2
Send `/newbot`
#### Step 3
Enter name and username
#### Step 4
Message @Rose-Bot to get User ID ("uid")
#### Step 5
Send `/id`
#### Step 6
Get userid
#### Step 7
Find the variables and replace the fields respectively.
```ini
[Telegram]
; EXAMPLE: 123456789:AAFmw4Vx0iA-xxxxxxxxx | Bot token from @BotFather
bot_token = 
; EXAMPLE: 987654321 | Your Telegram user ID
uid = 
```
### Machine Configuration ([Machine] Section)
#### Settings
Change the settings to accommodate required machine configuration.

```ini
[Machine]
; EXAMPLE: ARM | ARM or AMD
type = 
; EXAMPLE: VM.Standard.A1.Flex | Compute shape
shape = 
; EXAMPLE: 4 | OCPUs (1-4 for ARM)
ocpus = 
; EXAMPLE: 24 | Memory in GB (6-24 for ARM)
memory = 
```
### Retry Settings ([Retry] Section)
> [!TIP]
> It is recommended you do not edit these variables, they have been tested and proved to work the best.
#### Settings
Change the settings to accommodate required retry settings.
```ini
[Retry]
; EXAMPLE: 1 | Minimum wait (seconds) | RECOMMENDED
min_interval = 1
; EXAMPLE: 60 | Maximum wait (seconds) | RECOMMENDED
max_interval = 30
; EXAMPLE: 1 | Initial retry delay (seconds) | RECOMMENDED
initial_retry_interval = 1
; EXAMPLE: 1.5 | Backoff multiplier | | RECOMMENDED
backoff_factor = 1.5
```
### Logging Settings ([Logging] Section)
#### Settings
Change the settings to accommodate required instance settings.
```ini
[Logging]
; EXAMPLE: INFO | DEBUG/INFO/WARNING/ERROR | RECOMMENDED
log_level = INFO
```

### OCI API Setup

1.  Create API Key in OCI Console
    
2.  Download private key as  `oci_private_key.pem`
    
3.  Copy the contents from the Text Box and save it to file `config`.
    
