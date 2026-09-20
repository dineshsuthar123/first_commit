# AWS path: same Compose stack, one EC2 host, real S3 evidence

Cloud execution is **not validated or deployed** in this checkout's recorded session. No approved account, region, budget or provisioning authorization was supplied. The commands below are the exact remaining path; local implementation and tests do not establish AWS success.

The template creates one t3.medium, a 20 GiB encrypted gp3 root disk, public IPv4, an HTTP security group, an instance profile with SSM and scoped S3 permissions, and a private encrypted bucket. A public subnet/VPC with internet routing must already exist. No PostgreSQL/provider ports or SSH ports are opened. Nginx permits only read methods and the API also runs with `STATEPROOF_READ_ONLY=1`. Public HTTP is suitable only for this non-sensitive sample evidence; use HTTPS before expanding beyond it. Operators run trusted CLI commands using SSM.

The instance downloads pinned Compose v2.39.2 and verifies its release checksum. `deploy` uploads an exact `git archive HEAD`, checks SHA-256 on the host, builds the same digest-pinned Dockerfile, executes discovery, reduction, replay and repair comparison on EC2, and uploads the actual bundle to S3 through the instance role. AWS keys are never passed into Compose. IMDSv2 is required, with hop limit 2 so the container can use the role. The role cannot delete evidence.

From WSL/Linux or PowerShell, with Python dependencies installed and an approved AWS credential profile configured:

```sh
# Replace ALL placeholders with approved values. No resources created by render.
python infra/manage.py render > data/cloudformation.json
python infra/manage.py provision --region REGION --account-id ACCOUNT_ID \
  --vpc-id VPC_ID --subnet-id PUBLIC_SUBNET_ID --budget-usd APPROVED_BUDGET --execute
# Wait for bootstrap-ready / SSM registration (typically several minutes).
python infra/manage.py deploy --region REGION --account-id ACCOUNT_ID --execute
python infra/manage.py health --region REGION --account-id ACCOUNT_ID
```

If deployment fails, inspect the printed SSM command ID, `/var/log/cloud-init-output.log`, `/var/log/nginx/error.log`, and `docker compose -p stateproof logs` under `/opt/stateproof/current`. The script raises on unsuccessful commands; do not present the output URL as a verified deployment until health and the actual EC2 campaign/upload succeed. A public replay returns 403 by design. The public console's **Open a saved campaign** menu shows the actual EC2 campaign after deployment.

Teardown (requires explicit authorization for the chosen resources):

```sh
python infra/manage.py teardown --region REGION --account-id ACCOUNT_ID --execute
# Or permanently delete this stack's evidence bucket too:
python infra/manage.py teardown --region REGION --account-id ACCOUNT_ID --execute --purge-evidence
```

The bucket is retained on stack deletion, with a 14-day object expiry policy. It is not immutable: an authorized operator can change policy or delete objects. Evidence keys include build ID, campaign ID and content hash; writes use `If-None-Match: *` and a verified SHA-256 checksum. Presigned download links expire after one hour. CloudFormation's budget tag records approval; it is **not a spend limit or automatic shutdown**.

Cost planning estimate, not a live quote: reserve **US$3–6 for a 48-hour demo**, or approximately **US$35–50/month** if left running, for one t3.medium plus 20 GiB gp3, one IPv4 and under 1 GiB of evidence, excluding tax and unusual transfer. Region and usage affect charges. CPU credit mode is standard to avoid unlimited-credit surplus charges. EC2, disk, IPv4 and S3 storage can bill while idle; stopping EC2 still leaves disk/storage costs. There is no NAT gateway, load balancer or RDS instance. Check the [AWS pricing calculator](https://calculator.aws/) and current [EC2](https://aws.amazon.com/ec2/pricing/on-demand/), [EBS](https://aws.amazon.com/ebs/pricing/), [IPv4](https://aws.amazon.com/vpc/pricing/) and [S3](https://aws.amazon.com/s3/pricing/) rates for the approved region before provisioning. No free-credit assumption is included.

Sources: [CloudFormation EC2 resource](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-ec2-instance.html), [SSM sessions](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-sessions-start.html), [S3 conditional writes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html), [Compose installation](https://docs.docker.com/compose/install/linux/).
