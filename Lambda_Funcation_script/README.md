# AWS Default VPC Cleanup via Step Functions & Lambda

Automated deletion of default VPCs across 100+ AWS accounts using AWS Organizations, Step Functions, and Lambda.

---

## Table of Contents

- [Problem Statement](#problem-statement)
- [Why Step Functions Over Direct Lambda?](#why-step-functions-over-direct-lambda)
- [Architecture](#architecture)
- [State Machine Flow](#state-machine-flow)
- [Prerequisites](#prerequisites)
- [Deployment](#deployment)
- [Security & Permissions](#security--permissions)
- [Monitoring & Observability](#monitoring--observability)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Problem Statement

Every new AWS account automatically provisions a **default VPC** in each enabled region. For organizations with 100+ member accounts, this results in:

- **Shadow infrastructure** — unused network resources accumulating across regions
- **Security risks** — default VPCs often bypass network segmentation policies
- **Compliance violations** — auditors flag default VPCs as non-compliant in regulated environments
- **Operational overhead** — manual cleanup across hundreds of accounts and regions is not scalable

**Goal:** Automatically discover and delete all default VPCs across every account and region in an AWS Organization.

---

## Why Step Functions Over Direct Lambda?

| Challenge | Direct Lambda Approach | Step Functions Approach |
|-----------|----------------------|------------------------|
| **Orchestration** | One Lambda per account/region = 100+ concurrent invocations. Hard to track, retry, and sequence. | Native orchestration across accounts with visual workflow. Parallel or sequential execution controlled declaratively. |
| **Error Handling** | Custom retry logic, DLQs, and state management must be built from scratch inside Lambda code. | Built-in retries, catch blocks, dead-letter queues, and error states. Failures are isolated and don't crash the entire batch. |
| **Timeouts** | Lambda max timeout = 15 minutes. Deleting a VPC with many dependencies (subnets, IGWs, NATs, ENIs) can exceed this. | Step Functions standard workflows can run up to **1 year**. Long-running dependency cleanup is split across multiple Lambda invocations. |
| **Observability** | CloudWatch Logs only. No visual execution trace. Debugging 100+ parallel Lambdas is painful. | Visual execution graph. Every state transition is logged. See exactly which account/region failed and why. |
| **Cross-Account Role Assumption** | Lambda must handle STS AssumeRole logic, credential caching, and session management manually. | Step Functions natively integrates with IAM and cross-account roles via service integrations. |
| **State Persistence** | Need external database (DynamoDB) to track which accounts are done, in-progress, or failed. | Step Functions persists execution state automatically. No external state store needed. |
| **Human Approval Gates** | Not possible without building a custom API/SNS workflow. | Step Functions can integrate with SNS, SQS, or Callback patterns for approval workflows before destructive actions. |
| **Cost at Scale** | 100+ Lambdas running for minutes each = high concurrent execution costs. | Step Functions charges per state transition, but orchestration is cheaper than building and maintaining a custom scheduler. |

> **Bottom line:** Step Functions is the **control plane**; Lambda is the **worker**. Separation of concerns makes the solution maintainable, observable, and resilient at scale.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Management Account                              │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────────┐   │
│  │   EventBridge   │───▶│  Step Functions │───▶│   Lambda (Orchestrator)│   │
│  │  (Weekly Trigger)│    │   (State Machine)│    │                      │   │
│  └─────────────────┘    └────────┬────────┘    └─────────────────────┘   │
│                                   │                                          │
│                                   │ Cross-Account AssumeRole                 │
│                                   ▼                                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ STS AssumeRole
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Member Account (1..N)                              │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────────┐   │
│  │  IAM Role       │◀───│  Lambda (Worker)│◀───│  Step Functions     │   │
│  │  (Cross-Account)│    │  (VPC Cleanup)  │    │  (Distributed Map)    │   │
│  └─────────────────┘    └─────────────────┘    └─────────────────────┘   │
│           │                                                                    │
│           ▼                                                                    │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Per-Region Execution:                                              │   │
│  │  1. List Default VPCs                                               │   │
│  │  2. Delete Dependencies (Subnets, IGWs, NATs, Security Groups)      │   │
│  │  3. Delete Default VPC                                              │   │
│  │  4. Report Status Back to Management Account                        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## State Machine Flow

```
┌─────────────┐
│   Start     │
└──────┬──────┘
       │
       ▼
┌─────────────────────┐
│  Get Account List   │  ◄── Lambda queries AWS Organizations API
│  from Organizations │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Distributed Map    │  ◄── Iterate over all accounts (up to 40 concurrent)
│  (Per Account)      │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Assume Cross-      │  ◄── STS AssumeRole into member account
│  Account Role       │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Get Enabled        │  ◄── Lambda queries EC2 DescribeRegions
│  Regions            │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Inner Distributed  │  ◄── Iterate over all regions per account
│  Map (Per Region)   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Discover Default   │  ◄── Lambda: DescribeVpcs (isDefault=true)
│  VPC & Dependencies │
└──────────┬──────────┘
           │
     ┌─────┴─────┐
     │           │
     ▼           ▼
┌─────────┐ ┌─────────┐
│ Default │ │  None   │
│ Exists  │ │ Found   │
└────┬────┘ └────┬────┘
     │           │
     ▼           ▼
┌─────────────────────┐ ┌─────────────────────┐
│  Delete Dependencies│ │  Mark as Compliant  │
│  (Subnets, IGWs,    │ │  (No Action Needed) │
│   NATs, ENIs, SGs)  │ └─────────────────────┘
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Delete Default VPC │
└──────────┬──────────┘
           │
     ┌─────┴─────┐
     │           │
     ▼           ▼
┌─────────┐ ┌─────────┐
│ Success │ │ Failure │
└────┬────┘ └────┬────┘
     │           │
     ▼           ▼
┌─────────────────────┐ ┌─────────────────────┐
│  Report Success     │ │  Catch & Retry      │
│  to Central Log     │ │  (Max 3 attempts)   │
└─────────────────────┘ └──────────┬──────────┘
                                   │
                                   ▼
                          ┌─────────────────────┐
                          │  Send to DLQ / SNS  │
                          │  for Manual Review  │
                          └─────────────────────┘
```

---

## Prerequisites

### Management Account
- AWS Organizations with all member accounts
- Step Functions state machine
- Lambda function (Orchestrator / Account Lister)
- IAM role for Step Functions with `sts:AssumeRole` permissions

### Member Accounts
- Cross-account IAM role (deployed via CloudFormation StackSets or Terraform) with these permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeVpcs",
        "ec2:DescribeSubnets",
        "ec2:DescribeInternetGateways",
        "ec2:DescribeNatGateways",
        "ec2:DescribeNetworkInterfaces",
        "ec2:DescribeSecurityGroups",
        "ec2:DeleteVpc",
        "ec2:DeleteSubnet",
        "ec2:DeleteInternetGateway",
        "ec2:DetachInternetGateway",
        "ec2:DeleteNatGateway",
        "ec2:DeleteSecurityGroup",
        "ec2:DescribeRegions"
      ],
      "Resource": "*"
    }
  ]
}
```

### Trust Policy (Member Account Role)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::<MANAGEMENT-ACCOUNT-ID>:role/StepFunctionsVPCCleanupRole"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

---

## Deployment

### 1. Deploy Cross-Account Role to All Members

Use **AWS CloudFormation StackSets** or **Terraform** to deploy the IAM role to every member account.

### 2. Deploy State Machine & Lambda (Management Account)

```bash
# Deploy via AWS SAM
cd infrastructure/
sam build
sam deploy --guided
```

### 3. Trigger Execution

**Option A:** EventBridge scheduled rule (weekly)
**Option B:** Manual invocation via AWS Console or CLI

```bash
aws stepfunctions start-execution   --state-machine-arn arn:aws:states:<region>:<account>:stateMachine:DefaultVPCCleanup   --name "manual-cleanup-$(date +%s)"
```

---

## Security & Permissions

| Layer | Consideration |
|-------|--------------|
| **Least Privilege** | Cross-account role has only EC2 read/delete permissions. No broad admin access. |
| **Audit Trail** | All Step Functions executions and Lambda invocations are logged to CloudTrail. |
| **Encryption** | Step Functions execution history and Lambda environment variables use KMS encryption. |
| **Approval Gates** | Optional: Add a `Choice` state in Step Functions to pause for manual approval before deletion. |
| **Exclusion List** | Maintain a DynamoDB table of account/region pairs to skip (e.g., sandbox accounts that need default VPCs). |

---

## Monitoring & Observability

| Tool | Purpose |
|------|---------|
| **Step Functions Console** | Visual execution graph. Drill into failed states. |
| **CloudWatch Logs** | Lambda execution logs and VPC deletion details. |
| **CloudWatch Metrics** | Track success/failure rates, execution duration, accounts processed. |
| **SNS / Email Alerts** | Notify on failures or completion. |
| **Central S3 Bucket** | Aggregate execution reports from all member accounts. |

### Sample CloudWatch Dashboard Widget

```json
{
  "type": "metric",
  "properties": {
    "metrics": [
      [ "AWS/States", "ExecutionsSucceeded", "StateMachineArn", "arn:aws:states:us-east-1:123456789012:stateMachine:DefaultVPCCleanup" ],
      [ ".", "ExecutionsFailed", ".", "." ]
    ],
    "period": 3600,
    "stat": "Sum",
    "region": "us-east-1",
    "title": "VPC Cleanup Execution Status"
  }
}
```

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-----------|-----|
| `DependencyViolation` on VPC delete | ENI still attached to a resource (e.g., Lambda, RDS, ELB) | Add a wait state + retry, or skip VPCs with active ENIs |
| `AccessDenied` on AssumeRole | Trust policy missing management account role | Update IAM trust policy in member accounts |
| Throttling from EC2 API | Too many concurrent API calls | Reduce `MaxConcurrency` in Distributed Map state |
| VPC not found | Already deleted or not default | Add idempotency check in Lambda |
| Execution timeout | 15-min Lambda limit hit | Use Step Functions `Standard` workflow + multiple Lambda steps |

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Contributing

Pull requests welcome. For major changes, please open an issue first to discuss what you would like to change.

---

> **Disclaimer:** Deleting default VPCs is a destructive action. Always test in a non-production environment first. Maintain an exclusion list for accounts/regions that require default VPCs.
