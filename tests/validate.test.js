import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validatePlayer } from '../src/validate.js';

test('valid payload returns no errors', () => {
  const errors = validatePlayer({ game_id: 'Ok', kills: 3, escape_rate: 50 });
  assert.deepEqual(errors, []);
});

test('missing game_id is an error', () => {
  const errors = validatePlayer({ kills: 1 });
  assert.ok(errors.some((e) => e.includes('game_id')));
});

test('negative integer field is an error', () => {
  const errors = validatePlayer({ game_id: 'A', kills: -1 });
  assert.ok(errors.some((e) => e.includes('kills')));
});

test('escape_rate out of 0-100 is an error', () => {
  const errors = validatePlayer({ game_id: 'A', escape_rate: 150 });
  assert.ok(errors.some((e) => e.includes('escape_rate')));
});
