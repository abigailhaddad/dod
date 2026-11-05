"""Settings shared by the scripts. Change a value here, or set the environment
variable, to point the pipeline at a different Hugging Face dataset."""
import os

from dotenv import load_dotenv

load_dotenv()

# The Hugging Face dataset every script reads from and the scraper writes to.
REPO_ID = os.environ.get("HF_DATASET_REPO", "abigailhaddad/dod-daily-contracts")
