import hashlib
from pathlib import Path

with Path(f"{Path(__file__).parent}/databases/CLASSIC Fallout4.yaml").open("rb") as f:
    data = f.read()
    Path("databases/CLASSIC Fallout4.yaml.sha256").write_text(hashlib.sha256(data).hexdigest())