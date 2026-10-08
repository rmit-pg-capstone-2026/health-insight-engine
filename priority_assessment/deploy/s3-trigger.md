# S3 trigger configuration

Configure this later on bucket `<S3_BUCKET_NAME>`:

The bucket must be in the same actual `<AWS_REGION>` as the Lambda function.
Kimi K2.5 must also be available in that region.

| Setting | Value |
| --- | --- |
| Event | S3 ObjectCreated |
| Prefix | `data/insight-generated-files/` |
| Suffix | `.json` |
| Lambda handler | `src.lambda_handler.lambda_handler` |

The handler intentionally accepts exactly one S3 record per invocation and only
accepts a flat JSON filename directly below the input prefix.

Final output is written to `data/priority-tagged-insight-files/`; review-required
output is written to `data/priority-assessment-review/`. Neither prefix matches
the trigger prefix, so Lambda output writes do not recursively trigger this
function.

Before adding a bucket notification, inspect and preserve all existing bucket
notification rules. Updating a bucket notification configuration can replace
existing notifications when it is not performed as a merged update.
