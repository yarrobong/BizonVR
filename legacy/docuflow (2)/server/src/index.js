const { initDatabase, PORT, DB_FILE } = require('./legacy/legacy-app');
const { createApp } = require('./app/create-app');

const startServer = async () => {
  try {
    await initDatabase();
    const app = createApp();
    app.listen(PORT, () => {
      console.log(`DocuFlow Backend running on http://localhost:${PORT}`);
      console.log(`SQLite storage active: ${DB_FILE}`);
      console.log('API v2 available at /api/v2');
    });
  } catch (error) {
    console.error('Failed to start backend:', error);
    process.exit(1);
  }
};

module.exports = {
  startServer,
  createApp,
};

if (require.main === module) {
  startServer();
}
