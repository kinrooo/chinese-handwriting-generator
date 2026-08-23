from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "handwriting_cli.py"
POEMS_JSON = ROOT / "examples" / "poems.json"
POEMS_TEXT = ROOT / "examples" / "poems.txt"
POEM_LINE = "明月松间照，清泉石上流。"


def run_cli(*arguments: object) -> dict[str, object]:
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [sys.executable, str(CLI), *(str(argument) for argument in arguments)]
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=180,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return json.loads(result.stdout)


class HandwritingSmokeTests(unittest.TestCase):
    def test_bundled_font_catalog_and_poetry_coverage(self) -> None:
        result = run_cli(
            "inspect-font",
            "--input",
            POEMS_JSON,
            "--field",
            "text",
        )
        self.assertEqual(result["font_count"], 6)
        self.assertEqual(result["covering_font_count"], 6)
        for font in result["fonts"]:
            self.assertEqual(font["source"], "bundled")
            self.assertEqual(font["license"], "OFL-1.1")
            self.assertTrue(font["covers_all"])
            self.assertEqual(font["missing_characters"], [])

    def test_render_is_reproducible_private_and_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            output_a = temporary_root / "render-a"
            output_b = temporary_root / "render-b"
            common = (
                "render",
                "--text",
                POEM_LINE,
                "--variants",
                6,
                "--seed",
                20260823,
                "--manifest-level",
                "minimal",
                "--hide-preview-labels",
            )
            first = run_cli(*common, "--output", output_a)
            second = run_cli(*common, "--output", output_b)

            first_manifest = json.loads(Path(first["manifest"]).read_text(encoding="utf-8"))
            second_manifest = json.loads(Path(second["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(first_manifest["schema_version"], "1.1")
            self.assertNotIn("text", json.dumps(first_manifest, ensure_ascii=False))
            self.assertNotIn("text_sha256", json.dumps(first_manifest, ensure_ascii=False))
            self.assertNotIn("source_record_id", json.dumps(first_manifest, ensure_ascii=False))
            self.assertEqual(
                [item["sha256"] for item in first_manifest["outputs"]],
                [item["sha256"] for item in second_manifest["outputs"]],
            )
            self.assertEqual(len(first["font_distribution"]), 6)
            for font in first_manifest["fonts"]:
                self.assertEqual(font["source"], "bundled")
                self.assertNotIn("path", font)

            validation = run_cli("validate", "--manifest", first["manifest"])
            self.assertTrue(validation["passed"], validation["errors"])

    def test_batch_compare_page_and_scan_modes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)

            batch = run_cli(
                "batch",
                "--input",
                POEMS_JSON,
                "--field",
                "text",
                "--variants",
                1,
                "--output",
                temporary_root / "batch",
            )
            batch_manifest = json.loads(Path(batch["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(batch["count"], 4)
            self.assertEqual(
                [item["record_id"] for item in batch_manifest["outputs"]],
                ["record-0001", "record-0002", "record-0003", "record-0004"],
            )
            self.assertTrue(
                run_cli("validate", "--manifest", batch["manifest"])["passed"]
            )

            comparison = run_cli(
                "compare",
                "--text",
                "海上生明月，天涯共此时。",
                "--presets",
                "subtle",
                "--output",
                temporary_root / "compare",
            )
            self.assertEqual(comparison["count"], 6)
            self.assertTrue(
                run_cli("validate", "--manifest", comparison["manifest"])["passed"]
            )

            page = run_cli(
                "page",
                "--input",
                POEMS_TEXT,
                "--paper",
                "lined",
                "--page-size",
                "900x1200",
                "--margin",
                70,
                "--font-size",
                46,
                "--line-spacing",
                80,
                "--output",
                temporary_root / "page",
            )
            self.assertGreaterEqual(page["count"], 1)
            self.assertTrue(run_cli("validate", "--manifest", page["manifest"])["passed"])

            scan = run_cli(
                "scan",
                "--input",
                Path(page["output"]) / "page_001.png",
                "--preset",
                "phone-scan",
                "--output",
                temporary_root / "scan",
            )
            scan_manifest = json.loads(Path(scan["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(scan["count"], 1)
            self.assertNotIn("source_name", scan_manifest["outputs"][0])
            self.assertEqual(scan_manifest["outputs"][0]["file"], "0001_scan.jpg")
            self.assertTrue(run_cli("validate", "--manifest", scan["manifest"])["passed"])


if __name__ == "__main__":
    unittest.main()
