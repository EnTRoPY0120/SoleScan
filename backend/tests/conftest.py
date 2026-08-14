import os
from pathlib import Path

TEST_DB = Path(__file__).parents[2] / "data" / "test.sqlite3"
if TEST_DB.exists():
    TEST_DB.unlink()
os.environ["SPF_DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["SPF_RETAILER_TIMEOUT"] = "0.2"
os.environ["SPF_OVERALL_TIMEOUT"] = "1"

