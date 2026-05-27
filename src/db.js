import Database from 'better-sqlite3';
import { mkdirSync } from 'node:fs';
import { dirname } from 'node:path';

const SCHEMA = `
CREATE TABLE IF NOT EXISTS players (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  game_id TEXT NOT NULL UNIQUE,
  tags TEXT NOT NULL DEFAULT '[]',
  note TEXT,
  rank TEXT,
  matches INTEGER,
  escape_count INTEGER,
  escape_rate REAL,
  kills INTEGER,
  deaths INTEGER,
  net_profit INTEGER,
  favorite_operator TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
`;

export function openDb(dbFile = 'data/players.db') {
  if (dbFile !== ':memory:') {
    mkdirSync(dirname(dbFile), { recursive: true });
  }
  const db = new Database(dbFile);
  db.pragma('journal_mode = WAL');
  db.exec(SCHEMA);
  return db;
}
