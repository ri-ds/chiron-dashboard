"""Unit tests for chironval.report.write_json_report's failure handling.

Run with:  python -m unittest discover   (from the chiron-data-validator/ dir)
"""

import os
import tempfile
import unittest

from chironval.report import write_json_report


class TestWriteJsonReport(unittest.TestCase):
    def test_writes_report_to_a_valid_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.json")
            write_json_report(path, {"hello": "world"})
            with open(path, "r", encoding="utf-8") as f:
                self.assertIn("hello", f.read())

    def test_missing_parent_directory_raises_informative_oserror_not_a_crash(self):
        # Regression: an unwritable --json-out path (e.g. a parent directory
        # that does not exist) must raise a plain, catchable OSError that
        # names the path, not an uncaught traceback. cli.py is responsible
        # for catching this and mapping it to exit code 2.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "does_not_exist", "out.json")
            with self.assertRaises(OSError) as ctx:
                write_json_report(path, {"hello": "world"})
            self.assertIn(path, str(ctx.exception))

    def test_unwritable_directory_raises_informative_oserror(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.json")
            os.chmod(tmp, 0o500)  # read+execute only, no write
            try:
                with self.assertRaises(OSError) as ctx:
                    write_json_report(path, {"hello": "world"})
                self.assertIn(path, str(ctx.exception))
            finally:
                os.chmod(tmp, 0o700)  # restore so TemporaryDirectory cleanup can delete it


if __name__ == "__main__":
    unittest.main()
