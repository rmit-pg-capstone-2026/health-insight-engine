import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import lambda_handler


class FakeS3Client:
    def __init__(self):
        self.downloads = []
        self.uploads = []
        self.input_content = '{"result": {}}'

    def download_file(self, bucket, key, filename):
        self.downloads.append((bucket, key, filename))
        Path(filename).write_text(self.input_content, encoding="utf-8")

    def upload_file(self, filename, bucket, key):
        self.uploads.append(
            {
                "filename": filename,
                "bucket": bucket,
                "key": key,
                "content": Path(filename).read_text(encoding="utf-8"),
            }
        )


def s3_event(key):
    return {
        "Records": [
            {
                "eventName": "ObjectCreated:Put",
                "s3": {"bucket": {"name": "poc-bucket"}, "object": {"key": key}},
            }
        ]
    }


class LambdaHandlerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_dir_patch = patch.object(
            lambda_handler.tempfile,
            "TemporaryDirectory",
            return_value=self.temp_dir,
        )
        self.temp_dir_patch.start()

    def tearDown(self):
        self.temp_dir_patch.stop()
        self.temp_dir.cleanup()

    def test_valid_event_uploads_final_and_review_with_original_filename(self):
        client = FakeS3Client()
        event = s3_event(
            "data/insight-generated-files/monthly+report%20%C3%A9.json"
        )
        seen_paths = {}

        def successful_process(input_path, args, output_dir, *, work_dir):
            seen_paths.update(
                input_path=input_path,
                output_dir=output_dir,
                work_dir=work_dir,
            )
            (output_dir / input_path.name).write_text('{"insights": []}', encoding="utf-8")
            review_path = (
                work_dir
                / "processed"
                / f"{input_path.stem}__assessment_review_required.json"
            )
            review_path.parent.mkdir()
            review_path.write_text(
                json.dumps([{"insight_id": "INSIGHT_001"}]), encoding="utf-8"
            )
            return {"ready": 1, "review": 1, "kept": 0}

        with patch.object(lambda_handler, "process_one", side_effect=successful_process):
            result = lambda_handler.lambda_handler(event, None, s3_client=client)

        self.assertEqual(
            client.downloads,
            [
                (
                    "poc-bucket",
                    "data/insight-generated-files/monthly report é.json",
                    str(seen_paths["input_path"]),
                )
            ],
        )
        self.assertEqual(seen_paths["input_path"].name, "monthly report é.json")
        self.assertEqual(seen_paths["input_path"].parent.name, "input")
        self.assertEqual(seen_paths["work_dir"].name, "work")
        self.assertEqual(seen_paths["output_dir"].name, "output")
        self.assertEqual(seen_paths["input_path"].parent.parent, seen_paths["work_dir"].parent)
        self.assertEqual(seen_paths["work_dir"].parent, seen_paths["output_dir"].parent)
        self.assertNotEqual(seen_paths["input_path"].parent, seen_paths["work_dir"])
        self.assertNotEqual(seen_paths["work_dir"], seen_paths["output_dir"])
        self.assertEqual(
            [upload["key"] for upload in client.uploads],
            [
                "data/priority-assessment-review/"
                "monthly report é__assessment_review_required.json",
                "data/priority-tagged-insight-files/monthly report é.json",
            ],
        )
        self.assertEqual(
            result,
            {
                "input_bucket": "poc-bucket",
                "input_key": "data/insight-generated-files/monthly report é.json",
                "output_key": "data/priority-tagged-insight-files/monthly report é.json",
                "review_key": "data/priority-assessment-review/"
                "monthly report é__assessment_review_required.json",
            },
        )
        self.assertNotIn("result", result)

    def test_empty_review_is_not_uploaded(self):
        client = FakeS3Client()

        def successful_process(input_path, args, output_dir, *, work_dir):
            (output_dir / input_path.name).write_text('{"insights": []}', encoding="utf-8")
            review_path = (
                work_dir
                / "processed"
                / f"{input_path.stem}__assessment_review_required.json"
            )
            review_path.parent.mkdir()
            review_path.write_text("[]", encoding="utf-8")
            return {"ready": 0, "review": 0, "kept": 0}

        with patch.object(lambda_handler, "process_one", side_effect=successful_process):
            result = lambda_handler.lambda_handler(
                s3_event("data/insight-generated-files/article.json"),
                None,
                s3_client=client,
            )

        self.assertEqual(
            [upload["key"] for upload in client.uploads],
            ["data/priority-tagged-insight-files/article.json"],
        )
        self.assertIsNone(result["review_key"])

    def test_real_zero_insight_pipeline_uploads_final_without_review(self):
        client = FakeS3Client()
        client.input_content = json.dumps(
            {
                "result": {
                    "source": {
                        "publisher": "Test publisher",
                        "title": "Test article",
                        "url": "https://example.test/article",
                        "publication_date": "2026-01-01",
                        "retrieval_date": "2026-01-02",
                    },
                    "summary": None,
                    "insights": [],
                },
                "schema_errors": [],
                "quote_checks": [],
            }
        )

        result = lambda_handler.lambda_handler(
            s3_event("data/insight-generated-files/zero-insights.json"),
            None,
            s3_client=client,
        )

        self.assertEqual(
            [upload["key"] for upload in client.uploads],
            ["data/priority-tagged-insight-files/zero-insights.json"],
        )
        self.assertEqual(
            json.loads(client.uploads[0]["content"])["insights"],
            [],
        )
        self.assertIsNone(result["review_key"])
        json.dumps(result)

    def test_review_is_persisted_before_processing_failure_is_propagated(self):
        client = FakeS3Client()

        def failed_process(input_path, args, output_dir, *, work_dir):
            review_path = (
                work_dir
                / "processed"
                / f"{input_path.stem}__assessment_review_required.json"
            )
            review_path.parent.mkdir()
            review_path.write_text(
                json.dumps([{"insight_id": "INSIGHT_002"}]), encoding="utf-8"
            )
            raise RuntimeError("model validation failed")

        with patch.object(lambda_handler, "process_one", side_effect=failed_process):
            with self.assertRaisesRegex(RuntimeError, "model validation failed"):
                lambda_handler.lambda_handler(
                    s3_event("data/insight-generated-files/article.json"),
                    None,
                    s3_client=client,
                )

        self.assertEqual(
            [upload["key"] for upload in client.uploads],
            [
                "data/priority-assessment-review/"
                "article__assessment_review_required.json"
            ],
        )

    def test_rejects_invalid_s3_event_contracts(self):
        invalid_events = {
            "zero records": {"Records": []},
            "multiple records": {
                "Records": [
                    s3_event("data/insight-generated-files/one.json")["Records"][0],
                    s3_event("data/insight-generated-files/two.json")["Records"][0],
                ]
            },
            "wrong prefix": s3_event("data/other/article.json"),
            "nested key": s3_event("data/insight-generated-files/nested/article.json"),
            "non json": s3_event("data/insight-generated-files/article.txt"),
        }

        for label, event in invalid_events.items():
            with self.subTest(label=label):
                client = FakeS3Client()
                with self.assertRaises(ValueError):
                    lambda_handler.lambda_handler(event, None, s3_client=client)
                self.assertEqual(client.downloads, [])
                self.assertEqual(client.uploads, [])


if __name__ == "__main__":
    unittest.main()
