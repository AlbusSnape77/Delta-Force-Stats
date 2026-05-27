import { openDb } from '../db.js';
import { ManualProvider } from './manualProvider.js';
import { AutoProvider } from './autoProvider.js';

// 约定：所有 provider 实现 addPlayer / getById / search / updatePlayer / deletePlayer。
export function createProvider({ mode = 'manual', dbFile = 'data/players.db' } = {}) {
  if (mode === 'auto') return new AutoProvider();
  return new ManualProvider(openDb(dbFile));
}
