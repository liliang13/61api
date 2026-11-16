import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


BACKEND = Path(__file__).resolve().parents[1]


def environment(tmp_path):
    env = os.environ.copy()
    env.update({
        "APP_ENV": "development",
        "DATABASE_URL": "sqlite:///" + (tmp_path / "operations.db").as_posix(),
        "PAYKIT_PATH": "",
        "ADMIN_PASSWORD": "operations-test-password",
    })
    return env


def run_manage(tmp_path, *args):
    return subprocess.run(
        [sys.executable, "manage.py", *args], cwd=BACKEND, env=environment(tmp_path),
        check=True, capture_output=True, text=True, timeout=60,
    )


def test_migration_is_idempotent_and_hashes_existing_keys(tmp_path):
    run_manage(tmp_path, "migrate")
    database = tmp_path / "operations.db"
    with sqlite3.connect(database) as conn:
        conn.execute("INSERT INTO models (name, display_name, input_price, output_price) VALUES ('custom-model', 'Custom', 9, 18)")
        conn.execute("INSERT INTO usage_logs (user_id, model, request_id, quota, status) VALUES (1, 'custom-model', 'legacy-check', 25, 'ok')")
        conn.execute("INSERT INTO api_keys (user_id, key, status) VALUES (1, 'sk-legacy-key-that-must-be-hashed', 1)")
        conn.execute("UPDATE settings SET value='2' WHERE key='catalog_version'")
        conn.commit()
    run_manage(tmp_path, "migrate")
    run_manage(tmp_path, "migrate")
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM models WHERE name='custom-model'").fetchone()[0] == 1
        assert conn.execute("SELECT quota FROM usage_logs WHERE request_id='legacy-check'").fetchone()[0] == 25
        key, prefix, last4 = conn.execute("SELECT key, key_prefix, key_last4 FROM api_keys WHERE user_id=1").fetchone()
        assert key != "sk-legacy-key-that-must-be-hashed"
        assert not key.startswith("sk-")
        assert prefix == "sk-legac"
        assert last4 == "shed"


def test_backup_creates_consistent_copies_and_readiness_check(tmp_path):
    run_manage(tmp_path, "migrate")
    target = tmp_path / "backups"
    result = run_manage(tmp_path, "backup", "--target", str(target))
    backup_dir = Path(result.stdout.strip().splitlines()[-1])
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["databases"]["61api.db"]["integrity"] == "ok"
    with sqlite3.connect(backup_dir / "61api.db") as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    check = run_manage(tmp_path, "check")
    assert '"ok": true' in check.stdout
