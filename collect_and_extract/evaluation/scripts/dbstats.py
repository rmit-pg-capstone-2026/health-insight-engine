import sqlite3, os
p=r"C:\Users\saive\AppData\Local\Temp\hie_eval\data\pipeline.db"
c=sqlite3.connect(p); c.row_factory=sqlite3.Row
for t in ("sources","documents"):
    print(t, c.execute(f"select count(*) from {t}").fetchone()[0])
print([r[1] for r in c.execute("pragma table_info(documents)")])
for r in c.execute("select status, count(*) n from documents group by status"): print(dict(r))
for r in c.execute("select s.agency, s.origin, count(*) n from documents d join sources s on s.id=d.source_id group by 1,2"): print(dict(r))
for r in c.execute("select id, source_id, status, title from documents order by id"): print(tuple(r))
