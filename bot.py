# Oracle Cloud Infrastructure (OCI) - Create VPS instance
# Fix for Out of Capacity Error
# Made by @mosesman831
# https://github.com/mosesman831
# https://github.com/mosesman831/OCI-OcC-Fix
# Out of Capacity Fix by @mosesman831
# VERSION 2.1.2-beta

import oci
import logging
import time
import sys
import telebot
import datetime
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configuration
VERSION = "10.1.1"
IMAGE_ID = os.getenv('OCI_IMAGE_ID', 'default_image_id')
AVAILABILITY_DOMAINS = os.getenv('OCI_AVAILABILITY_DOMAINS', 'default_domain').split(',')
DISPLAY_NAME = os.getenv('OCI_DISPLAY_NAME', 'default_display_name')
COMPARTMENT_ID = os.getenv('OCI_COMPARTMENT_ID', 'default_compartment_id')
SUBNET_ID = os.getenv('OCI_SUBNET_ID', 'default_subnet_id')
SSH_AUTHORIZED_KEYS = os.getenv('OCI_SSH_AUTHORIZED_KEYS', 'default_ssh_keys')
BOOT_VOLUME_SIZE_IN_GBS = os.getenv('OCI_BOOT_VOLUME_SIZE_IN_GBS', 'default_volume_size')
BOOT_VOLUME_ID = os.getenv('OCI_BOOT_VOLUME_ID', 'default_volume_id')
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'default_bot_token')
UID = os.getenv('TELEGRAM_UID', 'default_uid')
MACHINE = os.getenv('MACHINE_TYPE', 'ARM')  # Options: "ARM" or "AMD"

# Set machine configurations
def get_machine_config(machine: str) -> dict:
    if machine == "ARM":
        return {
            "ocpus": 4,
            "memory_in_gbs": 24,
            "mname": "VM.Standard.A1.Flex"
        }
    else:
        return {
            "ocpus": 1,
            "memory_in_gbs": 1,
            "mname": "VM.Standard.E2.1.Micro"
        }

machine_config = get_machine_config(MACHINE)

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[
    logging.FileHandler("occlog.txt"),
    logging.StreamHandler()
])
logger = logging.getLogger(__name__)

logger.info(f"Starting OCI instance creation script version {VERSION}")
logger.info(f"Using machine configuration: {machine_config}")

# Initialize OCI clients
logger.debug("Initializing OCI clients...")
compute_client = oci.core.ComputeClient(oci.config.from_file())
vnc_client = oci.core.VirtualNetworkClient(oci.config.from_file())
logger.debug("OCI clients initialized.")

# Function to log and send message
def log_and_send(message: str):
    logger.info(message)
    bot = telebot.TeleBot(BOT_TOKEN)
    bot.send_message(UID, message)

total_count = 0
j_count = 0
wait_s_for_retry = 10

try:
    logger.debug("Preparing instance details...")
    instance_detail = oci.core.models.LaunchInstanceDetails(
        compartment_id=COMPARTMENT_ID,
        display_name=DISPLAY_NAME,
        availability_domain=AVAILABILITY_DOMAINS[0],
        shape=machine_config["mname"],
        source_details=oci.core.models.InstanceSourceViaImageDetails(
            source_type="image",
            image_id=IMAGE_ID,
            boot_volume_size_in_gbs=BOOT_VOLUME_SIZE_IN_GBS
        ),
        create_vnic_details=oci.core.models.CreateVnicDetails(
            subnet_id=SUBNET_ID,
            assign_public_ip=True
        ),
        metadata={
            "ssh_authorized_keys": SSH_AUTHORIZED_KEYS
        }
    )

    logger.debug("Instance details prepared: %s", instance_detail)
    logger.info("Launching instance...")
    launch_instance_response = compute_client.launch_instance(instance_detail)
    logger.info("Instance launched, waiting for it to be ready...")
    time.sleep(60)

    logger.debug("Listing VNIC attachments...")
    vnic_attachments = compute_client.list_vnic_attachments(compartment_id=COMPARTMENT_ID, instance_id=launch_instance_response.data.id)
    logger.debug("VNIC attachments: %s", vnic_attachments.data)

    logger.debug("Listing private IPs...")
    private_ips = vnc_client.list_private_ips(subnet_id=SUBNET_ID, vnic_id=vnic_attachments.data[0].vnic_id)
    logger.debug("Private IPs: %s", private_ips.data)

    logger.debug("Retrieving public IP...")
    public_ip = vnc_client.get_public_ip_by_private_ip_id(oci.core.models.GetPublicIpByPrivateIpIdDetails(private_ip_id=private_ips.data[0].id)).data.ip_address
    logger.info("Public IP retrieved: %s", public_ip)

    total_count += 1
    success_message = f'"{DISPLAY_NAME}" VPS {machine_config["mname"]} created successfully! IP: {public_ip}'
    logger.info(success_message)
    log_and_send(success_message)

    logger.info("Script completed successfully.")
    sys.exit()

except oci.exceptions.ServiceError as e:
    total_count += 1
    j_count += 1
    if j_count == 10:
        j_count = 0
        log_and_send(f"Bot is still running. Checked at: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    error_message = f'{e.status} - {e.code} - {e.message}. Retrying after {wait_s_for_retry} seconds. Number of Retry: {total_count}'
    logger.error(error_message)

    if e.status == 429:
        wait_s_for_retry += 1
        logger.warning(f"Rate limit exceeded. Increasing wait time to {wait_s_for_retry} seconds.")
    else:
        logger.info(f"Waiting for {wait_s_for_retry} seconds before retrying.")
        time.sleep(wait_s_for_retry)
