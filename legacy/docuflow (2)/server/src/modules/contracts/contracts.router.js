const express = require('express');

const createContractsRouter = () => {
  const router = express.Router();
  return router;
};

module.exports = { createContractsRouter };
