import sqlite3

conn = sqlite3.connect('production.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()

print("===== prod_order_colors 表结构 =====")
c.execute("PRAGMA table_info(prod_order_colors)")
for row in c.fetchall():
    print(dict(row))

print("\n===== 前3条数据示例 =====")
c.execute("SELECT * FROM prod_order_colors LIMIT 3")
rows = c.fetchall()
for i, row in enumerate(rows):
    print(f"--- 第{i+1}条 ---")
    for key in row.keys():
        print(f"  {key}: {row[key]}")

conn.close()