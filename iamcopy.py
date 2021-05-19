import boto3
import sys
import json

""" 
This is a script to copy IAM role from one account to another

Usage : python3 iamcopy.py <Source Role name> <Destination Role Name>

Please update the profile name in spn (Source profile name) and dpn (Destination profile name) in the script ,
NOTE: While copying please ensure that the limit of policies attached to role is same in both account
      If a customer managed policy already exists on the destination account with the same name, the script takes that policy

 """


def replace_acc(pdoc,accid,newacc):                                         #function to replace account number in policy resource
    if isinstance(pdoc["Statement"][0]["Resource"], str):
        pdoc["Statement"][0]["Resource"] = pdoc["Statement"][0]["Resource"].replace(accid,newacc)
    else:
        pdoc["Statement"][0]["Resource"] = [sub.replace(accid,newacc) for sub in pdoc["Statement"][0]["Resource"]]
    return(pdoc)

spn = 'stage'  #replace with source account
dpn = 'dev'    #replace with destination account

srn = sys.argv[1]
drn = sys.argv[2]
print("\033[96m {}\033[00m" .format("Copying "+ srn +" to "+drn))
src = boto3.Session(profile_name=spn,region_name='ap-south-1')
sts = src.client('sts')
response = sts.get_caller_identity()
oldacc = response['Account']

dest = boto3.Session(profile_name=dpn,region_name='ap-south-1')

sts = dest.client('sts')
response = sts.get_caller_identity()
account_id = response['Account']

iam = src.client('iam')
awsmanaged_policy=[]
custmanaged_policy=[]
assume_role_policy = iam.list_attached_role_policies(RoleName=srn)
print('getting AWS and customer managed policy')
for each in assume_role_policy['AttachedPolicies']:   #getting AWS and customer managed policy
    if each['PolicyArn'].startswith('arn:aws:iam::aws'):
        awsmanaged_policy.append(each['PolicyArn'])
    else:
        custmanaged_policy.append(each['PolicyArn'])

inline_policy = {}
print('getting inrole policy')
ip = iam.list_role_policies(RoleName=srn)            #getting inrole policy
for each in ip['PolicyNames']:
    temp = iam.get_role_policy(RoleName=srn,PolicyName= each)
    pd = replace_acc(temp['PolicyDocument'],oldacc,account_id)
    inline_policy[temp['PolicyName']] = pd

policy_doc = iam.get_role(RoleName=srn)             #getting assume role policy document    

print('creating role '+ drn)
tiam = dest.client('iam')                           #creating role
try:
    response = tiam.create_role(
        RoleName= drn,
        AssumeRolePolicyDocument=json.dumps(policy_doc['Role']['AssumeRolePolicyDocument']))
    print("\033[96m {}\033[00m" .format("Role Created"))
    for awspolicy in awsmanaged_policy:           #attaching aws managed policy to role
        polstatus = iam.get_policy(PolicyArn=awspolicy)
        if(polstatus['Policy']['IsAttachable']):  #checking if the policy is depreciated or not
            try:                                    
                tiam.attach_role_policy(RoleName=drn,PolicyArn=awspolicy)
            except tiam.exceptions.LimitExceededException:
                print("\033[91m {}\033[00m" .format("Max number of policies attached"))
        else:
            print("\033[91m {}\033[00m" .format("Depreciated:"+ awspolicy+ " Could not attach"))

    for cmkpolicy in custmanaged_policy: #adding customer managed policy to account
        print(cmkpolicy)
        policy = iam.get_policy(PolicyArn=cmkpolicy)
        policy_version = iam.get_policy_version(
        PolicyArn = cmkpolicy, 
        VersionId = policy['Policy']['DefaultVersionId'])
        pname = policy['Policy']['PolicyName']
        opdoc = replace_acc(policy_version['PolicyVersion']['Document'],oldacc,account_id) #replacing account number in customer manger policy
        pdoc = json.dumps(opdoc)
        try:                           #checking if the managed policy already in the account 
            response = tiam.create_policy(
            PolicyName=pname,
            PolicyDocument=pdoc)
            policy_arn = response['Policy']['Arn']
        except tiam.exceptions.EntityAlreadyExistsException:  
            policy_arn = "arn:aws:iam::"+account_id+":policy/"+pname   #taking the polcy with same name in destination account
        try:
            tiam.attach_role_policy(RoleName=drn,PolicyArn=policy_arn)
        except tiam.exceptions.LimitExceededException:
            print("\033[91m {}\033[00m" .format("Max number of policies attached"))
        

    for key, value in inline_policy.items(): #adding the inline policy to the account
        response = tiam.put_role_policy(
        RoleName=drn,
        PolicyName=key,
        PolicyDocument=json.dumps(value)
    )
except tiam.exceptions.EntityAlreadyExistsException:
    print("Account Already Exists")
