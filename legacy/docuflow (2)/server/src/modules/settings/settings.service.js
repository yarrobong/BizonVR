const legacy = require('../../legacy/legacy-app');

const getSettings = () => legacy.getSettingsFromDb();

module.exports = { getSettings };
