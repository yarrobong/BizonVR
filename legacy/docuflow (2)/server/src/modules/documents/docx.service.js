const { exportSingle } = require('./documents.service');

module.exports = {
  exportDocx: async (payload) => exportSingle({ ...payload, format: 'docx' }),
};
