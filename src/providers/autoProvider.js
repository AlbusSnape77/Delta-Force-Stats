// 占位：日后接入抓包/自动化数据源时实现这些方法。
const NOT_IMPLEMENTED = () => {
  const e = new Error('AutoProvider 尚未实现：自动取数能力待数据可行性验证后接入');
  e.code = 'NOT_IMPLEMENTED';
  throw e;
};

export class AutoProvider {
  addPlayer() { return NOT_IMPLEMENTED(); }
  getById() { return NOT_IMPLEMENTED(); }
  search() { return NOT_IMPLEMENTED(); }
  updatePlayer() { return NOT_IMPLEMENTED(); }
  deletePlayer() { return NOT_IMPLEMENTED(); }
}
