import { Contract, ContractType, Invoice } from '../types';

const INVALID_FILE_CHARS_REGEX = /[<>:"/\\|?*\u0000-\u001f]/g;
const MULTI_SPACES_REGEX = /\s+/g;
const MULTI_UNDERSCORES_REGEX = /_+/g;
const EDGE_UNDERSCORES_REGEX = /^_+|_+$/g;
const RU_DATE_REGEX = /^(\d{2})\.(\d{2})\.(\d{4})$/;
const ISO_DATE_REGEX = /^(\d{4})-(\d{2})-(\d{2})/;

const CONTRACT_TYPE_CODE_MAP: Record<ContractType, string> = {
  [ContractType.SUPPLY]: 'Agr',
  [ContractType.SERVICE]: 'Agr',
  [ContractType.NDA]: 'Agr',
  [ContractType.RENTAL]: 'Agr',
};

const normalizeDatePart = (value?: string): string => {
  const trimmed = String(value ?? '').trim();
  const ruMatch = RU_DATE_REGEX.exec(trimmed);
  if (ruMatch) {
    return `${ruMatch[3]}-${ruMatch[2]}-${ruMatch[1]}`;
  }

  const isoMatch = ISO_DATE_REGEX.exec(trimmed);
  if (isoMatch) {
    return `${isoMatch[1]}-${isoMatch[2]}-${isoMatch[3]}`;
  }

  const now = new Date();
  const yyyy = String(now.getFullYear());
  const mm = String(now.getMonth() + 1).padStart(2, '0');
  const dd = String(now.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
};

const toFileNamePart = (value: string, fallback: string): string => {
  const sanitized = String(value)
    .trim()
    .replace(INVALID_FILE_CHARS_REGEX, ' ')
    .replace(MULTI_SPACES_REGEX, '_')
    .replace(MULTI_UNDERSCORES_REGEX, '_')
    .replace(EDGE_UNDERSCORES_REGEX, '');

  return sanitized.length > 0 ? sanitized : fallback;
};

const normalizeCounterpartyPart = (value?: string): string => {
  const raw = String(value ?? '')
    .trim()
    .replace(/^индивидуальный предприниматель\s+/i, '')
    .replace(/^ип\s+/i, '')
    .replace(/^ооо\s+/i, '')
    .replace(/^пао\s+/i, '')
    .replace(/^ао\s+/i, '')
    .replace(/^зао\s+/i, '')
    .replace(/^оао\s+/i, '')
    .replace(/[«»"]/g, '')
    .trim();

  return toFileNamePart(raw, 'counterparty');
};

const normalizeSubjectPart = (value?: string, fallback = 'document'): string =>
  toFileNamePart(String(value ?? ''), fallback);

const normalizeNumberPart = (value?: string): string => `No-${toFileNamePart(String(value ?? ''), 'auto')}`;

const trimFileNameLength = (value: string, maxLength = 180): string =>
  value.length > maxLength ? value.slice(0, maxLength) : value;

export const buildContractDocumentName = (contract: Pick<Contract, 'createdAt' | 'type' | 'number' | 'title' | 'counterparty'>): string => {
  const datePart = normalizeDatePart(contract.createdAt);
  const typePart = CONTRACT_TYPE_CODE_MAP[contract.type] || 'Agr';
  const numberPart = normalizeNumberPart(contract.number);
  const counterpartyPart = normalizeCounterpartyPart(contract.counterparty?.name);
  const subjectPart = normalizeSubjectPart(contract.title, 'contract');

  return trimFileNameLength([datePart, typePart, numberPart, counterpartyPart, subjectPart].join('_'));
};

export const buildInvoiceDocumentName = (
  invoice: Pick<Invoice, 'date' | 'number' | 'items'>,
  counterpartyName?: string,
): string => {
  const datePart = normalizeDatePart(invoice.date);
  const typePart = 'Inv';
  const numberPart = normalizeNumberPart(invoice.number);
  const counterpartyPart = normalizeCounterpartyPart(counterpartyName);
  const subjectFromItem = Array.isArray(invoice.items) && invoice.items.length > 0 ? invoice.items[0]?.description : '';
  const subjectPart = normalizeSubjectPart(subjectFromItem, 'invoice');

  return trimFileNameLength([datePart, typePart, numberPart, counterpartyPart, subjectPart].join('_'));
};

