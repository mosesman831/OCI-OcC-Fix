"""
OCI Out of Capacity Fix
Version 2.1.1
Moses (@mosesman831)
GitHub: https://github.com/mosesman831/OCI-OcC-Fix
Please support by donating or starring this repo.
"""

import oci
import logging
import time
import sys
import telebot
import datetime
import configparser
import json
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, Optional

# Constants
CONFIG_FILE = 'configuration.ini'
LOG_FILE = 'oci_occ.log'
MAX_LOG_SIZE = 5 * 1024 * 1024  # 5 MB
LOG_BACKUP_COUNT = 3

class OciOccFix:
    def __init__(self):
        self.config = self.load_config()
        self.setup_logging()
        self.clients = self.initialize_oci_clients()
        self.tg_bot = self.initialize_telegram()
        self.tg_message_id = None
        
        # Runtime state
        self.total_retries = 0
        self.retry_counter = 0
        self.wait_seconds = self.config.getint('Retry', 'initial_retry_interval')

    @staticmethod
    def load_config() -> configparser.ConfigParser:
        """Load and validate configuration"""
        config = configparser.ConfigParser()
        if not Path(CONFIG_FILE).exists():
            raise FileNotFoundError(f"Configuration file {CONFIG_FILE} not found")
        
        config.read(CONFIG_FILE)
        required_sections = ['OCI', 'Instance', 'Telegram', 'Machine', 'Retry']
        for section in required_sections:
            if not config.has_section(section):
                raise ValueError(f"Missing required section [{section}]")
        
        return config

    def setup_logging(self):
        """Configure logging with rotation"""
        formatter = logging.Formatter('[%(levelname)s] %(asctime)s - %(message)s')
        log_level = self.config.get('Logging', 'log_level', fallback='INFO')

        handlers = [
            RotatingFileHandler(
                LOG_FILE,
                maxBytes=MAX_LOG_SIZE,
                backupCount=LOG_BACKUP_COUNT,
                encoding='utf-8'
            ),
            logging.StreamHandler()
        ]

        logging.basicConfig(
            level=log_level,
            format=formatter._fmt,
            handlers=handlers
        )

    def initialize_oci_clients(self) -> Dict[str, object]:
        """Initialize OCI service clients with validation"""
        try:
            oci_config = oci.config.from_file('./config')
            return {
                'compute': oci.core.ComputeClient(oci_config),
                'identity': oci.identity.IdentityClient(oci_config),
                'network': oci.core.VirtualNetworkClient(oci_config),
                'blockstorage': oci.core.BlockstorageClient(oci_config)
            }
        except Exception as e:
            logging.error(f"OCI client initialization failed: {str(e)}")
            sys.exit(1)

    def initialize_telegram(self) -> Optional[telebot.TeleBot]:
        """Initialize Telegram bot if configured"""
        bot_token = self.config.get('Telegram', 'bot_token')
        uid = self.config.get('Telegram', 'uid')
        
        if bot_token not in ('xxxx', '') and uid not in ('xxxx', ''):
            bot = telebot.TeleBot(bot_token)
            self.send_telegram_startup_message(bot)
            return bot
        return None

    def send_telegram_startup_message(self, bot: telebot.TeleBot):
        """Send initial status message"""
        tenancy = self.clients['identity'].get_tenancy(
            self.config.get('OCI', 'compartment_id')
        ).data
        users = self.clients['identity'].list_users(
            self.config.get('OCI', 'compartment_id')
        ).data
        
        message = f"""OCI Capacity Manager Started
Account: {tenancy.name}
User: {users[0].email if users else 'Unknown'}
Time: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
Retry Interval: {self.wait_seconds}s
Machine: {self.config.get('Machine', 'shape')}"""
        
        try:
            sent = bot.send_message(self.config.get('Telegram', 'uid'), message)
            self.tg_message_id = sent.message_id
        except Exception as e:
            logging.error(f"Telegram initialization failed: {str(e)}")

    def validate_resources(self) -> bool:
        """Perform comprehensive resource validation"""
        # Storage validation
        compartment_id = self.config.get('OCI', 'compartment_id')
        try:
            volumes = self.clients['blockstorage'].list_volumes(compartment_id).data
            total_storage = sum(v.size_in_gbs for v in volumes if v.lifecycle_state not in ("TERMINATING", "TERMINATED"))
            
            # Check boot volumes in all availability domains
            ads = json.loads(self.config.get('OCI', 'availability_domains'))
            for ad in ads:
                boot_volumes = self.clients['blockstorage'].list_boot_volumes(
                    compartment_id=compartment_id,
                    availability_domain=ad
                ).data
                total_storage += sum(bv.size_in_gbs for bv in boot_volumes if bv.lifecycle_state not in ("TERMINATING", "TERMINATED"))
            
            required_size = self.config.getint('Instance', 'boot_volume_size', fallback=47)
            if (200 - total_storage) < required_size:
                logging.critical(f"Insufficient storage! Required: {required_size}GB, Available: {200 - total_storage}GB")
                return False

        except oci.exceptions.ServiceError as e:
            logging.error(f"Storage validation failed: {e.message}")
            return False

        # Instance quota validation
        instances = self.clients['compute'].list_instances(compartment_id).data
        active_instances = [i for i in instances if i.lifecycle_state not in ("TERMINATING", "TERMINATED")]
        
        if self.config.get('Instance', 'display_name') in [i.display_name for i in active_instances]:
            logging.critical("Duplicate instance display name detected!")
            return False

        # ARM quota validation
        if self.config.get('Machine', 'type').upper() == 'ARM':
            total_ocpus = sum(i.shape_config.ocpus for i in active_instances if i.shape == "VM.Standard.A1.Flex")
            total_memory = sum(i.shape_config.memory_in_gbs for i in active_instances if i.shape == "VM.Standard.A1.Flex")
            
            new_ocpus = self.config.getint('Machine', 'ocpus')
            new_memory = self.config.getint('Machine', 'memory')
            
            if (total_ocpus + new_ocpus) > 4 or (total_memory + new_memory) > 24:
                logging.critical("ARM quota exceeded! Max 4 OCPUs/24GB")
                return False

        return True

    def create_instance(self, availability_domain: str) -> Optional[str]:
        """Attempt instance creation in specified AD"""
        launch_details = oci.core.models.LaunchInstanceDetails(
            metadata={"ssh_authorized_keys": self.config.get('Instance', 'ssh_keys')},
            availability_domain=availability_domain,
            compartment_id=self.config.get('OCI', 'compartment_id'),
            shape=self.config.get('Machine', 'shape'),
            display_name=self.config.get('Instance', 'display_name'),
            source_details=self.get_source_details(),
            create_vnic_details=oci.core.models.CreateVnicDetails(
                subnet_id=self.config.get('OCI', 'subnet_id'),
                assign_public_ip=True
            ),
            shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
                ocpus=self.config.getint('Machine', 'ocpus'),
                memory_in_gbs=self.config.getint('Machine', 'memory')
            )
        )

        try:
            response = self.clients['compute'].launch_instance(launch_details)
            return response.data.id
        except oci.exceptions.ServiceError as e:
            logging.warning(f"Create failed in {availability_domain}: {e.code} - {e.message}")
            return None

    def get_source_details(self):
        """Get appropriate source configuration"""
        if self.config.get('OCI', 'boot_volume_id', fallback='xxxx') != 'xxxx':
            return oci.core.models.InstanceSourceViaBootVolumeDetails(
                source_type="bootVolume",
                boot_volume_id=self.config.get('OCI', 'boot_volume_id')
            )
        
        return oci.core.models.InstanceSourceViaImageDetails(
            source_type="image",
            image_id=self.config.get('OCI', 'image_id'),
            boot_volume_size_in_gbs=self.config.getint('Instance', 'boot_volume_size')
        )

    def handle_success(self, instance_id: str):
        """Handle successful instance creation"""
        try:
            vnic = self.clients['compute'].list_vnic_attachments(
                compartment_id=self.config.get('OCI', 'compartment_id'),
                instance_id=instance_id
            ).data[0]

            public_ip = self.clients['network'].get_public_ip_by_private_ip_id(
                oci.core.models.GetPublicIpByPrivateIpIdDetails(
                    private_ip_id=self.clients['network'].list_private_ips(
                        vnic_id=vnic.vnic_id
                    ).data[0].id
                )
            ).data.ip_address

            logging.info(f"Instance created successfully! Public IP: {public_ip}")
            self.send_telegram_update(f"Instance Ready!\nIP: {public_ip}\nRetries: {self.total_retries}")

        except Exception as e:
            logging.error(f"Success handling failed: {str(e)}")

    def send_telegram_update(self, message: str):
        """Update Telegram message or send new"""
        if not self.tg_bot or not self.tg_message_id:
            return

        try:
            self.tg_bot.edit_message_text(
                chat_id=self.config.get('Telegram', 'uid'),
                message_id=self.tg_message_id,
                text=message
            )
        except Exception as e:
            logging.warning(f"Telegram update failed: {str(e)}")

    def adaptive_retry_wait(self, error_code: str):
        """Adjust retry timing based on error type"""
        if error_code == 'TooManyRequests':
            self.wait_seconds = min(
                self.wait_seconds * self.config.getfloat('Retry', 'backoff_factor'),
                self.config.getint('Retry', 'max_interval')
            )
        else:
            self.wait_seconds = max(
                self.wait_seconds / 1.5,
                self.config.getint('Retry', 'min_interval')
            )

        logging.info(f"Next retry in {self.wait_seconds:.1f}s")

    def run(self):
        """Main execution loop"""
        if not self.validate_resources():
            logging.critical("Resource validation failed. Exiting.")
            sys.exit(1)

        ads = json.loads(self.config.get('OCI', 'availability_domains'))
        
        while True:
            try:
                for ad in ads:
                    self.total_retries += 1
                    instance_id = self.create_instance(ad)
                    
                    if instance_id:
                        self.handle_success(instance_id)
                        sys.exit(0)
                    
                    # Update Telegram every 10 attempts
                    if self.total_retries % 10 == 0 and self.tg_bot:
                        self.send_telegram_update(
                            f"Attempt {self.total_retries}\n"
                            f"Last Error: {ad} capacity\n"
                            f"Next retry: {self.wait_seconds:.1f}s"
                        )

                    time.sleep(self.wait_seconds)

            except KeyboardInterrupt:
                logging.info("Process interrupted by user")
                self.send_telegram_update("Process interrupted by user")
                sys.exit(0)
            except Exception as e:
                logging.error(f"Unexpected error: {str(e)}")
                self.adaptive_retry_wait(getattr(e, 'code', 'Unknown'))
                time.sleep(self.wait_seconds)

if __name__ == "__main__":
    try:
        OciOccFix().run()
    except Exception as e:
        logging.critical(f"Fatal initialization error: {str(e)}")
        sys.exit(1)
