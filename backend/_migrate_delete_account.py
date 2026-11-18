#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性脚本:users 表新增注销软删除列(deleted_at / deleted_phone)。

幂等:列已存在则跳过。用法:
    cd /opt/61api/backend && ../venv/bin/python _migrate_delete_account.py
"""
import os
import sqlite3

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "61api.db")
COLUMNS = {
    "deleted_at": "ALTER TABLE users ADD COLUMN deleted_at DATETIME",
    "deleted_phone": "ALTER TABLE users ADD COLUMN deleted_phone VARCHAR(20)",
}

con = sqlite3.connect(DB)
cur = con.cursor()
existing = {r[1] for r in cur.execute("PRAGMA table_info(users)")}
for name, ddl in COLUMNS.items():
    if name in existing:
        print(f"列 {name} 已存在,跳过")
        continue
    cur.execute(ddl)
    print(f"列 {name} 已添加")
con.commit()
con.close()
print("迁移完成")
