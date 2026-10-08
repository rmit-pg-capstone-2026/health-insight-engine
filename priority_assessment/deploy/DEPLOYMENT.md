# Priority Assessment Lambda deployment

This is a manual deployment runbook. The commands below are templates only and
must be reviewed, populated with account values, and run later. They were not
run while preparing this package.

## Prerequisites

- Confirm that `moonshotai.kimi-k2.5` is enabled and available in the selected
  `<AWS_REGION>`.
- Deploy the Lambda function and configure its direct S3 trigger in the same
  actual `<AWS_REGION>`. The trigger bucket must be in that region.
- Replace `<AWS_REGION>`, `<S3_BUCKET_NAME>`, `<AWS_ACCOUNT_ID>`, and role
  placeholders in copied policy files and commands.
- Use the Bedrock Runtime Chat Completions URL:
  `https://bedrock-runtime.<AWS_REGION>.amazonaws.com/openai/v1/chat/completions`.
- Do not set `PROMPT2_API_KEY`, `OPENAI_API_KEY`, or `AWS_PROFILE` for the
  intended Lambda execution-role SigV4 path.

## 1. Build and verify the ZIP

From the repository root in Windows PowerShell:

```powershell
.\priority_assessment\deploy\build_lambda.ps1
```

The ZIP is created at
`priority_assessment/dist/priority_assessment_lambda.zip`. Inspect its contents
before deployment; its root must contain `src/`, `prompts/`, `schemas/`, and
the Linux x86_64 dependency packages, with no enclosing `priority_assessment/`
directory.

## 2. Create or identify the execution role

Copy the inline policy template, replace its placeholders, then use templates
like these:

```powershell
aws iam create-role `
  --role-name health-insight-priority-assessment-role `
  --assume-role-policy-document file://priority_assessment/deploy/lambda-trust-policy.json

aws iam attach-role-policy `
  --role-name health-insight-priority-assessment-role `
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

aws iam put-role-policy `
  --role-name health-insight-priority-assessment-role `
  --policy-name health-insight-priority-assessment-access `
  --policy-document file://priority_assessment/deploy/lambda-inline-policy.json
```

`AWSLambdaBasicExecutionRole` supplies the standard CloudWatch Logs permissions.
The inline policy is limited to input reads, final/review writes, and
`bedrock:InvokeModel` for Kimi K2.5.

## 3. Create the Lambda function and upload the ZIP

Use the reviewed values in `lambda-config.template.json`. A creation template is:

```powershell
$Endpoint = 'https://bedrock-runtime.<AWS_REGION>.amazonaws.com/openai/v1/chat/completions'

aws lambda create-function `
  --region <AWS_REGION> `
  --function-name health-insight-priority-assessment `
  --runtime python3.12 `
  --architectures x86_64 `
  --role arn:aws:iam::<AWS_ACCOUNT_ID>:role/health-insight-priority-assessment-role `
  --handler src.lambda_handler.lambda_handler `
  --zip-file fileb://priority_assessment/dist/priority_assessment_lambda.zip `
  --timeout 480 `
  --memory-size 512 `
  --ephemeral-storage Size=512 `
  --environment "Variables={PROMPT2_API_URL=$Endpoint,PROMPT2_MODEL=moonshotai.kimi-k2.5}"
```

For a later code update, use:

```powershell
aws lambda update-function-code `
  --region <AWS_REGION> `
  --function-name health-insight-priority-assessment `
  --zip-file fileb://priority_assessment/dist/priority_assessment_lambda.zip
```

Confirm runtime, architecture, handler, timeout, memory, ephemeral storage, and
environment configuration after creation. Lambda provides `AWS_REGION`; the
execution role provides credentials for the existing SigV4 request path.

## 4. Configure the S3 ObjectCreated trigger

Use the settings in [s3-trigger.md](s3-trigger.md):

- bucket: `<S3_BUCKET_NAME>`
- prefix: `data/insight-generated-files/`
- suffix: `.json`

First add Lambda permission for the bucket:

```powershell
aws lambda add-permission `
  --region <AWS_REGION> `
  --function-name health-insight-priority-assessment `
  --statement-id allow-s3-priority-assessment-input `
  --action lambda:InvokeFunction `
  --principal s3.amazonaws.com `
  --source-arn arn:aws:s3:::<S3_BUCKET_NAME> `
  --source-account <AWS_ACCOUNT_ID>
```

Then create the S3 notification rule through the console or a reviewed merged
notification configuration. `aws s3api put-bucket-notification-configuration`
can replace existing bucket notification rules, so never run it with a partial
configuration.

## 5. Controlled end-to-end test

1. Review [s3-test-event.template.json](s3-test-event.template.json). Its key
   uses the S3 event representation. For filenames containing spaces or other
   reserved characters, use the URL-encoded key form S3 emits; the handler
   decodes it with `unquote_plus`.
2. Upload one known valid Prompt 1 JSON directly under
   `data/insight-generated-files/`.
3. Inspect the function's CloudWatch logs for preprocessing, model invocation,
   validation/retry, aggregation, and consolidation results.
4. Confirm exactly one final file with the same input filename at
   `data/priority-tagged-insight-files/`.
5. Confirm a nonempty review-required artifact at
   `data/priority-assessment-review/` when upstream quote checks require it.
6. Run the existing briefing module against the final output to confirm it can
   consume the generated file.

The handler processes exactly one S3 record and only a flat `.json` input key.
The output and review prefixes differ from the input prefix, so their uploads
do not recursively trigger the function.
