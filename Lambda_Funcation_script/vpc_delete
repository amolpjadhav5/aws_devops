import boto3
import os
import logging
from botocore.exceptions import ClientError
 
# Setup structured logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
 
def lambda_handler(event, context):
    account_id = event["account_id"]
    role_name = os.environ.get("ASSUME_ROLE_NAME", "DeleteDefaultVPCExecutionRole")
 
    def assume_role(account_id, role_name):
        sts = boto3.client("sts")
        role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
        try:
            creds = sts.assume_role(RoleArn=role_arn, RoleSessionName="VPCCleanup")["Credentials"]
            logger.info(f"Assumed role into account {account_id}")
            return boto3.Session(
                aws_access_key_id=creds["AccessKeyId"],
                aws_secret_access_key=creds["SecretAccessKey"],
                aws_session_token=creds["SessionToken"]
            )
        except Exception as e:
            logger.error(f"Assume role failed for {account_id}: {e}")
            return None
 
    def is_vpc_unused(client, vpc_id):
        instances = client.describe_instances(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])["Reservations"]
        enis = client.describe_network_interfaces(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])["NetworkInterfaces"]
        return not instances and not enis
 
    def delete_vpc_resources(client, vpc_id):
        try:
            logger.info(f"Deleting resources in VPC {vpc_id}")
 
            # Detach and delete Internet Gateways
            for igw in client.describe_internet_gateways(Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}])["InternetGateways"]:
                client.detach_internet_gateway(InternetGatewayId=igw["InternetGatewayId"], VpcId=vpc_id)
                client.delete_internet_gateway(InternetGatewayId=igw["InternetGatewayId"])
                logger.info(f"Deleted Internet Gateway {igw['InternetGatewayId']}")
 
            # Delete Subnets
            for subnet in client.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])["Subnets"]:
                client.delete_subnet(SubnetId=subnet["SubnetId"])
                logger.info(f"Deleted Subnet {subnet['SubnetId']}")
 
            # Replace and delete main route table
            for rtb in client.describe_route_tables(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])["RouteTables"]:
                is_main = any(assoc.get("Main", False) for assoc in rtb.get("Associations", []))
                if is_main:
                    new_rtb = client.create_route_table(VpcId=vpc_id)["RouteTable"]
                    client.replace_route_table_association(
                        AssociationId=rtb["Associations"][0]["RouteTableAssociationId"],
                        RouteTableId=new_rtb["RouteTableId"]
                    )
                    client.delete_route_table(RouteTableId=rtb["RouteTableId"])
                    logger.info(f"Replaced and deleted main route table {rtb['RouteTableId']}")
                else:
                    for assoc in rtb.get("Associations", []):
                        if assoc.get("RouteTableAssociationId"):
                            client.disassociate_route_table(AssociationId=assoc["RouteTableAssociationId"])
                    client.delete_route_table(RouteTableId=rtb["RouteTableId"])
                    logger.info(f"Deleted route table {rtb['RouteTableId']}")
 
            # Delete non-default Security Groups
            for sg in client.describe_security_groups(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])["SecurityGroups"]:
                if sg["GroupName"] != "default":
                    try:
                        client.delete_security_group(GroupId=sg["GroupId"])
                        logger.info(f"Deleted security group {sg['GroupId']}")
                    except ClientError as e:
                        logger.warning(f"Failed to delete security group {sg['GroupId']}: {e}")
 
            # Delete non-default Network ACLs
            for acl in client.describe_network_acls(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])["NetworkAcls"]:
                if not acl.get("IsDefault", False):
                    try:
                        client.delete_network_acl(NetworkAclId=acl["NetworkAclId"])
                        logger.info(f"Deleted network ACL {acl['NetworkAclId']}")
                    except ClientError as e:
                        logger.warning(f"Failed to delete network ACL {acl['NetworkAclId']}: {e}")
 
            # Replace DHCP Options
            try:
                default_dhcp_id = client.describe_dhcp_options()["DhcpOptions"][0]["DhcpOptionsId"]
                client.associate_dhcp_options(DhcpOptionsId=default_dhcp_id, VpcId=vpc_id)
                logger.info(f"Associated default DHCP options to VPC {vpc_id}")
            except ClientError as e:
                logger.warning(f"Failed to associate DHCP options for VPC {vpc_id}: {e}")
 
        except ClientError as e:
            logger.error(f"Error deleting resources in VPC {vpc_id}: {e}")
 
    session = assume_role(account_id, role_name)
    if not session:
        return {"account_id": account_id, "status": "role_assume_failed"}
 
    ec2 = session.client("ec2")
    regions = [r["RegionName"] for r in ec2.describe_regions()["Regions"]]
    deleted_vpcs = []
 
    for region in regions:
        try:
            logger.info(f"Processing region: {region}")
            client = session.client("ec2", region_name=region)
            vpcs = client.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"]
            if not vpcs:
                logger.info(f"No default VPC found in {region}")
            for vpc in vpcs:
                vpc_id = vpc["VpcId"]
                if is_vpc_unused(client, vpc_id):
                    logger.info(f"Unused default VPC {vpc_id} in {region} - proceeding to delete")
                    delete_vpc_resources(client, vpc_id)
                    try:
                        client.delete_vpc(VpcId=vpc_id)
                        logger.info(f"Deleted VPC {vpc_id} in {region}")
                        deleted_vpcs.append({"region": region, "vpc_id": vpc_id})
                    except ClientError as e:
                        logger.error(f"Failed to delete VPC {vpc_id} in {region}: {e}")
                else:
                    logger.info(f"Skipping in-use default VPC {vpc_id} in {region}")
        except Exception as e:
            logger.error(f"Error processing region {region}: {e}")
 
    return {
        "account_id": account_id,
        "deleted_vpcs": deleted_vpcs,
        "status": "completed" if deleted_vpcs else "no_vpcs_deleted"
    }
 