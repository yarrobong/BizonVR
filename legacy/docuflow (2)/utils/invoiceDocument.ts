import { AppSettings, BankAccount, Counterparty, CounterpartyLegalType, Invoice, SupplierCompanyProfile } from '../types';
import invoiceLogoUrl from '../media/logos/logo-for-doc.png';
import { buildInvoicePricing, normalizePricingConfig } from './contractPricing';

const RU_DATE_REGEX = /^(\d{2})\.(\d{2})\.(\d{4})$/;
const ISO_DATE_REGEX = /^(\d{4})-(\d{2})-(\d{2})/;

const toTrimmedString = (value?: string | null) => String(value ?? '').trim();
const hasValue = (value?: string | null) => toTrimmedString(value).length > 0;
let cachedInvoiceLogoDataUrl: string | null = null;

const escapeHtml = (value?: string | null) =>
  String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

const resolveLegalType = (legalType: unknown, name: unknown): CounterpartyLegalType => {
  const explicitType = String(legalType ?? '').trim().toLowerCase();
  if (explicitType === 'ip' || explicitType === 'ooo' || explicitType === 'ao' || explicitType === 'person') {
    return explicitType as CounterpartyLegalType;
  }

  const normalizedName = String(name ?? '').trim().toLowerCase();
  if (normalizedName.startsWith('ип ') || normalizedName.includes('индивидуальный предприниматель')) {
    return 'ip';
  }
  if (normalizedName.startsWith('ао ')) {
    return 'ao';
  }
  if (normalizedName.startsWith('физ ') || normalizedName.includes('физическое лицо')) {
    return 'person';
  }

  return 'ooo';
};

const stripIpPrefix = (value?: string) =>
  toTrimmedString(value).replace(/^ип\s+/i, '').replace(/^индивидуальный предприниматель\s+/i, '').trim();

const resolveCounterpartyType = (counterparty?: Counterparty | null): CounterpartyLegalType =>
  resolveLegalType(counterparty?.legalType, counterparty?.name);

const resolveSupplierType = (supplier?: Partial<SupplierCompanyProfile>): CounterpartyLegalType =>
  resolveLegalType(supplier?.legalType, supplier?.companyName);

const formatIpDisplayName = (value?: string) => {
  const stripped = stripIpPrefix(value);
  return stripped ? `Индивидуальный предприниматель ${stripped}` : 'Индивидуальный предприниматель';
};

const formatCounterpartyDisplayName = (counterparty?: Counterparty | null) => {
  const rawName = toTrimmedString(counterparty?.name);
  if (!rawName) {
    return '';
  }

  return resolveCounterpartyType(counterparty) === 'ip' ? formatIpDisplayName(rawName) : rawName;
};

const formatSupplierDisplayName = (supplier?: Partial<SupplierCompanyProfile>) => {
  const rawName = toTrimmedString(supplier?.companyName);
  if (!rawName) {
    return '';
  }

  return resolveSupplierType(supplier) === 'ip' ? formatIpDisplayName(rawName) : rawName;
};

type BankAccountSource = {
  bankAccounts?: Array<Partial<BankAccount>> | null;
  bankName?: string;
  checkingAccount?: string;
  correspondentAccount?: string;
  bik?: string;
};

const normalizeBankAccount = (value?: Partial<BankAccount> | null): BankAccount => ({
  bankName: toTrimmedString(value?.bankName),
  checkingAccount: toTrimmedString(value?.checkingAccount),
  correspondentAccount: toTrimmedString(value?.correspondentAccount),
  bik: toTrimmedString(value?.bik),
});

const hasBankAccountValue = (value: BankAccount) =>
  Boolean(value.bankName || value.checkingAccount || value.correspondentAccount || value.bik);

const resolvePrimaryBankAccount = (source?: BankAccountSource | null): BankAccount => {
  if (Array.isArray(source?.bankAccounts)) {
    const normalized = source.bankAccounts.map((item) => normalizeBankAccount(item)).filter(hasBankAccountValue);
    if (normalized.length > 0) {
      return normalized[0];
    }
  }

  return normalizeBankAccount({
    bankName: source?.bankName,
    checkingAccount: source?.checkingAccount,
    correspondentAccount: source?.correspondentAccount,
    bik: source?.bik,
  });
};

const resolveSupplierProfile = (settings?: AppSettings | null, preferredProfileId?: string): Partial<SupplierCompanyProfile> => {
  if (!settings) {
    return {};
  }

  if (Array.isArray(settings.companyProfiles) && settings.companyProfiles.length > 0) {
    const requestedProfileId = toTrimmedString(preferredProfileId) || toTrimmedString(settings.activeCompanyProfileId);
    const activeProfile = settings.companyProfiles.find((profile) => profile.id === requestedProfileId) || settings.companyProfiles[0];
    if (activeProfile) {
      return activeProfile;
    }
  }

  return {
    legalType: settings.legalType,
    companyName: settings.companyName,
    inn: settings.inn,
    kpp: settings.kpp,
    ogrn: settings.ogrn,
    ogrnip: settings.ogrnip,
    directorGenitive: settings.directorGenitive,
    legalAddress: settings.legalAddress,
    email: settings.email,
    phone: settings.phone,
    bankName: settings.bankName,
    checkingAccount: settings.checkingAccount,
    correspondentAccount: settings.correspondentAccount,
    bik: settings.bik,
    bankAccounts: settings.bankAccounts,
  };
};

const parseDate = (value?: string): Date => {
  const trimmed = toTrimmedString(value);

  const ruMatch = RU_DATE_REGEX.exec(trimmed);
  if (ruMatch) {
    const day = Number(ruMatch[1]);
    const month = Number(ruMatch[2]) - 1;
    const year = Number(ruMatch[3]);
    return new Date(year, month, day);
  }

  const isoMatch = ISO_DATE_REGEX.exec(trimmed);
  if (isoMatch) {
    const year = Number(isoMatch[1]);
    const month = Number(isoMatch[2]) - 1;
    const day = Number(isoMatch[3]);
    return new Date(year, month, day);
  }

  return new Date();
};

const formatDateRu = (value?: string) => {
  const date = parseDate(value);
  const day = String(date.getDate()).padStart(2, '0');
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const year = String(date.getFullYear());
  return `${day}.${month}.${year}`;
};

const formatAmountPlain = (amount: number) =>
  (Number.isFinite(amount) ? amount : 0).toLocaleString('ru-RU', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

const formatQuantity = (value: number) =>
  Number.isInteger(value)
    ? String(value)
    : value.toLocaleString('ru-RU', {
        minimumFractionDigits: 0,
        maximumFractionDigits: 3,
      });

const toPlural = (value: number, one: string, few: string, many: string) => {
  const abs = Math.abs(value) % 100;
  const last = abs % 10;
  if (abs > 10 && abs < 20) {
    return many;
  }
  if (last > 1 && last < 5) {
    return few;
  }
  if (last === 1) {
    return one;
  }
  return many;
};

const toWordsTriplet = (value: number, female = false): string[] => {
  const hundredsWords = [
    '',
    'сто',
    'двести',
    'триста',
    'четыреста',
    'пятьсот',
    'шестьсот',
    'семьсот',
    'восемьсот',
    'девятьсот',
  ];
  const tensWords = ['', '', 'двадцать', 'тридцать', 'сорок', 'пятьдесят', 'шестьдесят', 'семьдесят', 'восемьдесят', 'девяносто'];
  const teensWords = [
    'десять',
    'одиннадцать',
    'двенадцать',
    'тринадцать',
    'четырнадцать',
    'пятнадцать',
    'шестнадцать',
    'семнадцать',
    'восемнадцать',
    'девятнадцать',
  ];
  const unitsMale = ['', 'один', 'два', 'три', 'четыре', 'пять', 'шесть', 'семь', 'восемь', 'девять'];
  const unitsFemale = ['', 'одна', 'две', 'три', 'четыре', 'пять', 'шесть', 'семь', 'восемь', 'девять'];

  const words: string[] = [];
  const hundreds = Math.floor(value / 100);
  const tensUnits = value % 100;
  const tens = Math.floor(tensUnits / 10);
  const units = tensUnits % 10;

  if (hundreds > 0) {
    words.push(hundredsWords[hundreds]);
  }

  if (tensUnits >= 10 && tensUnits <= 19) {
    words.push(teensWords[tensUnits - 10]);
    return words;
  }

  if (tens > 1) {
    words.push(tensWords[tens]);
  }

  if (units > 0) {
    words.push((female ? unitsFemale : unitsMale)[units]);
  }

  return words;
};

const toWordsIntegerRu = (value: number): string => {
  const normalized = Math.floor(Math.abs(value));
  if (normalized === 0) {
    return 'ноль';
  }

  const scales: Array<{ one: string; few: string; many: string; female: boolean }> = [
    { one: '', few: '', many: '', female: false },
    { one: 'тысяча', few: 'тысячи', many: 'тысяч', female: true },
    { one: 'миллион', few: 'миллиона', many: 'миллионов', female: false },
    { one: 'миллиард', few: 'миллиарда', many: 'миллиардов', female: false },
    { one: 'триллион', few: 'триллиона', many: 'триллионов', female: false },
  ];

  let rest = normalized;
  let groupIndex = 0;
  const words: string[] = [];

  while (rest > 0 && groupIndex < scales.length) {
    const triplet = rest % 1000;
    if (triplet > 0) {
      const scale = scales[groupIndex];
      const tripletWords = toWordsTriplet(triplet, scale.female);
      if (scale.one) {
        tripletWords.push(toPlural(triplet, scale.one, scale.few, scale.many));
      }
      words.unshift(...tripletWords);
    }
    rest = Math.floor(rest / 1000);
    groupIndex += 1;
  }

  return words.join(' ');
};

const formatAmountWordsRu = (amount: number): string => {
  const normalized = Number.isFinite(amount) ? Math.abs(amount) : 0;
  let rubles = Math.floor(normalized);
  let kopeks = Math.round((normalized - rubles) * 100);

  if (kopeks === 100) {
    rubles += 1;
    kopeks = 0;
  }

  const rublesWords = toWordsIntegerRu(rubles);
  const rublesLabel = toPlural(rubles, 'рубль', 'рубля', 'рублей');
  const kopeksLabel = toPlural(kopeks, 'копейка', 'копейки', 'копеек');

  return `${rublesWords} ${rublesLabel} ${String(kopeks).padStart(2, '0')} ${kopeksLabel}`;
};

const toSignatureShortName = (value?: string) => {
  const normalized = stripIpPrefix(value);
  if (!normalized) {
    return '';
  }

  const parts = normalized.split(/\s+/).filter(Boolean);
  if (parts.length < 2) {
    return normalized;
  }

  const surname = parts[0];
  const initials = parts
    .slice(1)
    .map((part) => `${part.charAt(0).toUpperCase()}.`)
    .join('');

  return `${surname} ${initials}`.trim();
};

const getInvoiceSignatureLabels = (legalType: CounterpartyLegalType) => {
  switch (legalType) {
    case 'ao':
      return { left: 'Руководитель (АО)', right: 'Бухгалтер' };
    case 'ip':
      return { left: 'ИП', right: 'Подпись' };
    case 'person':
      return { left: 'Физ. лицо', right: 'Подпись' };
    case 'ooo':
    default:
      return { left: 'Руководитель (ООО)', right: 'Бухгалтер' };
  }
};

const blobToDataUrl = async (blob: Blob): Promise<string> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(reader.error || new Error('Failed to convert blob to data URL'));
    reader.readAsDataURL(blob);
  });

export const INVOICE_LOGO_URL = invoiceLogoUrl;

export const getInvoiceLogoDataUrl = async (): Promise<string> => {
  if (cachedInvoiceLogoDataUrl) {
    return cachedInvoiceLogoDataUrl;
  }

  const response = await fetch(invoiceLogoUrl);
  if (!response.ok) {
    throw new Error(`Не удалось загрузить логотип счета (${response.status})`);
  }

  const blob = await response.blob();
  const dataUrl = await blobToDataUrl(blob);
  cachedInvoiceLogoDataUrl = dataUrl;
  return dataUrl;
};

export const INVOICE_DOCUMENT_CSS = `
  .preview-root {
    --font-main: Arial, "Helvetica Neue", Helvetica, sans-serif;
  }

  .document-page.invoice-document {
    width: 210mm;
    min-height: 297mm;
    box-sizing: border-box;
    margin: 0 auto;
    padding: 10mm 12mm 12mm;
    background: #fff;
    color: #000;
    font-family: var(--font-main);
    font-size: 11pt;
    line-height: 1.3;
  }

  .invoice-main {
    width: 100%;
    font-family: var(--font-main);
  }

  .invoice-main table {
    width: 100%;
    border-collapse: collapse;
    font-family: var(--font-main);
  }

  .notice-table td {
    vertical-align: top;
  }


  .notice-text-wrap {
    width: 68%;
    padding: 12px 0 8px;
  }

  .notice-text {
    text-align: justify;
    font-size: 11pt;
    line-height: 1.3;
    padding-right: 14px;
  }

  .notice-logo-wrap {
    width: 32%;
    text-align: center;
    padding: 14px 0 8px;
  }

  .notice-logo-placeholder {
    width: 70%;
    min-height: 68px;
    margin: 0 auto;
    border: 1px dashed #8d8d8d;
    font-size: 9pt;
    color: #666;
    display: flex;
    align-items: center;
    justify-content: center;
    box-sizing: border-box;
  }

  .notice-logo-image {
    width: 50%;
    height: auto;
    display: block;
    margin: 0 auto;
    object-fit: contain;
  }

  .bank-table {
    border: 2px solid #000;
    margin-top: 4px;
  }

  .bank-table td {
    border: 1px solid #000;
    padding: 2px 4px;
    font-size: 11pt;
    vertical-align: top;
  }

  .bank-main-cell {
    min-height: 13mm;
    width: 105mm;
  }

  .bank-main-cell-inner {
    min-height: 13mm;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
  }

  .bank-label-cell {
    width: 25mm;
    min-height: 7mm;
  }

  .bank-value-cell {
    width: 60mm;
    min-height: 7mm;
  }

  .bank-caption {
    font-size: 10pt;
    margin-top: 2px;
  }

  .bank-inn-cell {
    min-height: 6mm;
    width: 50mm;
  }

  .bank-kpp-cell {
    min-height: 6mm;
    width: 55mm;
  }

  .bank-checking-label {
    min-height: 19mm;
    width: 25mm;
  }

  .bank-checking-value {
    min-height: 19mm;
    width: 60mm;
  }

  .bank-recipient-cell {
    min-height: 13mm;
  }

  .bank-recipient-inner {
    min-height: 13mm;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
  }

  .invoice-title {
    font-weight: 700;
    font-size: 25pt;
    padding-left: 5px;
    margin: 12px 0;
    font-family: var(--font-main);
  }

  .invoice-divider {
    background-color: #000;
    width: 100%;
    font-size: 1px;
    height: 2px;
  }

  .party-table {
    margin-top: 8px;
  }

  .party-label {
    width: 30mm;
    vertical-align: top;
    padding: 2px 0 2px 2px;
    font-size: 11pt;
  }

  .party-content {
    padding-left: 2px;
    font-weight: 700;
    font-size: 11pt;
    line-height: 1.33;
  }

  .party-content-meta {
    display: block;
    font-weight: 400;
    margin-top: 2px;
  }

  .party-content-meta-line {
    display: block;
  }

  .items-table {
    border: 2px solid #000;
    margin-top: 10px;
  }

  .items-table th,
  .items-table td {
    border: 1px solid #000;
    padding: 2px 4px;
    font-size: 11pt;
    vertical-align: middle;
  }

  .items-table th {
    text-align: center;
    font-weight: 700;
  }

  .items-table .num-col {
    width: 13mm;
    text-align: center;
  }

  .items-table .qty-col {
    width: 20mm;
    text-align: center;
  }

  .items-table .unit-col {
    width: 17mm;
    text-align: center;
  }

  .items-table .price-col {
    width: 27mm;
    text-align: center;
    white-space: nowrap;
  }

  .items-table .sum-col {
    width: 27mm;
    text-align: center;
    white-space: nowrap;
  }

  .totals-table {
    margin-top: 3px;
  }

  .totals-table td {
    font-size: 11pt;
    padding: 1px 2px;
    border: 0;
  }

  .totals-label {
    width: 37mm;
    font-weight: 700;
    text-align: right;
  }

  .totals-value {
    width: 27mm;
    font-weight: 700;
    text-align: center;
    white-space: nowrap;
  }

  .summary-text {
    font-size: 11pt;
    line-height: 1.35;
  }

  .terms-divider {
    margin-top: 14px;
  }

  .terms-text {
    font-size: 10pt;
    line-height: 1.35;
  }

  .signature-divider {
    margin-top: 14px;
  }

  .signature-table {
    width: 100%;
    margin-top: 10px;
  }

  .signature-table td {
    width: 50%;
    padding: 0;
    vertical-align: middle;
    border: 0;
    font-size: 11pt;
    white-space: nowrap;
  }

  .signature-cell-left {
    padding-right: 20px;
  }

  .signature-cell-right {
    padding-left: 20px;
  }

  .signature-role {
    display: inline-block;
    font-size: 11px;
  }

  .signature-line {
    display: inline-block;
    width: 45%;
    margin: 0 8px 2px;
    border-bottom: 1px solid #000;
    vertical-align: bottom;
  }

  .signature-name {
    display: inline-block;
    font-size: 11px;
    text-align: right;
    vertical-align: middle;
  }
`;

interface InvoiceDocumentParams {
  invoice: Invoice;
  counterparty?: Counterparty | null;
  settings?: AppSettings | null;
  logoSrc?: string;
}

export const buildInvoiceDocument = ({ invoice, counterparty, settings, logoSrc }: InvoiceDocumentParams) => {
  const supplierProfile = resolveSupplierProfile(settings, invoice.supplierProfileId);
  const supplierType = resolveSupplierType(supplierProfile);
  const buyerType = resolveCounterpartyType(counterparty);

  const supplierName = formatSupplierDisplayName(supplierProfile);
  const buyerName = formatCounterpartyDisplayName(counterparty);
  const supplierRawName = toTrimmedString(supplierProfile.companyName);
  const buyerRawName = toTrimmedString(counterparty?.name);
  const supplierPersonName = stripIpPrefix(supplierRawName);
  const supplierDisplayName =
    supplierType === 'ip'
      ? supplierPersonName
        ? `ИП ${supplierPersonName}`
        : ''
      : supplierName;
  const supplierRecipientName =
    supplierType === 'ip'
      ? supplierPersonName
      : supplierName;
  const buyerDisplayName =
    buyerType === 'ip'
      ? buyerRawName
        ? /^ип\s+/i.test(buyerRawName)
          ? buyerRawName
          : `ИП ${stripIpPrefix(buyerRawName)}`
        : ''
      : buyerName;

  const invoiceSupplierBankAccount = normalizeBankAccount(invoice.supplierBankAccount);
  const supplierPrimaryBankAccount = hasBankAccountValue(invoiceSupplierBankAccount)
    ? invoiceSupplierBankAccount
    : resolvePrimaryBankAccount(supplierProfile);
  const supplierBankName = toTrimmedString(supplierPrimaryBankAccount.bankName);
  const supplierBik = toTrimmedString(supplierPrimaryBankAccount.bik);
  const supplierCorrAccount = toTrimmedString(supplierPrimaryBankAccount.correspondentAccount);
  const supplierCheckingAccount = toTrimmedString(supplierPrimaryBankAccount.checkingAccount);
  const supplierInn = toTrimmedString(supplierProfile.inn);
  const supplierKpp = toTrimmedString(supplierProfile.kpp);
  const supplierPhone = toTrimmedString(supplierProfile.phone);
  const supplierAddress = toTrimmedString(supplierProfile.legalAddress);
  const supplierCityMatch = /г\.\s*[^,]+/i.exec(toTrimmedString(supplierProfile.legalAddress));
  const supplierCity = supplierCityMatch ? supplierCityMatch[0] : '';
  const buyerAddress = toTrimmedString(counterparty?.address);
  const buyerPhone = toTrimmedString((counterparty as (Counterparty & { phone?: string }) | undefined)?.phone);
  const buyerInn = toTrimmedString(counterparty?.inn);
  const buyerKpp = toTrimmedString(counterparty?.kpp);

  const invoiceNumber = toTrimmedString(invoice.number);
  const invoiceDate = formatDateRu(invoice.date);
  const paymentDueDate = hasValue(invoice.paymentDueDate) ? formatDateRu(invoice.paymentDueDate) : '';

  const normalizedItems =
    Array.isArray(invoice.items) && invoice.items.length > 0
      ? invoice.items
      : [{ id: 'fallback-item', description: 'Товар/услуга', quantity: 1, price: Number(invoice.amount || 0), unit: 'шт' }];

  const baseItemsRows = normalizedItems.map((item, index) => {
    const quantity = Number(item.quantity || 0);
    const price = Number(item.price || 0);
    const lineTotal = quantity * price;
    return {
      index: index + 1,
      description: toTrimmedString(item.description),
      quantity: Number.isFinite(quantity) ? quantity : 0,
      unit: toTrimmedString(item.unit || 'шт'),
      unitPrice: Number.isFinite(price) ? price : 0,
      lineTotal: Number.isFinite(lineTotal) ? lineTotal : 0,
    };
  });

  const calculatedAmount = baseItemsRows.reduce((sum, item) => sum + item.lineTotal, 0);
  const normalizedCommissionPercent = Number.isFinite(Number(invoice.commissionPercent))
    ? Math.max(0, Number(invoice.commissionPercent))
    : 0;
  const invoicePricingConfig = normalizePricingConfig({
    vatRate: invoice.vatRate,
    vatMode: invoice.vatMode,
    markupPercent: normalizedCommissionPercent,
    markupMode: 'per_item',
    markupCalcMode: 'simple',
  });
  const pricing = buildInvoicePricing(
    {
      ...invoice,
      amount: Number.isFinite(Number(invoice.amount)) ? Number(invoice.amount) : calculatedAmount,
      items: normalizedItems,
    },
    invoicePricingConfig,
  );
  const itemsRows = pricing.items.map((item, index) => ({
    index: index + 1,
    description: toTrimmedString(item.description),
    quantity: Number.isFinite(Number(item.quantity)) ? Number(item.quantity) : 0,
    unit: toTrimmedString(item.unit || 'шт'),
    unitPrice: Number.isFinite(Number(item.unitPrice)) ? Number(item.unitPrice) : 0,
    lineTotal: Number.isFinite(Number(item.lineTotal)) ? Number(item.lineTotal) : 0,
  }));
  const totalAmount = pricing.total;
  const vatAmount = pricing.vatAmount;
  const subtotalAmount = pricing.subtotalExcludingVat;
  const vatSummaryLabel =
    invoicePricingConfig.vatRate === 'none'
      ? 'Итого НДС (Без НДС):'
      : invoicePricingConfig.vatRate === '0'
        ? 'Итого НДС 0%:'
        : invoicePricingConfig.vatMode === 'included'
          ? `В т.ч. НДС ${invoicePricingConfig.vatRate}%:`
          : `НДС ${invoicePricingConfig.vatRate}%:`;
  const itemsCount = itemsRows.length;
  const supplierRepresentativeRaw =
    toTrimmedString(supplierProfile.directorGenitive) || supplierPersonName || supplierRawName;
  const supplierSignatureShortName = toTrimmedString(toSignatureShortName(supplierRepresentativeRaw));
  const signatureDisplayName =
    supplierSignatureShortName ||
    toTrimmedString(toSignatureShortName(supplierPersonName || supplierRawName || supplierDisplayName));
  const signatureLabels = getInvoiceSignatureLabels(supplierType);
  const supplierHeadlineParts = [
    supplierDisplayName,
    hasValue(supplierInn) ? `ИНН ${supplierInn}` : '',
    supplierType === 'ooo' && hasValue(supplierKpp) ? `КПП ${supplierKpp}` : '',
  ].filter(Boolean);
  const buyerHeadlineParts = [
    buyerDisplayName,
    hasValue(buyerInn) ? `ИНН ${buyerInn}` : '',
    buyerType === 'ooo' && hasValue(buyerKpp) ? `КПП ${buyerKpp}` : '',
  ].filter(Boolean);
  const supplierInnCellValue = hasValue(supplierInn) ? `ИНН ${supplierInn}` : '';
  const supplierKppCellValue = supplierType === 'ooo' && hasValue(supplierKpp) ? `КПП ${supplierKpp}` : '';
  const supplierEmail = toTrimmedString(supplierProfile.email);
  const buyerEmail = toTrimmedString(counterparty?.email);
  const supplierMetaLines = [
    hasValue(supplierAddress) ? `Адрес: ${supplierAddress}` : '',
    hasValue(supplierPhone) ? `Тел.: ${supplierPhone}` : '',
    hasValue(supplierEmail) ? `E-mail: ${supplierEmail}` : '',
  ].filter(Boolean);
  const buyerMetaLines = [
    hasValue(buyerAddress) ? `Адрес: ${buyerAddress}` : '',
    hasValue(buyerPhone) ? `Тел.: ${buyerPhone}` : '',
    hasValue(buyerEmail) ? `E-mail: ${buyerEmail}` : '',
  ].filter(Boolean);
  const hasSupplierPartyData = supplierHeadlineParts.length > 0 || supplierMetaLines.length > 0;
  const hasBuyerPartyData = buyerHeadlineParts.length > 0 || buyerMetaLines.length > 0;
  const invoiceTitle = invoiceNumber ? `Счет № ${invoiceNumber} от ${invoiceDate}` : `Счет от ${invoiceDate}`;
  const summaryAmountText = formatAmountPlain(totalAmount);
  const summaryAmountWords = formatAmountWordsRu(totalAmount);

  const html = `
    <div class="document-page invoice-document">
      <div class="invoice-main">
        <table class="notice-table">
          <tr>
            <td class="notice-text-wrap">
              <div class="notice-text">
                Внимание! Оплата данного счета означает согласие с условиями поставки товара. Счет действителен в течение
                5 (пяти) банковских дней, не считая дня выписки счета. Уведомление об оплате обязательно, в противном
                случае НЕ ГАРАНТИРУЕТСЯ наличие товара на складе. Товар отпускается по факту прихода денег на р/с
                Поставщика, самовывозом, при наличии доверенности и паспорта.
              </div>
            </td>
            <td class="notice-logo-wrap">
              ${
                hasValue(logoSrc)
                  ? `<img class="notice-logo-image" src="${escapeHtml(logoSrc)}" alt="Логотип" />`
                  : '<div class="notice-logo-placeholder">Логотип</div>'
              }
            </td>
          </tr>
        </table>

        <table class="bank-table" cellpadding="2" cellspacing="2">
          <tbody>
            <tr>
              <td colspan="2" rowspan="2" class="bank-main-cell">
                <div class="bank-main-cell-inner">
                  <div>
                    ${escapeHtml(supplierBankName)}
                    ${supplierCity ? `<br/>${escapeHtml(supplierCity)}` : ''}
                  </div>
                  <div class="bank-caption">Банк получателя</div>
                </div>
              </td>
              <td class="bank-label-cell">БИК</td>
              <td rowspan="2" class="bank-value-cell">
                <div>${escapeHtml(supplierBik)}</div>
                <div>${escapeHtml(supplierCorrAccount)}</div>
              </td>
            </tr>
            <tr>
              <td class="bank-label-cell">Сч. №</td>
            </tr>
            <tr>
              <td class="bank-inn-cell">${escapeHtml(supplierInnCellValue)}</td>
              <td class="bank-kpp-cell">${escapeHtml(supplierKppCellValue)}</td>
              <td rowspan="2" class="bank-checking-label">Сч. №</td>
              <td rowspan="2" class="bank-checking-value">${escapeHtml(supplierCheckingAccount)}</td>
            </tr>
            <tr>
              <td colspan="2" class="bank-recipient-cell">
                <div class="bank-recipient-inner">
                  <div>${escapeHtml(supplierRecipientName)}</div>
                  <div class="bank-caption">Получатель</div>
                </div>
              </td>
            </tr>
          </tbody>
        </table>

        <br/>
        <div class="invoice-title">${escapeHtml(invoiceTitle)}</div>
        <div class="invoice-divider">&nbsp;</div>

        <table class="party-table">
          ${
            hasSupplierPartyData
              ? `
                <tr>
                  <td class="party-label">Поставщик:</td>
                  <td>
                    <div class="party-content">
                      ${escapeHtml(supplierHeadlineParts.join(', '))}
                      ${
                        supplierMetaLines.length > 0
                          ? `<span class="party-content-meta">${supplierMetaLines
                              .map((line) => `<span class="party-content-meta-line">${escapeHtml(line)}</span>`)
                              .join('')}</span>`
                          : ''
                      }
                    </div>
                  </td>
                </tr>`
              : ''
          }
          ${
            hasBuyerPartyData
              ? `
                <tr>
                  <td class="party-label">Покупатель:</td>
                  <td>
                    <div class="party-content">
                      ${escapeHtml(buyerHeadlineParts.join(', '))}
                      ${
                        buyerMetaLines.length > 0
                          ? `<span class="party-content-meta">${buyerMetaLines
                              .map((line) => `<span class="party-content-meta-line">${escapeHtml(line)}</span>`)
                              .join('')}</span>`
                          : ''
                      }
                    </div>
                  </td>
                </tr>`
              : ''
          }
        </table>

        <table class="items-table" cellpadding="2" cellspacing="2">
          <thead>
            <tr>
              <th class="num-col">№</th>
              <th>Товары (работы, услуги)</th>
              <th class="qty-col">Кол-во</th>
              <th class="unit-col">Ед.</th>
              <th class="price-col">Цена</th>
              <th class="sum-col">Сумма</th>
            </tr>
          </thead>
          <tbody>
            ${itemsRows
              .map(
                (item) => `
                  <tr>
                    <td class="num-col">${item.index}</td>
                    <td>${escapeHtml(item.description || 'Товар')}</td>
                    <td class="qty-col">${escapeHtml(formatQuantity(item.quantity))}</td>
                    <td class="unit-col">${escapeHtml(item.unit || 'шт.')}</td>
                    <td class="price-col">${escapeHtml(formatAmountPlain(item.unitPrice))}</td>
                    <td class="sum-col">${escapeHtml(formatAmountPlain(item.lineTotal))}</td>
                  </tr>`,
              )
              .join('')}
          </tbody>
        </table>

        <table class="totals-table" cellpadding="1" cellspacing="1">
          <tr>
            <td></td>
            <td class="totals-label">Итого:</td>
            <td class="totals-value">${escapeHtml(formatAmountPlain(subtotalAmount))}</td>
          </tr>
          <tr>
            <td></td>
            <td class="totals-label">${escapeHtml(vatSummaryLabel)}</td>
            <td class="totals-value">${escapeHtml(formatAmountPlain(vatAmount))}</td>
          </tr>
          <tr>
            <td></td>
            <td class="totals-label">Всего к оплате:</td>
            <td class="totals-value">${escapeHtml(formatAmountPlain(totalAmount))}</td>
          </tr>
        </table>

        <br />
        <div class="summary-text">
          Всего наименований ${escapeHtml(String(itemsCount))} на сумму ${escapeHtml(summaryAmountText)} рублей (${escapeHtml(summaryAmountWords)}).
          ${paymentDueDate ? `<br />Оплатить не позднее ${escapeHtml(paymentDueDate)}` : ''}
        </div>
        <br /><br />
        <div class="invoice-divider terms-divider">&nbsp;</div>
        <br />
        <div class="terms-text">
          1. Счет действителен в течение 5 (пяти) банковских дней, не считая дня выписки счета. В случае нарушения срока оплаты
          сохранение цены на товар и наличие товара на складе НЕ ГАРАНТИРУЕТСЯ.<br />
          2. Оплата данного счета означает согласие с условиями, изложенными в п.1.
        </div>
        <div class="invoice-divider signature-divider">&nbsp;</div>
        <table class="signature-table">
          <tbody>
            <tr>
              <td class="signature-cell-left">
                <span class="signature-role">${escapeHtml(signatureLabels.left)}</span>
                <span class="signature-line"></span>
                <span class="signature-name">${escapeHtml(signatureDisplayName)}</span>
              </td>
              <td class="signature-cell-right">
                <span class="signature-role">${escapeHtml(signatureLabels.right)}</span>
                <span class="signature-line"></span>
                <span class="signature-name">${escapeHtml(signatureDisplayName)}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `;

  return {
    html,
    css: INVOICE_DOCUMENT_CSS,
  };
};
