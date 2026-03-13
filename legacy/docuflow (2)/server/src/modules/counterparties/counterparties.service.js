const legacy = require('../../legacy/legacy-app');

const listCounterparties = () => legacy.listCounterpartiesFromDb();

module.exports = { listCounterparties };
