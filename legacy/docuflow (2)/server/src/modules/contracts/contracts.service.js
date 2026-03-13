const legacy = require('../../legacy/legacy-app');
const { HttpError } = require('../../app/errors/http-error');

const listContracts = () => legacy.listContractsFromDb();

const buildPreviewContractFromPayload = (payload, counterparty, invoice) => {
  const fallbackAmount = invoice ? Number(invoice.amount || 0) : 0;

  return {
    id: 'preview-contract-v2',
    number: legacy.isNonEmptyString(payload?.number) ? String(payload.number).trim() : 'V2-PREVIEW',
    title: legacy.isNonEmptyString(payload?.title) ? String(payload.title).trim() : `Preview: ${counterparty.name}`,
    type: payload?.type,
    counterparty,
    status: 'Черновик',
    createdAt: legacy.formatDate(),
    amount: invoice || Number.isFinite(Number(payload?.amount)) ? legacy.toNonNegativeNumber(payload.amount, fallbackAmount) : undefined,
    supplierProfileId: payload?.supplierProfileId,
    invoiceId: invoice ? invoice.id : undefined,
    paymentTerms: legacy.toPositiveInteger(payload?.paymentTerms, 10),
    includeDelivery: Boolean(payload?.includeDelivery),
    deliveryDate: legacy.isNonEmptyString(payload?.deliveryDate) ? String(payload.deliveryDate).trim() : null,
    vatRate: legacy.toVatRate(payload?.vatRate),
    vatMode: legacy.toVatMode(payload?.vatMode),
    markupPercent: legacy.toMarkupPercent(payload?.markupPercent),
    markupMode: legacy.toMarkupMode(payload?.markupMode),
    markupCalcMode: legacy.toMarkupCalcMode(payload?.markupCalcMode),
    contractData: payload?.contractData && typeof payload.contractData === 'object' ? payload.contractData : {},
  };
};

const renderContractSnapshot = (payload) => {
  const counterpartyId = String(payload?.counterpartyId || '').trim();
  if (!counterpartyId) {
    throw new HttpError(400, 'COUNTERPARTY_REQUIRED', 'counterpartyId is required');
  }

  const counterparty = legacy.getCounterpartyByIdFromDb(counterpartyId);
  if (!counterparty) {
    throw new HttpError(404, 'COUNTERPARTY_NOT_FOUND', 'Counterparty not found');
  }

  const invoiceId = String(payload?.invoiceId || '').trim();
  const invoice = invoiceId ? legacy.getInvoiceByIdFromDb(invoiceId) : null;
  if (invoiceId && !invoice) {
    throw new HttpError(404, 'INVOICE_NOT_FOUND', 'Invoice not found');
  }

  const contract = buildPreviewContractFromPayload(payload, counterparty, invoice);
  const snapshot = legacy.buildContractSnapshotPayload({
    contract,
    counterparty,
    invoice,
    templateId: payload?.templateId,
  });

  return {
    html: snapshot.htmlSnapshot,
    css: snapshot.snapshotCss,
    templateId: snapshot.templateId,
    templateName: snapshot.templateName,
    templateVersion: snapshot.templateVersion,
  };
};

module.exports = {
  listContracts,
  renderContractSnapshot,
};
