const FIELDS = [
  'game_id', 'tags', 'note', 'rank', 'matches', 'escape_count',
  'escape_rate', 'kills', 'deaths', 'net_profit', 'favorite_operator',
];

function deserialize(row) {
  if (!row) return null;
  return { ...row, tags: JSON.parse(row.tags || '[]') };
}

export class ManualProvider {
  constructor(db) {
    this.db = db;
  }

  addPlayer(data) {
    const now = new Date().toISOString();
    const values = {
      game_id: data.game_id,
      tags: JSON.stringify(data.tags ?? []),
      note: data.note ?? null,
      rank: data.rank ?? null,
      matches: data.matches ?? null,
      escape_count: data.escape_count ?? null,
      escape_rate: data.escape_rate ?? null,
      kills: data.kills ?? null,
      deaths: data.deaths ?? null,
      net_profit: data.net_profit ?? null,
      favorite_operator: data.favorite_operator ?? null,
      created_at: now,
      updated_at: now,
    };
    try {
      const stmt = this.db.prepare(`
        INSERT INTO players
          (game_id, tags, note, rank, matches, escape_count, escape_rate,
           kills, deaths, net_profit, favorite_operator, created_at, updated_at)
        VALUES
          (@game_id, @tags, @note, @rank, @matches, @escape_count, @escape_rate,
           @kills, @deaths, @net_profit, @favorite_operator, @created_at, @updated_at)
      `);
      const info = stmt.run(values);
      return this.getById(info.lastInsertRowid);
    } catch (err) {
      if (String(err.message).includes('UNIQUE')) {
        const e = new Error('DUPLICATE game_id');
        e.code = 'DUPLICATE';
        throw e;
      }
      throw err;
    }
  }

  getById(id) {
    const row = this.db.prepare('SELECT * FROM players WHERE id = ?').get(id);
    return deserialize(row);
  }

  search(query) {
    const q = (query ?? '').trim();
    if (q === '') {
      const rows = this.db.prepare('SELECT * FROM players ORDER BY id DESC').all();
      return rows.map(deserialize);
    }
    const rows = this.db
      .prepare("SELECT * FROM players WHERE game_id LIKE ? COLLATE NOCASE ORDER BY id DESC")
      .all(`%${q}%`);
    return rows.map(deserialize);
  }

  updatePlayer(id, data) {
    const existing = this.getById(id);
    if (!existing) return null;
    const merged = {};
    for (const f of FIELDS) {
      merged[f] = f in data ? data[f] : existing[f];
    }
    const now = new Date().toISOString();
    this.db.prepare(`
      UPDATE players SET
        game_id=@game_id, tags=@tags, note=@note, rank=@rank, matches=@matches,
        escape_count=@escape_count, escape_rate=@escape_rate, kills=@kills,
        deaths=@deaths, net_profit=@net_profit, favorite_operator=@favorite_operator,
        updated_at=@updated_at
      WHERE id=@id
    `).run({
      ...merged,
      tags: JSON.stringify(merged.tags ?? []),
      updated_at: now,
      id,
    });
    return this.getById(id);
  }

  deletePlayer(id) {
    const info = this.db.prepare('DELETE FROM players WHERE id = ?').run(id);
    return info.changes > 0;
  }
}
