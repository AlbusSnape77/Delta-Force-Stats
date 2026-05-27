import express from 'express';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { createProvider } from './providers/statsProvider.js';
import { playersRouter } from './routes/players.js';

const __dirname = dirname(fileURLToPath(import.meta.url));

export function createApp({ dbFile = 'data/players.db', provider } = {}) {
  const app = express();
  app.use(express.json());

  const activeProvider = provider ?? createProvider({ mode: 'manual', dbFile });

  app.get('/api/health', (req, res) => res.json({ status: 'ok' }));
  app.use('/api/players', playersRouter(activeProvider));

  app.use(express.static(join(__dirname, '..', 'public')));

  return app;
}
