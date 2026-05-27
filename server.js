import { createApp } from './src/app.js';

const PORT = process.env.PORT || 5173;
const app = createApp({ dbFile: 'data/players.db' });
app.listen(PORT, () => {
  console.log(`三角洲档案本已启动: http://localhost:${PORT}`);
});
