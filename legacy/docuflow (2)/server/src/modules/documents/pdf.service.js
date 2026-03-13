const { exportSingle } = require('./documents.service');

module.exports = {
  exportPdf: async (payload) => exportSingle({ ...payload, format: 'pdf' }),
};
