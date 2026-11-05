from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from settings import DATABASE_PATH


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_connection() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


@contextmanager
def connection_scope() -> Iterator[sqlite3.Connection]:
    connection = get_connection()
    try:
        yield connection
    finally:
        connection.close()


def initialize_database() -> None:
    with connection_scope() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS slots (
                id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                start TEXT NOT NULL,
                end TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bookings (
                id TEXT PRIMARY KEY,
                slot_id TEXT NOT NULL REFERENCES slots(id),
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('confirmed', 'cancelled')),
                created_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_confirmed_booking_per_slot
                ON bookings(slot_id) WHERE status = 'confirmed';
            CREATE TABLE IF NOT EXISTS idempotency (
                key TEXT PRIMARY KEY,
                request_body TEXT NOT NULL,
                status_code INTEGER NOT NULL,
                response_body TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS booking_attempts (
                email TEXT NOT NULL,
                attempted_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS booking_attempts_by_email_time
                ON booking_attempts(email, attempted_at);
            """
        )
