"""Transactional checkpoints and durable decision/API journals."""

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

from tass.types import Decision, Event, Observation


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class RunStore:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.directory / "run.sqlite", timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS ticks (
                tick INTEGER PRIMARY KEY, snapshot TEXT NOT NULL, metrics TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT UNIQUE NOT NULL, tick INTEGER NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS decisions (
                tick INTEGER NOT NULL, actor TEXT NOT NULL, data TEXT NOT NULL,
                PRIMARY KEY(tick, actor));
            CREATE TABLE IF NOT EXISTS observations (
                tick INTEGER NOT NULL, actor TEXT NOT NULL, data TEXT NOT NULL,
                PRIMARY KEY(tick, actor));
            CREATE TABLE IF NOT EXISTS calls (
                call_id INTEGER PRIMARY KEY AUTOINCREMENT,
                tick INTEGER NOT NULL, actor TEXT NOT NULL, request TEXT NOT NULL,
                response TEXT, status TEXT NOT NULL, input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL, estimated INTEGER NOT NULL DEFAULT 1,
                error TEXT);
            CREATE TABLE IF NOT EXISTS traces (
                tick INTEGER NOT NULL, actor TEXT NOT NULL, data TEXT NOT NULL,
                PRIMARY KEY(tick, actor));
            """
        )

    def close(self):
        self.connection.close()

    def get(self, key: str, default=None):
        row = self.connection.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key: str, value):
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO metadata VALUES (?, ?)", (key, encode(value))
            )

    def save_decision(self, tick: int, actor: str, decision: Decision):
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO decisions VALUES (?, ?, ?)",
                (tick, actor, decision.model_dump_json()),
            )

    def save_observations(self, tick: int, observations: dict[str, Observation]):
        with self.connection:
            self.connection.executemany(
                "INSERT OR IGNORE INTO observations VALUES (?, ?, ?)",
                [
                    (tick, actor, observation.model_dump_json())
                    for actor, observation in observations.items()
                ],
            )

    def observation(self, tick: int, actor: str) -> Observation | None:
        row = self.connection.execute(
            "SELECT data FROM observations WHERE tick=? AND actor=?", (tick, actor)
        ).fetchone()
        return Observation.model_validate_json(row[0]) if row else None

    def decision(self, tick: int, actor: str) -> Decision | None:
        row = self.connection.execute(
            "SELECT data FROM decisions WHERE tick=? AND actor=?", (tick, actor)
        ).fetchone()
        return Decision.model_validate_json(row[0]) if row else None

    def commit_tick(self, tick: int, snapshot: dict, metrics: dict, events: list[Event]):
        with self.connection:
            self.connection.execute(
                "INSERT INTO ticks VALUES (?, ?, ?)", (tick, encode(snapshot), encode(metrics))
            )
            self.connection.executemany(
                "INSERT INTO events(event_id, tick, data) VALUES (?, ?, ?)",
                [(event.event_id, event.tick, event.model_dump_json()) for event in events],
            )

    def snapshot(self, tick: int | None = None) -> dict | None:
        if tick is None:
            row = self.connection.execute(
                "SELECT snapshot FROM ticks ORDER BY tick DESC LIMIT 1"
            ).fetchone()
        else:
            row = self.connection.execute(
                "SELECT snapshot FROM ticks WHERE tick=?", (tick,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def metrics(self) -> list[dict]:
        return [
            json.loads(row[0])
            for row in self.connection.execute(
                "SELECT metrics FROM ticks WHERE tick>=0 ORDER BY tick"
            )
        ]

    def events(self, tick: int | None = None) -> list[dict]:
        query = "SELECT data FROM events"
        arguments = ()
        if tick is not None:
            query += " WHERE tick=?"
            arguments = (tick,)
        query += " ORDER BY sequence"
        return [json.loads(row[0]) for row in self.connection.execute(query, arguments)]

    def usage(self) -> dict:
        row = self.connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0), "
            "COALESCE(SUM(estimated),0) FROM calls"
        ).fetchone()
        return dict(
            zip(["requests", "input_tokens", "output_tokens", "estimated_calls"], row, strict=True)
        )

    def reserve_call(self, tick: int, actor: str, request: dict, inputs: int, outputs: int) -> int:
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO calls(tick,actor,request,status,input_tokens,output_tokens) "
                "VALUES (?,?,?,'pending',?,?)",
                (tick, actor, encode(request), inputs, outputs),
            )
        return cursor.lastrowid

    def finish_call(self, call_id: int, response: dict | None, error: str | None = None):
        usage = (response or {}).get("usage") or {}
        actual = "prompt_tokens" in usage and "completion_tokens" in usage
        with self.connection:
            self.connection.execute(
                "UPDATE calls SET response=?,status=?,error=? WHERE call_id=?",
                (encode(response), "failed" if error else "complete", error, call_id),
            )
            if actual:
                self.connection.execute(
                    "UPDATE calls SET input_tokens=?,output_tokens=?,estimated=0 WHERE call_id=?",
                    (
                        max(0, int(usage["prompt_tokens"])),
                        max(0, int(usage["completion_tokens"])),
                        call_id,
                    ),
                )

    def completed_responses(self, tick: int, actor: str) -> list[dict]:
        rows = self.connection.execute(
            "SELECT request,response FROM calls WHERE tick=? AND actor=? "
            "AND status='complete' ORDER BY call_id",
            (tick, actor),
        )
        return [{"request": json.loads(row[0]), "response": json.loads(row[1])} for row in rows]

    def save_trace(self, tick: int, actor: str, trace: list[dict]):
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO traces VALUES (?,?,?)", (tick, actor, encode(trace))
            )

    def export(self):
        with (self.directory / "events.jsonl").open("w", encoding="utf-8") as stream:
            for event in self.events():
                stream.write(encode(event) + "\n")
        metrics = self.metrics()
        if metrics:
            with (self.directory / "metrics.csv").open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(metrics[0]))
                writer.writeheader()
                writer.writerows(metrics)
        manifest = {
            "config": self.get("config"),
            "versions": self.get("versions"),
            "status": self.get("status"),
            "usage": self.usage(),
            "validation": self.get("validation"),
        }
        (self.directory / "run.json").write_text(encode(manifest) + "\n", encoding="utf-8")
