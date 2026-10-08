# Priority Assessment Lambda deployment manifest

| Item | Value |
| --- | --- |
| Runtime | `python3.12` |
| Architecture | `x86_64` |
| Handler | `src.lambda_handler.lambda_handler` |
| Timeout | 480 seconds |
| Memory | 512 MB |
| Ephemeral storage | 512 MB |
| Model | `moonshotai.kimi-k2.5` |
| API URL | `https://bedrock-runtime.<AWS_REGION>.amazonaws.com/openai/v1/chat/completions` |
| ZIP path | `priority_assessment/dist/priority_assessment_lambda.zip` |
| Input prefix | `data/insight-generated-files/` |
| Final prefix | `data/priority-tagged-insight-files/` |
| Review prefix | `data/priority-assessment-review/` |

`<AWS_REGION>` is the actual deployment region. The Lambda function and the
direct-trigger S3 bucket must be in the same region, and Kimi K2.5 must be
available there.

Configure only `PROMPT2_API_URL` and `PROMPT2_MODEL`. Lambda supplies
`AWS_REGION` and execution-role credentials. Do not configure
`PROMPT2_API_KEY`, `OPENAI_API_KEY`, or `AWS_PROFILE` for the intended SigV4
path.

The inline policy grants `s3:GetObject`, `s3:PutObject`, and
`bedrock:InvokeModel`. Attach the AWS managed `AWSLambdaBasicExecutionRole` for
CloudWatch Logs permissions.

This PoC intentionally relies on the boto3 and botocore versions supplied by
the managed Lambda Python runtime. Packaging and pinning those libraries can be
considered later for production dependency reproducibility.

The ZIP includes `src/`, `prompts/`, `schemas/`, and the dependencies installed
from `requirements-lambda.txt`. It excludes tests, data, backup content,
virtual environments, `.env`, Git metadata, `AGENTS.md`, patch files,
`__pycache__`, and `.pyc` files.
