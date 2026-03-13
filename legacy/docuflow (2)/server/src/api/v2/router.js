const express = require('express');
const { z } = require('zod');
const { validate } = require('../../shared/validators/validate');
const { listContracts, renderContractSnapshot } = require('../../modules/contracts/contracts.service');
const { listInvoices } = require('../../modules/invoices/invoices.service');
const { listCounterparties } = require('../../modules/counterparties/counterparties.service');
const { listTemplates } = require('../../modules/templates/templates.service');
const { getSettings } = require('../../modules/settings/settings.service');
const { getStats } = require('../../modules/dashboard/dashboard.service');
const { exportSingle, exportPackage } = require('../../modules/documents/documents.service');

const renderContractSchema = z.object({
  type: z.string(),
  counterpartyId: z.string(),
  invoiceId: z.string().optional(),
  templateId: z.string().optional(),
  number: z.string().optional(),
  title: z.string().optional(),
  amount: z.number().optional(),
  paymentTerms: z.number().optional(),
  includeDelivery: z.boolean().optional(),
  deliveryDate: z.string().nullable().optional(),
  vatRate: z.enum(['none', '0', '10', '20']).optional(),
  vatMode: z.enum(['included', 'on_top']).optional(),
  markupPercent: z.number().optional(),
  markupMode: z.enum(['per_item', 'separate_line', 'proportional_total']).optional(),
  markupCalcMode: z.enum(['simple', 'gross_up']).optional(),
  supplierProfileId: z.string().optional(),
  contractData: z.record(z.unknown()).optional(),
});

const exportSingleSchema = z.object({
  format: z.enum(['pdf', 'docx']),
  html: z.string().min(1),
  css: z.string().optional(),
  fileName: z.string().optional(),
});

const exportPackageSchema = z.object({
  format: z.enum(['pdf', 'docx']),
  fileName: z.string().optional(),
  files: z.array(
    z.object({
      html: z.string().min(1),
      css: z.string().optional(),
      fileName: z.string().optional(),
    })
  ).min(1),
});

const createV2Router = () => {
  const router = express.Router();

  router.get('/contracts', (_req, res) => {
    res.status(200).json(listContracts());
  });

  router.get('/invoices', (_req, res) => {
    res.status(200).json(listInvoices());
  });

  router.get('/counterparties', (_req, res) => {
    res.status(200).json(listCounterparties());
  });

  router.get('/templates', (_req, res) => {
    res.status(200).json(listTemplates());
  });

  router.get('/settings', (_req, res) => {
    res.status(200).json(getSettings());
  });

  router.get('/dashboard/stats', (_req, res) => {
    res.status(200).json(getStats());
  });

  router.get('/bootstrap-lite', (_req, res) => {
    const settings = getSettings();
    const contracts = listContracts();
    const invoices = listInvoices();
    const counterparties = listCounterparties();
    const templates = listTemplates();

    res.status(200).json({
      settings: {
        activeCompanyProfileId: settings?.activeCompanyProfileId || '',
        defaultCurrency: settings?.defaultCurrency || 'RUB',
      },
      counters: {
        contracts: contracts.length,
        invoices: invoices.length,
        counterparties: counterparties.length,
        templates: templates.length,
      },
    });
  });

  router.post('/documents/render/contract', (req, res, next) => {
    try {
      const payload = validate(renderContractSchema, req.body, 'V2_RENDER_CONTRACT_VALIDATION_ERROR');
      const rendered = renderContractSnapshot(payload);
      res.status(200).json(rendered);
    } catch (error) {
      next(error);
    }
  });

  router.post('/documents/export', async (req, res, next) => {
    try {
      const payload = validate(exportSingleSchema, req.body, 'V2_EXPORT_VALIDATION_ERROR');
      const result = await exportSingle(payload);
      res.set({
        'Content-Type': result.contentType,
        'Content-Length': result.buffer.length,
        'Content-Disposition': result.contentDisposition,
      });
      res.send(result.buffer);
    } catch (error) {
      next(error);
    }
  });

  router.post('/documents/package', async (req, res, next) => {
    try {
      const payload = validate(exportPackageSchema, req.body, 'V2_PACKAGE_VALIDATION_ERROR');
      const result = await exportPackage(payload);
      res.set({
        'Content-Type': result.contentType,
        'Content-Length': result.buffer.length,
        'Content-Disposition': result.contentDisposition,
      });
      res.send(result.buffer);
    } catch (error) {
      next(error);
    }
  });

  return router;
};

module.exports = { createV2Router };
