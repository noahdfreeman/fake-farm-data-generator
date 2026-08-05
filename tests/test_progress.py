import unittest

from fake_farm_data_generator.core.progress import ProgressReporter, format_duration


class FakeFeedback:
    def __init__(self):
        self.progress = []
        self.messages = []

    def setProgress(self, value):
        self.progress.append(value)

    def pushInfo(self, value):
        self.messages.append(value)


class ProgressTests(unittest.TestCase):
    def test_duration_format(self):
        self.assertEqual(format_duration(9.6), "10s")
        self.assertEqual(format_duration(65), "1m 05s")
        self.assertEqual(format_duration(3661), "1h 01m 01s")

    def test_reporter_includes_records_elapsed_and_remaining(self):
        times = iter([100.0, 110.0, 140.0])
        feedback = FakeFeedback()
        reporter = ProgressReporter(
            feedback,
            4,
            "Yield",
            clock=lambda: next(times),
            minimum_message_interval=0,
        )
        reporter.update(1, "Field_001 2025", 250)
        reporter.update(4, "complete", 1000)
        self.assertEqual(feedback.progress, [25, 100])
        self.assertIn("250 records created", feedback.messages[0])
        self.assertIn("elapsed 10s", feedback.messages[0])
        self.assertIn("estimated remaining 30s", feedback.messages[0])
        self.assertIn("estimated remaining 0s", feedback.messages[1])

    def test_reporter_throttles_non_forced_messages(self):
        times = iter([0.0, 1.0, 2.0])
        feedback = FakeFeedback()
        reporter = ProgressReporter(
            feedback,
            10,
            "Planting",
            clock=lambda: next(times),
            minimum_message_interval=5,
        )
        reporter.update(1, "pass 1")
        reporter.update(2, "pass 2", force=True)
        self.assertEqual(len(feedback.messages), 1)
        self.assertIn("pass 2", feedback.messages[0])


if __name__ == "__main__":
    unittest.main()
