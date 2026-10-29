cd /c/Users/saive/Documents/health-insight-engine
export PIPELINE_DATA_DIR='C:\Users\saive\AppData\Local\Temp\hie_eval\data'
unset PIPELINE_S3_BUCKET
echo "=== RUN 1 start $(date +%T)"
S=$(date +%s)
.venv/Scripts/python.exe pipeline/run.py collect
echo "=== RUN 1 secs $(( $(date +%s) - S ))"
echo "=== RUN 2 start $(date +%T)"
S=$(date +%s)
.venv/Scripts/python.exe pipeline/run.py collect
echo "=== RUN 2 secs $(( $(date +%s) - S ))"
