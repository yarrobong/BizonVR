const legacy = require('../../legacy/legacy-app');

const listTemplates = () => legacy.listTemplatesFromDb();

module.exports = { listTemplates };
