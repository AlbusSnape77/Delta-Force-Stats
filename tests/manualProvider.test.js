import { test } from 'node:test';
import assert from 'node:assert/strict';
import { openDb } from '../src/db.js';
import { ManualProvider } from '../src/providers/manualProvider.js';

function newProvider() {
  return new ManualProvider(openDb(':memory:'));
}

test('addPlayer stores and getById returns it', () => {
  const p = newProvider();
  const created = p.addPlayer({ game_id: 'Ghost001', tags: ['老六'], kills: 10, deaths: 5 });
  assert.ok(created.id > 0);
  const found = p.getById(created.id);
  assert.equal(found.game_id, 'Ghost001');
  assert.deepEqual(found.tags, ['老六']);
  assert.equal(found.kills, 10);
  assert.ok(found.created_at);
});

test('addPlayer with duplicate game_id throws DuplicateError', () => {
  const p = newProvider();
  p.addPlayer({ game_id: 'Dup' });
  assert.throws(() => p.addPlayer({ game_id: 'Dup' }), /DUPLICATE/);
});

test('getById returns null for missing id', () => {
  const p = newProvider();
  assert.equal(p.getById(999), null);
});
