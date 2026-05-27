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

test('search matches game_id case-insensitively, partial', () => {
  const p = newProvider();
  p.addPlayer({ game_id: 'GhostSniper' });
  p.addPlayer({ game_id: 'RushBoy' });
  const results = p.search('ghost');
  assert.equal(results.length, 1);
  assert.equal(results[0].game_id, 'GhostSniper');
  assert.deepEqual(results[0].tags, []);
});

test('search with empty query returns all, newest first', () => {
  const p = newProvider();
  p.addPlayer({ game_id: 'A' });
  p.addPlayer({ game_id: 'B' });
  const results = p.search('');
  assert.equal(results.length, 2);
  assert.equal(results[0].game_id, 'B');
});

test('updatePlayer changes fields and bumps updated_at', async () => {
  const p = newProvider();
  const created = p.addPlayer({ game_id: 'Edit01', kills: 1 });
  await new Promise((r) => setTimeout(r, 5));
  const updated = p.updatePlayer(created.id, { kills: 42, tags: ['车队'] });
  assert.equal(updated.kills, 42);
  assert.deepEqual(updated.tags, ['车队']);
  assert.equal(updated.game_id, 'Edit01');
  assert.notEqual(updated.updated_at, created.updated_at);
});

test('updatePlayer returns null for missing id', () => {
  const p = newProvider();
  assert.equal(p.updatePlayer(999, { kills: 1 }), null);
});

test('deletePlayer removes the row', () => {
  const p = newProvider();
  const created = p.addPlayer({ game_id: 'Del01' });
  assert.equal(p.deletePlayer(created.id), true);
  assert.equal(p.getById(created.id), null);
  assert.equal(p.deletePlayer(created.id), false);
});
