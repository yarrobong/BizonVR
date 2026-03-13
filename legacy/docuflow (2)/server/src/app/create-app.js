const { app } = require('../legacy/legacy-app');
const { createV1Router } = require('../api/v1/router');
const { createV2Router } = require('../api/v2/router');
const { errorHandler } = require('./middleware/error-handler');

let initialized = false;

const createApp = () => {
  if (initialized) {
    return app;
  }

  app.use('/api/v2', createV2Router());
  app.use('/api/v1', createV1Router());
  app.use(errorHandler);
  initialized = true;

  return app;
};

module.exports = { createApp };
