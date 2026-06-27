🚀 Automating AWS Governance: Deleting Default VPCs at Scale with Step Functions
Default VPCs in every account = shadow infrastructure, misconfiguration risks, and compliance headaches.
Here's how we solved it across 100+ accounts in our AWS Organization:
🔹 AWS Step Functions orchestrates the workflow at scale
🔹 State Machine handles cross-account logic: discover → validate → delete → confirm
🔹 Lambda does the heavy lifting — querying VPCs, checking dependencies, and executing cleanup
Why Step Functions — and not just direct Lambda?
Sure, we could've invoked Lambda directly. But with 100+ accounts, that approach falls apart fast:
🎯 Orchestration over 100+ accounts — Step Functions manages the sequence across accounts without writing custom scheduler code in Lambda
🔄 Built-in retries & error handling — If an account has dependencies blocking deletion, the state machine catches it, retries, or routes to a dead-letter queue. Lambda alone would need all that boilerplate.
📊 Visual audit trail — Every execution, every account, every success/failure is visible in the Step Functions console. Try debugging 100+ Lambda invocations scattered across CloudWatch Logs.
⚡ Parallelization control — We can fan-out to process multiple accounts in parallel, but cap concurrency to avoid API throttling. Step Functions handles this natively; Lambda would need complex orchestration.
🛡️ State management — Step Functions remembers where it left off. If the job fails at account #73, we don't re-process accounts #1-72. Pure Lambda would require a DynamoDB state table — more code, more cost, more bugs.
⏱️ Timeouts & waiting — Some accounts take longer due to dependency cleanup. Step Functions waits gracefully; Lambda would burn runtime (and money) or timeout.
The flow:
1️⃣ Step Functions assumes cross-account roles via AWS Organizations
2️⃣ Lambda discovers default VPCs and their dependencies (IGWs, subnets, NATs)
3️⃣ State Machine validates it's safe to delete
4️⃣ Lambda cleans up dependencies and removes the VPC
5️⃣ Success/failure reported back to a central logging account
One state machine. 100+ accounts. Zero default VPCs. Full compliance.