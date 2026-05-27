import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createApp } from '../src/app.js';

async function startTestServer() {
  const app = createApp({ dbFile: ':memory:' });
  const server = app.listen(0);
  await new Promise((r) => server.once('listening', r));
  const { port } = server.address();
  return { server, base: `http://127.0.0.1:${port}` };
}

test('GET /api/health returns ok', async () => {
  const { server, base } = await startTestServer();
  try {
    const res = await fetch(`${base}/api/health`);
    assert.equal(res.status, 200);
    const body = await res.json();
    assert.equal(body.status, 'ok');
  } finally {
    server.close();
  }
});

test('CRUD flow over REST', async () => {
  const { server, base } = await startTestServer();
  try {
    // create
    let res = await fetch(`${base}/api/players`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ game_id: 'ApiGuy', tags: ['老六'], kills: 10, deaths: 2 }),
    });
    assert.equal(res.status, 201);
    const created = await res.json();
    assert.equal(created.game_id, 'ApiGuy');

    // duplicate -> 409
    res = await fetch(`${base}/api/players`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ game_id: 'ApiGuy' }),
    });
    assert.equal(res.status, 409);

    // invalid -> 400
    res = await fetch(`${base}/api/players`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ game_id: 'Bad', kills: -5 }),
    });
    assert.equal(res.status, 400);

    // search
    res = await fetch(`${base}/api/players?q=api`);
    assert.equal(res.status, 200);
    const list = await res.json();
    assert.equal(list.length, 1);

    // update
    res = await fetch(`${base}/api/players/${created.id}`, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ kills: 99 }),
    });
    assert.equal(res.status, 200);
    assert.equal((await res.json()).kills, 99);

    // update missing -> 404
    res = await fetch(`${base}/api/players/999`, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ kills: 1 }),
    });
    assert.equal(res.status, 404);

    // delete
    res = await fetch(`${base}/api/players/${created.id}`, { method: 'DELETE' });
    assert.equal(res.status, 204);

    // delete again -> 404
    res = await fetch(`${base}/api/players/${created.id}`, { method: 'DELETE' });
    assert.equal(res.status, 404);
  } finally {
    server.close();
  }
});
