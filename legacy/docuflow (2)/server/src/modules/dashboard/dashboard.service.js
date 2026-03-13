const legacy = require('../../legacy/legacy-app');

const getStats = () => legacy.buildDashboardStats(legacy.listContractsFromDb(), legacy.listInvoicesFromDb());

module.exports = { getStats };
