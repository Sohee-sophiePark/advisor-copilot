"""Local SQLite store: client data seeded from the synthetic JSON, plus app state (threads, usage, caches)."""

import hashlib
import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS instruments (ticker TEXT PRIMARY KEY, name TEXT, asset_class TEXT, risk_bucket TEXT,
  price_cad REAL, listing TEXT, income_type TEXT, single_security INTEGER);
CREATE TABLE IF NOT EXISTS clients (client_id TEXT PRIMARY KEY, name TEXT, age INTEGER, province TEXT,
  risk_profile TEXT, time_horizon_years INTEGER, objectives TEXT, annual_income_cad REAL, liquidity_needs TEXT,
  kyc_last_reviewed TEXT, tfsa_room_cad REAL, rrsp_room_cad REAL, life_stage TEXT, review_due TEXT,
  last_contact TEXT, preferences TEXT);
CREATE TABLE IF NOT EXISTS accounts (account_id TEXT PRIMARY KEY, client_id TEXT REFERENCES clients, type TEXT);
CREATE TABLE IF NOT EXISTS holdings (account_id TEXT REFERENCES accounts, ticker TEXT REFERENCES instruments, units REAL);
CREATE TABLE IF NOT EXISTS goals (client_id TEXT REFERENCES clients, goal_id TEXT, name TEXT, target_cad REAL,
  target_year INTEGER);
CREATE TABLE IF NOT EXISTS notes (note_id TEXT PRIMARY KEY, client_id TEXT REFERENCES clients, date TEXT,
  author TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS reference (name TEXT PRIMARY KEY, doc TEXT);
CREATE TABLE IF NOT EXISTS threads (thread_id TEXT PRIMARY KEY, client_id TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS messages (thread_id TEXT, seq INTEGER, role TEXT, text TEXT, run_id TEXT,
  route TEXT, calls INTEGER DEFAULT 0, tokens INTEGER DEFAULT 0, created_at TEXT, PRIMARY KEY (thread_id, seq));
CREATE TABLE IF NOT EXISTS usage (day TEXT, model TEXT, calls INTEGER, tokens_in INTEGER, tokens_out INTEGER,
  PRIMARY KEY (day, model));
CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT, created_at TEXT);
"""
CLIENT_COLS = [
    "client_id",
    "name",
    "age",
    "province",
    "risk_profile",
    "time_horizon_years",
    "objectives",
    "annual_income_cad",
    "liquidity_needs",
    "kyc_last_reviewed",
    "tfsa_room_cad",
    "rrsp_room_cad",
    "life_stage",
    "review_due",
    "last_contact",
    "preferences",
]
JSON_COLS = {"objectives", "preferences"}
SOURCE_FILES = [
    "instruments.json",
    "clients.json",
    "crm_notes.json",
    "book.json",
    "model_portfolios.json",
    "capital_market_assumptions.json",
    "market_snapshot.json",
    "fund_facts.json",
]


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def source_hash(data_dir: Path) -> str:
    return hashlib.sha256(b"".join((data_dir / f).read_bytes() for f in SOURCE_FILES)).hexdigest()


def seed(raw: dict, data_dir: Path, path: Path) -> None:
    """Rebuild client data tables from `raw` (as read from JSON); app tables are kept."""
    with connect(path) as conn:
        for t in ("instruments", "clients", "accounts", "holdings", "goals", "notes", "reference"):
            conn.execute(f"DELETE FROM {t}")  # noqa: S608 — fixed table names
        conn.executemany(
            "INSERT INTO instruments VALUES (?,?,?,?,?,?,?,?)",
            [tuple(i.values()) for i in raw["instruments"]],
        )
        for c in raw["clients"]:
            conn.execute(
                f"INSERT INTO clients VALUES ({','.join('?' * len(CLIENT_COLS))})",
                [json.dumps(c.get(k)) if k in JSON_COLS else c.get(k) for k in CLIENT_COLS],
            )
            for a in c["accounts"]:
                conn.execute(
                    "INSERT INTO accounts VALUES (?,?,?)",
                    (a["account_id"], c["client_id"], a["type"]),
                )
                conn.executemany(
                    "INSERT INTO holdings VALUES (?,?,?)",
                    [(a["account_id"], h["ticker"], h["units"]) for h in a["holdings"]],
                )
            conn.executemany(
                "INSERT INTO goals VALUES (?,?,?,?,?)",
                [
                    (c["client_id"], g["goal_id"], g["name"], g["target_cad"], g["target_year"])
                    for g in c.get("goals", [])
                ],
            )
        conn.executemany(
            "INSERT INTO notes VALUES (?,?,?,?,?)",
            [
                (n["note_id"], n["client_id"], n["date"], n["author"], n["text"])
                for n in raw["notes"]
            ],
        )
        for name in ("model_portfolios", "cma", "market", "facts"):
            conn.execute("INSERT INTO reference VALUES (?,?)", (name, json.dumps(raw[name])))
        conn.execute(
            "INSERT OR REPLACE INTO meta VALUES ('source_hash', ?)", (source_hash(data_dir),)
        )


def load(path: Path) -> dict:
    """Client data in the same shape `seed` received."""
    with connect(path) as conn:

        def q(sql: str, *a: object) -> list[dict]:
            return [dict(r) for r in conn.execute(sql, a)]

        instruments = [
            {**r, "single_security": bool(r["single_security"])}
            for r in q("SELECT * FROM instruments")
        ]
        clients = []
        for r in q("SELECT * FROM clients ORDER BY rowid"):
            c = {k: json.loads(v) if k in JSON_COLS else v for k, v in r.items()}
            c["accounts"] = [
                {
                    "account_id": a["account_id"],
                    "type": a["type"],
                    "holdings": q(
                        "SELECT ticker, units FROM holdings WHERE account_id=? ORDER BY rowid",
                        a["account_id"],
                    ),
                }
                for a in q(
                    "SELECT * FROM accounts WHERE client_id=? ORDER BY rowid", c["client_id"]
                )
            ]
            c["goals"] = q(
                "SELECT goal_id, name, target_cad, target_year FROM goals WHERE client_id=? ORDER BY rowid",
                c["client_id"],
            )
            clients.append(c)
        ref = {r["name"]: json.loads(r["doc"]) for r in q("SELECT * FROM reference")}
        return {
            "instruments": instruments,
            "clients": clients,
            "notes": q("SELECT note_id, client_id, date, author, text FROM notes ORDER BY rowid"),
            **ref,
        }


def stored_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    with connect(path) as conn:
        row = conn.execute("SELECT value FROM meta WHERE key='source_hash'").fetchone()
        return row["value"] if row else None


class Store:
    """App state in the same SQLite file: chat threads, daily usage, caches."""

    def __init__(self, path: Path) -> None:
        self.conn = connect(path)

    def cache_get(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM cache WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def cache_put(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO cache VALUES (?,?,datetime('now'))", (key, value)
            )

    def usage_today(self, model: str) -> int:
        row = self.conn.execute(
            "SELECT calls FROM usage WHERE day=date('now') AND model=?", (model,)
        ).fetchone()
        return row["calls"] if row else 0

    def add_usage(self, model: str, tokens_in: int, tokens_out: int) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO usage VALUES (date('now'),?,1,?,?) ON CONFLICT(day, model) DO UPDATE SET "
                "calls=calls+1, tokens_in=tokens_in+excluded.tokens_in, tokens_out=tokens_out+excluded.tokens_out",
                (model, tokens_in, tokens_out),
            )

    def usage(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM usage ORDER BY day DESC, model")]

    def create_thread(self, thread_id: str, client_id: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO threads VALUES (?,?,datetime('now'))", (thread_id, client_id)
            )

    def threads(self, client_id: str) -> list[dict]:
        """A client's threads that have messages, newest first, titled by their first question."""
        sql = (
            "SELECT t.thread_id, t.created_at, COUNT(m.seq) AS messages, "
            "(SELECT text FROM messages WHERE thread_id=t.thread_id AND seq=1) AS title "
            "FROM threads t JOIN messages m USING (thread_id) WHERE t.client_id=? "
            "GROUP BY t.thread_id ORDER BY t.rowid DESC LIMIT 20"
        )
        return [dict(r) for r in self.conn.execute(sql, (client_id,))]

    def thread_client(self, thread_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT client_id FROM threads WHERE thread_id=?", (thread_id,)
        ).fetchone()
        return row["client_id"] if row else None

    def add_message(
        self,
        thread_id: str,
        role: str,
        text: str,
        run_id: str | None = None,
        route: str | None = None,
        calls: int = 0,
        tokens: int = 0,
    ) -> None:
        with self.conn:
            seq = self.conn.execute(
                "SELECT COUNT(*) FROM messages WHERE thread_id=?", (thread_id,)
            ).fetchone()[0]
            self.conn.execute(
                "INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,datetime('now'))",
                (thread_id, seq + 1, role, text, run_id, route, calls, tokens),
            )

    def messages(self, thread_id: str) -> list[dict]:
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM messages WHERE thread_id=? ORDER BY seq", (thread_id,)
            )
        ]

    def thread_totals(self, thread_id: str) -> tuple[int, int]:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(calls),0), COALESCE(SUM(tokens),0) FROM messages WHERE thread_id=?",
            (thread_id,),
        ).fetchone()
        return row[0], row[1]
