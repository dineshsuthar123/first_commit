"""AWS operator commands. Provisioning is never invoked by the browser or tests."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import time

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]


def template():
    body = json.loads((ROOT / "infra/stack.json").read_text())
    body["Resources"]["Runner"]["Properties"]["UserData"]["Fn::Base64"] = (ROOT / "infra/bootstrap.sh").read_text()
    return body


def outputs(cf, name):
    return {o["OutputKey"]: o["OutputValue"] for o in cf.describe_stacks(StackName=name)["Stacks"][0]["Outputs"]}


def run_remote(ssm, instance, commands):
    response = ssm.send_command(InstanceIds=[instance], DocumentName="AWS-RunShellScript",
                                Parameters={"commands": [commands], "executionTimeout": ["1800"]}, TimeoutSeconds=1800)
    command_id = response["Command"]["CommandId"]
    print(json.dumps({"commandId": command_id, "instanceId": instance}), flush=True)
    for _ in range(360):
        time.sleep(5)
        try:
            result = ssm.get_command_invocation(CommandId=command_id, InstanceId=instance)
        except ssm.exceptions.InvocationDoesNotExist:
            continue
        if result["Status"] not in ("Pending", "InProgress", "Delayed"):
            print(result.get("StandardOutputContent", ""))
            print(result.get("StandardErrorContent", ""))
            if result["Status"] != "Success":
                raise RuntimeError(f"SSM execution {result['Status']}; inspect command {command_id}")
            return result
    raise TimeoutError("SSM deadline exceeded; inspect command status before retrying")


def deploy_script(bucket, key, digest, region):
    # All substituted strings are trusted SDK outputs or locally generated hashes, shell-quoted.
    return f'''set -eu
test -f /opt/stateproof/bootstrap-ready
mkdir -p /opt/stateproof/releases/{digest}
aws s3api get-object --region {shlex.quote(region)} --bucket {shlex.quote(bucket)} --key {shlex.quote(key)} /opt/stateproof/source.tar.gz >/dev/null
echo '{digest}  /opt/stateproof/source.tar.gz' | sha256sum -c -
tar -xzf /opt/stateproof/source.tar.gz -C /opt/stateproof/releases/{digest}
cd /opt/stateproof/releases/{digest}
if [ ! -f /opt/stateproof/runtime.env ]; then
  umask 077
  printf 'POSTGRES_PASSWORD=%s\n' "$(openssl rand -hex 24)" > /opt/stateproof/runtime.env
fi
cp /opt/stateproof/runtime.env .env
printf '%s\n' 'STATEPROOF_READ_ONLY=1' 'EVIDENCE_BUCKET={bucket}' 'AWS_DEFAULT_REGION={region}' >> .env
docker compose -p stateproof up -d --build --wait
ln -sfn /opt/stateproof/releases/{digest} /opt/stateproof/current
curl --fail http://127.0.0.1:8000/api/health
set +e
docker compose -p stateproof exec -T control python -m engine.cli campaign --variant local_dedup > /opt/stateproof/campaign.json
campaign_status=$?
set -e
test "$campaign_status" -le 1
campaign_id=$(python3 -c 'import json; print(json.load(open("/opt/stateproof/campaign.json"))["id"])')
docker compose -p stateproof exec -T control python -m engine.cli reduce "$campaign_id"
docker compose -p stateproof exec -T control python -m engine.cli manifest "$campaign_id" --output data/cloud-replay.json
docker compose -p stateproof exec -T control python -m engine.cli replay data/cloud-replay.json
docker compose -p stateproof exec -T control python -m engine.cli replay data/cloud-replay.json --compare stable_key
docker compose -p stateproof exec -T control python -m engine.cli export "$campaign_id" --s3
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["render", "provision", "deploy", "health", "teardown"])
    parser.add_argument("--region")
    parser.add_argument("--stack", default="stateproof-demo")
    parser.add_argument("--account-id")
    parser.add_argument("--budget-usd", type=float)
    parser.add_argument("--vpc-id")
    parser.add_argument("--subnet-id")
    parser.add_argument("--execute", action="store_true", help="explicitly authorize provisioning/deployment/deletion")
    parser.add_argument("--purge-evidence", action="store_true", help="permanently delete the retained bucket and evidence during teardown")
    args = parser.parse_args()
    if args.command == "render":
        print(json.dumps(template(), indent=2))
        return
    if not args.region or not args.account_id or not re.fullmatch(r"[0-9]{12}", args.account_id):
        parser.error("AWS commands require an approved --region and --account-id")
    if args.command in ("provision", "deploy", "teardown") and not args.execute:
        parser.error("review infra/README.md and pass --execute only with authorization")
    session = boto3.Session(region_name=args.region)
    account = session.client("sts").get_caller_identity()["Account"]
    if account != args.account_id:
        raise RuntimeError("credential account does not match the approved account")
    cf = session.client("cloudformation")
    if args.command == "provision":
        if not args.vpc_id or not args.subnet_id or not args.budget_usd or args.budget_usd <= 0:
            parser.error("provision requires VPC, public subnet and approved positive budget")
        body = json.dumps(template())
        cf.validate_template(TemplateBody=body)
        cf.create_stack(StackName=args.stack, TemplateBody=body, Capabilities=["CAPABILITY_IAM"],
                        Parameters=[{"ParameterKey": k, "ParameterValue": str(v)} for k, v in {
                            "VpcId": args.vpc_id, "SubnetId": args.subnet_id, "ApprovedBudgetUSD": args.budget_usd}.items()])
        cf.get_waiter("stack_create_complete").wait(StackName=args.stack)
        print(json.dumps(outputs(cf, args.stack), indent=2))
        return
    output = outputs(cf, args.stack)
    s3 = session.client("s3")
    if args.command == "deploy":
        if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).strip():
            raise RuntimeError("deploy requires a clean committed checkout")
        payload = subprocess.check_output(["git", "archive", "--format=tar.gz", "HEAD"], cwd=ROOT)
        digest = hashlib.sha256(payload).hexdigest()
        key = f"sources/{digest}.tar.gz"
        try:
            s3.put_object(Bucket=output["EvidenceBucket"], Key=key, Body=payload, IfNoneMatch="*",
                          ChecksumSHA256=base64.b64encode(hashlib.sha256(payload).digest()).decode())
        except ClientError as e:
            if e.response["ResponseMetadata"]["HTTPStatusCode"] != 412:
                raise
        run_remote(session.client("ssm"), output["InstanceId"], deploy_script(output["EvidenceBucket"], key, digest, args.region))
        print(json.dumps(output, indent=2))
    elif args.command == "health":
        run_remote(session.client("ssm"), output["InstanceId"], "set -eu; test -f /opt/stateproof/bootstrap-ready; cd /opt/stateproof/current; docker compose -p stateproof ps; curl --fail http://127.0.0.1:8000/api/health; curl --fail http://127.0.0.1/api/fixtures")
    elif args.command == "teardown":
        cf.delete_stack(StackName=args.stack)
        cf.get_waiter("stack_delete_complete").wait(StackName=args.stack)
        bucket = output["EvidenceBucket"]
        if args.purge_evidence:
            for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
                if page.get("Contents"):
                    s3.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": o["Key"]} for o in page["Contents"]]})
            s3.delete_bucket(Bucket=bucket)
            print("Stack and evidence bucket deleted.")
        else:
            print(f"Stack deleted. Retained bucket {bucket}; storage remains billable until expiry/deletion.")


if __name__ == "__main__":
    main()
