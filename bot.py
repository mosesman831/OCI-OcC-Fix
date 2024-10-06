#Oracle Cloud Infrastructure (OCI) - Create VPS instance
#Fix for Out of Capacity Error
#Made by @mosesman831
#https://github.com/mosesman831
#https://github.com/mosesman831/OCI-OcC-Fix
#OCI OcC
#Out of Capacity Fix by @mosesman831
#VERSION 1.1 (BETA 10)



import oci
import logging
import time
import sys
import telebot
import datetime

# Configuration
version = "10.1.1"
imageId = 'xxxx'
availabilityDomains = ["xxxx"]
displayName = 'xxxx'
compartmentId = 'xxxx'
subnetId = 'xxxx'
ssh_authorized_keys = "xxxx"
boot_volume_size_in_gbs = "xxxx"
boot_volume_id = "xxxx"
bot_token = "xxxx"
uid = "xxxx"
machine = "ARM"  # Options: "ARM" or "AMD"

# Set machine configurations
if machine == "ARM":
    ocpus = 4
    memory_in_gbs = 24
    mname = "VM.Standard.A1.Flex"
else:
    ocpus = 1
    memory_in_gbs = 1
    mname = "VM.Standard.E2.1.Micro"

minimum_time_interval = 1

# Initialize logging
LOG_FORMAT = '[%(levelname)s] %(asctime)s - %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, handlers=[logging.StreamHandler(sys.stdout)])

# Initialize bot
bot = telebot.TeleBot(bot_token)

logging.info("#####################################################")
logging.info("Welcome to OCI OcC Fix by Moses")
logging.info(f"Spawning {machine} instance {mname}")
logging.info("Made by Moses")
logging.info("https://github.com/mosesman831/OCI-OcC-Fix")
logging.info(f"Version {version}")
logging.info("#####################################################")

def log_and_send_message(message):
    logging.info(message)
    if bot_token != "xxxx" and uid != "xxxx":
        try:
            bot.send_message(uid, message)
        except Exception as e:
            logging.error(f"Failed to send message: {e}")

log_and_send_message(f'Start spawning instance {mname} - {ocpus} OCPUs - {memory_in_gbs} GB')

# Load OCI configuration
config = oci.config.from_file(file_location="./config")

# Initialize OCI clients
compute_client = oci.core.ComputeClient(config)
identity_client = oci.identity.IdentityClient(config)
vnc_client = oci.core.VirtualNetworkClient(config)
volume_client = oci.core.BlockstorageClient(config)

cloud_name = identity_client.get_tenancy(tenancy_id=compartmentId).data.name
email = identity_client.list_users(compartment_id=compartmentId).data[0].email

def check_storage_capacity():
    total_volume_size = 0
    if imageId != "xxxx":
        list_volumes = volume_client.list_volumes(compartment_id=compartmentId).data
        total_volume_size += sum(v.size_in_gbs for v in list_volumes if v.lifecycle_state not in ("TERMINATING", "TERMINATED"))
        
        for ad in availabilityDomains:
            list_boot_volumes = volume_client.list_boot_volumes(availability_domain=ad, compartment_id=compartmentId).data
            total_volume_size += sum(bv.size_in_gbs for bv in list_boot_volumes if bv.lifecycle_state not in ("TERMINATING", "TERMINATED"))
        
        free_storage = 200 - total_volume_size
        required_storage = int(boot_volume_size_in_gbs) if boot_volume_size_in_gbs != "xxxx" else 47
        
        if free_storage < required_storage:
            logging.critical(f"Not enough storage: {free_storage} GB available, {required_storage} GB needed. **SCRIPT STOPPED**")
            sys.exit()

check_storage_capacity()

def check_instance_resources():
    current_instance = compute_client.list_instances(compartment_id=compartmentId)
    response = current_instance.data

    total_ocpus = total_memory = 0
    instance_names = []

    if response:
        logging.info(f"{len(response)} instance(s) found!")
        for instance in response:
            logging.info(f"{instance.display_name} - {instance.shape} - {int(instance.shape_config.ocpus)} OCPU(s) - {instance.shape_config.memory_in_gbs} GB(s) | State: {instance.lifecycle_state}")
            instance_names.append(instance.display_name)
            if instance.shape == "VM.Standard.A1.Flex" and instance.lifecycle_state not in ("TERMINATING", "TERMINATED"):
                total_ocpus += int(instance.shape_config.ocpus)
                total_memory += int(instance.shape_config.memory_in_gbs)

    logging.info(f"Total OCPUs: {total_ocpus} - Total memory: {total_memory} GB || Free {4 - total_ocpus} OCPUs - Free memory: {24 - total_memory} GB")

    if total_ocpus + ocpus > 4 or total_memory + memory_in_gbs > 24:
        logging.critical("Exceeded free tier limits (Over 4 OCPUs/24GB total). **SCRIPT STOPPED**")
        sys.exit()

    if displayName in instance_names:
        logging.critical(f"Duplicate display name: {displayName}. **SCRIPT STOPPED**")
        sys.exit()

check_instance_resources()

def create_instance():
    source_details = oci.core.models.InstanceSourceViaImageDetails(
        source_type="image", image_id=imageId) if imageId != "xxxx" else None

    if boot_volume_id != "xxxx":
        source_details = oci.core.models.InstanceSourceViaBootVolumeDetails(
            source_type="bootVolume", boot_volume_id=boot_volume_id)

    instance_detail = oci.core.models.LaunchInstanceDetails(
        metadata={"ssh_authorized_keys": ssh_authorized_keys},
        availability_domain=availabilityDomains[0],
        shape='VM.Standard.A1.Flex',
        compartment_id=compartmentId,
        display_name=displayName,
        is_pv_encryption_in_transit_enabled=True,
        source_details=source_details,
        create_vnic_details=oci.core.models.CreateVnicDetails(assign_public_ip=True, subnet_id=subnetId),
        shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(ocpus=ocpus, memory_in_gbs=memory_in_gbs)
    )

    return instance_detail

def launch_instance():
    wait_s_for_retry = 1
    total_count = 0
    j_count = 0

    while True:
        instance_detail = create_instance()
        
        try:
            launch_instance_response = compute_client.launch_instance(instance_detail)
            time.sleep(60)

            vnic_attachments = compute_client.list_vnic_attachments(compartment_id=compartmentId, instance_id=launch_instance_response.data.id)
            private_ips = vnc_client.list_private_ips(subnet_id=subnetId, vnic_id=vnic_attachments.data[0].vnic_id)
            public_ip = vnc_client.get_public_ip_by_private_ip_id(oci.core.models.GetPublicIpByPrivateIpIdDetails(private_ip_id=private_ips.data[0].id)).data.ip_address

            total_count += 1
            logging.info(f'"{displayName}" VPS {mname} created successfully! IP: {public_ip}')
            log_and_send_message(f'"{displayName}" VPS created successfully!\nIP: {public_ip}')

            sys.exit()

        except oci.exceptions.ServiceError as e:
            total_count += 1
            j_count += 1
            if j_count == 10:
                j_count = 0
                log_and_send_message(f"Bot is still running. Checked at: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

            message = f'{e.status} - {e.code} - {e.message}. Retrying after {wait_s_for_retry} seconds. Number of Retry: {total_count}'
            logging.info(message)

            if e.status == 429:
                wait_s_for_retry += 1
            else:
                wait_s_for_retry = max(minimum_time_interval, wait_s_for_retry - 1)

            time.sleep(wait_s_for_retry)

        except Exception as e:
            logging.error(f"Unexpected error: {e}")
            sys.exit()

launch_instance()
