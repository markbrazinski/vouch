# Vouch IAM policy documents

These are the **intended** deployment policies for the Vouch V2 authority
boundary (audit-2 Finding 2). They are tracked source, not applied
infrastructure: a document in this directory says what the deployment must
enforce, and `tests/v2/test_iam_policy.py` asserts the documents actually say
it. Whether they have been **attached** in the account is a separate,
independently recorded fact — see `docs/architecture/v2/AWS_STATUS.md`.

No account ids appear here. `${TABLE_ARN}` and `${BUCKET}` are substituted at
deployment time from the gitignored `provisioning.json`.

| File | Principal | Purpose |
|---|---|---|
| `agent_runtime_policy.json` | agent/tool execution identity | Everything the decision pipeline needs, with capability-row writes **explicitly denied** |
| `policy_engine_policy.json` | Policy Engine identity | The only principal permitted to write `CAP#` items |

## The boundary these express

`Deny` on `dynamodb:PutItem` / `UpdateItem` / `DeleteItem` when
`dynamodb:LeadingKeys` begins with `CAP#`. An explicit `Deny` cannot be
overridden by any `Allow`, so agent code under the runtime role cannot create a
capability row even if some other policy grants it table-wide write access.

## What these documents do NOT do

They are defence in depth, not the load-bearing control. The load-bearing
control is cryptographic: every capability row carries an HMAC `issuer_proof`
over its complete binding, produced by a key only the Policy Engine's issuance
module holds, and `DynamoCapabilityStore.consume` verifies it before building
any transaction. A forged row is refused **even when the attacker has full
PutItem on the table** — which is precisely the audited condition. See
`docs/architecture/v2/CAPABILITY_SECURITY.md` for the honest statement of where
each half of the boundary holds and where it does not.
