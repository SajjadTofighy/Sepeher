import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend" if (root / "backend/app").is_dir() else root))
from app.main import app

schema = json.dumps(app.openapi(), ensure_ascii=False, indent=2)
(root / "docs/openapi.json").write_text(schema, encoding="utf-8")
if (root / "frontend").is_dir():
    (root / "frontend/openapi.json").write_text(schema, encoding="utf-8")
print("docs/openapi.json updated")
