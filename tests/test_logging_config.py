import tempfile
import logging
import unittest
from pathlib import Path

from src.shared.logging_config import setup_logging, get_logger


class LoggingConfigTests(unittest.TestCase):
    def test_setup_logging_with_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "app.log"
            logger = setup_logging(log_level="DEBUG", log_file=log_file, console_output=False)
            logger.debug("test")
            self.assertTrue(log_file.exists())
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)
            logger.addHandler(logging.NullHandler())
            logger.propagate = False

    def test_get_logger_name(self):
        logger = get_logger("module")
        self.assertTrue(logger.name.endswith("tf2_skin_generator.module"))


if __name__ == "__main__":
    unittest.main()
