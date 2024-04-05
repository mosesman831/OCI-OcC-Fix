#Oracle Cloud Infrastructure (OCI) - Create VPS instance
#Fix for Out of Capacity Error
#Made by @mosesman831
#https://github.com/mosesman831
#https://github.com/mosesman831/OCI-OcC-Fix
#OCI OcC	
#Out of Capacity Fix by @mosesman831
#VERSION1.1
version = "1.1"

imageId = 'xxxx'
#e.g. imageId = 'ocid1.image.oc1.eu-frankfurt-1.aaaaaaaaonnh....'
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
#"xxxx" = default
#e.g. boot_volume_size_in_gbs="47"
boot_volume_id="xxxx"
#e.g. boot_volume_id="ocid1.bootvolume.oc1.uk-manchester-1.aaaaaaa..."

bot_token = "xxxx"
#Telegram BOT Token
#Use @BotFather to create a new bot and get the token (/newbot)
uid = "xxxx"
#Telegram User ID
#Use @RoseBot to get your user id (/id)

#AMD not working yet. Please do not change.
machine = "ARM"
#e.g. machine = AMD or ARM
if machine=="ARM":
	#edit if you want to use ARM image (MAX OCPU 4 and MEMORY 24)
	ocpus = 4
	memory_in_gbs = 24
	mname = "VM.Standard.A1.Flex"
elif machine == "AMD":
	#DO NOT EDIT
	ocpus = 1
	memory_in_gbs = 1
	mname = "VM.Standard.E2.1.Micro"

minimum_time_interval = 1

import oci
import logging
import time
import sys
import telebot
import datetime

bot = telebot.TeleBot(bot_token)

LOG_FORMAT = '[%(levelname)s] %(asctime)s - %(message)s'
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logging.info("#####################################################")
logging.info("Welcome to OCI OcC Fix by Moses")
logging.info(f"Spawing {machine} instance {mname}")
logging.info("Made by Moses")
logging.info("https://github.com/mosesman831/OCI-OcC-Fix")
logging.info(f"Version {version}")
logging.info("#####################################################")


message = f'Start spawning instance {mname} - {ocpus} ocpus - {memory_in_gbs} GB'
logging.info(message)

logging.info("Loading OCI config")
config = oci.config.from_file(file_location="./config")

logging.info("Initialize service client with default config file")
to_launch_instance = oci.core.ComputeClient(config)
identity_client = oci.identity.IdentityClient(config)
vnc_client = oci.core.VirtualNetworkClient(config)
cloud_name = identity_client.get_tenancy(tenancy_id=compartmentId).data.name
email = identity_client.list_users(compartment_id=compartmentId).data[0].email

message = f"Instance to create: {mname} - {ocpus} ocpus - {memory_in_gbs} GB"
logging.info(message)

volume_client = oci.core.BlockstorageClient(config)

total_volume_size=0

logging.info("Check available storage in account")

if imageId!="xxxx":
	try:
		list_volumes = volume_client.list_volumes(compartment_id=compartmentId).data
	except Exception as e:
		logging.info(f"{e.status} - {e.code} - {e.message}")
		logging.info("Error detected. Stopping script. Check values of bot.py file, config file and oci_private_key.pem file.")
		sys.exit()
	if list_volumes!=[]:
		for block_volume in list_volumes:
			if block_volume.lifecycle_state not in ("TERMINATING", "TERMINATED"):
				total_volume_size=total_volume_size+block_volume.size_in_gbs
	for availabilityDomain in availabilityDomains:
		list_boot_volumes = volume_client.list_boot_volumes(availability_domain=availabilityDomain,compartment_id=compartmentId).data
		if list_boot_volumes!=[]:
			for b_volume in list_boot_volumes:
				if b_volume.lifecycle_state not in ("TERMINATING", "TERMINATED"):
					total_volume_size=total_volume_size+b_volume.size_in_gbs
	free_storage=200-total_volume_size
	if boot_volume_size_in_gbs!="xxxx" and free_storage<boot_volume_size_in_gbs:
		logging.critical(f"There is {free_storage} GB out of 200 GB left in your Oracle Cloud account. {boot_volume_size_in_gbs} GB storage needs to create this vps. So, you need to delete unnecessary boot and block volumes in your oracle cloud account. **SCRIPT STOPPED**")
		sys.exit()
	if boot_volume_size_in_gbs=="xxxx" and free_storage<47:
		logging.critical(f"There is {free_storage} GB out of 200 GB left in your Oracle Cloud account. 47 GB storage needs to create this vps. So, you need to delete unnecessary boot and block volumes in your oracle cloud account. **SCRIPT STOPPED**")
		sys.exit()
		
logging.info("Check current instances in account")

current_instance = to_launch_instance.list_instances(compartment_id=compartmentId)
response = current_instance.data

total_ocpus = total_memory = _A1_Flex = 0
instance_names = []

if response:
	logging.info(f"{len(response)} instance(s) found!")
	for instance in response:
		logging.info(f"{instance.display_name} - {instance.shape} - {int(instance.shape_config.ocpus)} ocpu(s) - {instance.shape_config.memory_in_gbs} GB(s) | State: {instance.lifecycle_state}")
		instance_names.append(instance.display_name)
		if instance.shape == "VM.Standard.A1.Flex" and instance.lifecycle_state not in ("TERMINATING", "TERMINATED"):
			_A1_Flex += 1
			total_ocpus += int(instance.shape_config.ocpus)
			total_memory += int(instance.shape_config.memory_in_gbs)
	message = f"Current: {_A1_Flex} active VM.Standard.A1.Flex instance(s) (including RUNNING OR STOPPED)"
	logging.info(message)
else:
	logging.info(f"No instance(s) found!")

message = f"Total ocpus: {total_ocpus} - Total memory: {total_memory} (GB) || Free {4-total_ocpus} ocpus - Free memory: {24-total_memory} (GB)"
logging.info(message)

if total_ocpus + ocpus > 4 or total_memory + memory_in_gbs > 24:
    message = "Total maximum resource exceed free tier limit (Over 4 ocpus/24GB total). **SCRIPT STOPPED**"
    logging.critical(message)
    sys.exit()

if displayName in instance_names:
    message = f"Duplicate display name: >>>{displayName}<<< Change this! **SCRIPT STOPPED**"
    logging.critical(message)
    sys.exit()

message = f"Precheck pass! Create new instance VM.Standard.A1.Flex: {ocpus} opus - {memory_in_gbs} GB"
logging.info(message)

wait_s_for_retry = 1
tc=0
oc=0
total_count = 0
j_count = 0

if imageId!="xxxx":
	if boot_volume_size_in_gbs=="xxxx":
		op=oci.core.models.InstanceSourceViaImageDetails(source_type="image", image_id=imageId)
	else:
		op=oci.core.models.InstanceSourceViaImageDetails(source_type="image", image_id=imageId,boot_volume_size_in_gbs=boot_volume_size_in_gbs)
		
if boot_volume_id!="xxxx":
	op=oci.core.models.InstanceSourceViaBootVolumeDetails(source_type="bootVolume", boot_volume_id=boot_volume_id)

if bot_token!="xxxx" and uid!="xxxx":
	try:
		msg = f'''Cloud Account Name :- {cloud_name}
Email :- {email}
Number of Retry :- {total_count}
Bot Status :- Running
Last Checked: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
Made by Moses
https://github.com/mosesman831/OCI-OcC-Fix'''
		msg_id = bot.send_message(uid, msg).id
	except:
		pass

while True:
	for availabilityDomain in availabilityDomains:
		instance_detail = oci.core.models.LaunchInstanceDetails(metadata={"ssh_authorized_keys": ssh_authorized_keys},availability_domain=availabilityDomain,shape='VM.Standard.A1.Flex',compartment_id=compartmentId,display_name=displayName,is_pv_encryption_in_transit_enabled=True,source_details=op,create_vnic_details=oci.core.models.CreateVnicDetails(assign_public_ip=True,subnet_id=subnetId),shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(ocpus=ocpus, memory_in_gbs=memory_in_gbs))
		try:
			launch_instance_response = to_launch_instance.launch_instance(instance_detail)
			time.sleep(60)
			list_vnic_attachments_response = to_launch_instance.list_vnic_attachments(compartment_id=compartmentId,instance_id=launch_instance_response.data.id)
			list_private_ips_response = vnc_client.list_private_ips(subnet_id=subnetId,vnic_id=list_vnic_attachments_response.data[0].vnic_id)
			get_public_ip_response = vnc_client.get_public_ip_by_private_ip_id(get_public_ip_by_private_ip_id_details=oci.core.models.GetPublicIpByPrivateIpIdDetails(private_ip_id=list_private_ips_response.data[0].id))
			ip = get_public_ip_response.data.ip_address
			total_count = total_count+1
			logging.info(f'"{displayName}" VPS {mname} is created successfully!. Cloud Account Name :- {cloud_name}. Email :- {email}. Number of Retry :- {total_count}. VPS IP :- {ip}')
			if bot_token!="xxxx" and uid!="xxxx":
				while True:
					try:
						bot.delete_message(uid,msg_id)
						msg=f'''"{displayName}" VPS is created successfully!
Cloud Account Name :- {cloud_name}
Email :- {email}
Number of Retry :- {total_count}
VPS IP :- {ip}
Made by Moses
https://github.com/mosesman831/OCI-OcC-Fix'''
						bot.send_message(uid,msg)
						break
					except:
						time.sleep(5)
			sys.exit()
		except oci.exceptions.ServiceError as e:
			total_count = total_count +1
			j_count = j_count+1
			if j_count==10:
				j_count=0
				if bot_token!="xxxx" and uid!="xxxx":
					try:
						msg=f'''Cloud Account Name: {cloud_name}
Email: {email}
Number of Retry: {total_count}
Bot Status: Running
Last Checked: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
Made by Moses
https://github.com/mosesman831/OCI-OcC-Fix'''
						bot.edit_message_text(msg,uid,msg_id)
					except:
						pass
			if e.status == 429:
				oc=0
				tc=tc+1
				if tc==2:
					wait_s_for_retry=wait_s_for_retry+1
					tc=0
				message = f'{e.status} - {e.code} - {e.message}. Retrying after {wait_s_for_retry} seconds. Number of Retry: {total_count}'
				time.sleep(wait_s_for_retry)
			else:
				tc=0
				if wait_s_for_retry>minimum_time_interval:
					oc=oc+1
				if oc==2:
					wait_s_for_retry=wait_s_for_retry-1
					oc=0
				message = f'{e.status} - {e.code} - {e.message}. Retrying after {wait_s_for_retry} seconds. Number of Retry: {total_count}'
				logging.info(message)
				time.sleep(wait_s_for_retry)
		except Exception as e:
			total_count=total_count+1
			j_count=j_count+1
			if j_count==10:
				j_count=0
				if bot_token!="xxxx" and uid!="xxxx":
					try:
						msg=f'''Cloud Account Name: {cloud_name}
Email: {email}
Number of Retry: {total_count}
Bot Status: Running
Last Checked: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
Made by Moses
https://github.com/mosesman831/OCI-OcC-Fix'''
						bot.edit_message_text(msg,uid,msg_id)
					except:
						pass
			tc=0
			if wait_s_for_retry>minimum_time_interval:
				oc=oc+1
			if oc==2:
				wait_s_for_retry=wait_s_for_retry-1
				oc=0
			message = f'{e}. Retrying after {wait_s_for_retry} seconds. Number of Retry: {total_count}'
			logging.info(message)
			time.sleep(wait_s_for_retry)
		except KeyboardInterrupt:
			sys.exit()
