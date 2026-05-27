import { Router } from 'express';
import { validatePlayer } from '../validate.js';

export function playersRouter(provider) {
  const router = Router();

  router.get('/', (req, res) => {
    res.json(provider.search(req.query.q ?? ''));
  });

  router.get('/:id', (req, res) => {
    const player = provider.getById(Number(req.params.id));
    if (!player) return res.status(404).json({ error: 'not found' });
    res.json(player);
  });

  router.post('/', (req, res) => {
    const errors = validatePlayer(req.body);
    if (errors.length) return res.status(400).json({ errors });
    try {
      res.status(201).json(provider.addPlayer(req.body));
    } catch (err) {
      if (err.code === 'DUPLICATE') {
        return res.status(409).json({ error: 'game_id 已存在' });
      }
      throw err;
    }
  });

  router.put('/:id', (req, res) => {
    const errors = validatePlayer({ game_id: 'placeholder', ...req.body });
    if (errors.length) return res.status(400).json({ errors });
    const updated = provider.updatePlayer(Number(req.params.id), req.body);
    if (!updated) return res.status(404).json({ error: 'not found' });
    res.json(updated);
  });

  router.delete('/:id', (req, res) => {
    const ok = provider.deletePlayer(Number(req.params.id));
    if (!ok) return res.status(404).json({ error: 'not found' });
    res.status(204).end();
  });

  return router;
}
