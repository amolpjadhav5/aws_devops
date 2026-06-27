import boto3
import os
 
def lambda_handler(event, context):
    OU_ID = os.environ.get("OU_ID")
    if not OU_ID:
        raise ValueError("Environment variable OU_ID is not set")
 
    org_client = boto3.client("organizations")
 
    def list_children(parent_id):
        paginator = org_client.get_paginator("list_children")
        children = []
        for page in paginator.paginate(ParentId=parent_id, ChildType="ORGANIZATIONAL_UNIT"):
            children.extend(page["Children"])
        return children
 
    def list_accounts(parent_id):
        paginator = org_client.get_paginator("list_accounts_for_parent")
        accounts = []
        for page in paginator.paginate(ParentId=parent_id):
            accounts.extend(page["Accounts"])
        return [acct["Id"] for acct in accounts if acct["Status"] == "ACTIVE"]
 
    def get_all_accounts_recursive(ou_id):
        accounts = list_accounts(ou_id)
        for child in list_children(ou_id):
            accounts.extend(get_all_accounts_recursive(child["Id"]))
        return accounts
 
    try:
        account_ids = get_all_accounts_recursive(OU_ID)
        print(f"Found accounts: {account_ids}")
        return {"accounts": account_ids}
    except Exception as e:
        print(f"Error retrieving accounts: {e}")
        return {"error": str(e)}