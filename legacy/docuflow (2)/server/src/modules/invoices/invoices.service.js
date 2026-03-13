const legacy = require('../../legacy/legacy-app');

const listInvoices = () => legacy.listInvoicesFromDb();

module.exports = { listInvoices };
