const express = require('express');
const { listContracts } = require('../../modules/contracts/contracts.service');
const { listInvoices } = require('../../modules/invoices/invoices.service');
const { listCounterparties } = require('../../modules/counterparties/counterparties.service');
const { listTemplates } = require('../../modules/templates/templates.service');
const { getSettings } = require('../../modules/settings/settings.service');
const { getStats } = require('../../modules/dashboard/dashboard.service');

const V1_SUNSET_DATE = 'Mon, 30 Jun 2026 00:00:00 GMT';

const createV1Router = () => {
  const router = express.Router();

  router.use((_, res, next) => {
    res.setHeader('Deprecation', 'true');
    res.setHeader('Sunset', V1_SUNSET_DATE);
    next();
  });

  router.get('/bootstrap', (_req, res) => {
    const contracts = listContracts();
    const invoices = listInvoices();
    const counterparties = listCounterparties();
    const templates = listTemplates();
    const settings = getSettings();
    const stats = getStats();

    res.status(200).json({
      contracts,
      invoices,
      counterparties,
      templates,
      templateVariables: [],
      settings,
      stats,
    });
  });

  router.get('/contracts', (_req, res) => res.status(200).json(listContracts()));
  router.get('/invoices', (_req, res) => res.status(200).json(listInvoices()));
  router.get('/counterparties', (_req, res) => res.status(200).json(listCounterparties()));
  router.get('/templates', (_req, res) => res.status(200).json(listTemplates()));
  router.get('/settings', (_req, res) => res.status(200).json(getSettings()));
  router.get('/dashboard/stats', (_req, res) => res.status(200).json(getStats()));

  return router;
};

module.exports = { createV1Router };
