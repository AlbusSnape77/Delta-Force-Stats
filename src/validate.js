const NON_NEGATIVE_INTS = ['matches', 'escape_count', 'kills', 'deaths', 'net_profit'];

export function validatePlayer(data) {
  const errors = [];
  if (!data.game_id || String(data.game_id).trim() === '') {
    errors.push('game_id 不能为空');
  }
  for (const field of NON_NEGATIVE_INTS) {
    const v = data[field];
    if (v === undefined || v === null || v === '') continue;
    if (!Number.isInteger(v) || v < 0) {
      errors.push(`${field} 必须是非负整数`);
    }
  }
  const rate = data.escape_rate;
  if (rate !== undefined && rate !== null && rate !== '') {
    if (typeof rate !== 'number' || rate < 0 || rate > 100) {
      errors.push('escape_rate 必须在 0–100 之间');
    }
  }
  return errors;
}
