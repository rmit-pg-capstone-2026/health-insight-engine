#!/usr/bin/env bash
# Builds dist/lambda.zip: the pipeline code plus its packages, compiled for
# AWS Lambda (Linux, x86_64, Python 3.12). One zip is used by all four stage
# functions. Run from anywhere:  ./build_lambda.sh
set -euo pipefail
cd "$(dirname "$0")"

rm -rf build/lambda dist/lambda.zip
mkdir -p build/lambda dist

echo "Installing Linux packages for Python 3.12..."
pip install -r requirements.txt --target build/lambda --quiet --upgrade \
  --implementation cp --python-version 3.12 --only-binary=:all: \
  --platform manylinux2014_x86_64 --platform manylinux_2_28_x86_64

echo "Copying code..."
for dir in pipeline collect_and_extract insight-extraction-test priority_assessment briefing; do
  cp -R "$dir" build/lambda/
done
# Local data, test runs and caches stay out of the zip.
rm -rf build/lambda/priority_assessment/data build/lambda/priority_assessment/tests \
       build/lambda/insight-extraction-test/{runs,test-runs,insight_generated_files,source_extracted_files,reference-insights,older-prompts}
find build/lambda -name "__pycache__" -type d -prune -exec rm -rf {} +
find build/lambda \( -name ".DS_Store" -o -name ".env" -o -name ".env.*" \) -delete

echo "Zipping..."
(cd build/lambda && zip -qr ../../dist/lambda.zip .)
ls -lh dist/lambda.zip
echo "Unzipped size: $(du -sh build/lambda | cut -f1)  (Lambda limit: 250 MB)"
