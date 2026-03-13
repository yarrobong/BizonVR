import React from 'react';
import {
  AppSettings,
  BankAccount,
  Counterparty,
  CounterpartyLegalType,
  Invoice,
  SupplierCompanyProfile,
} from '../types';
import { buildInvoicePricing, normalizePricingConfig, PricingConfig } from '../utils/contractPricing';

export const CONTRACT_DOCUMENT_CSS = `
  /* --- 1. SETTINGS (PAPER) --- */
  .preview-root {
      --font-main: "Times New Roman", "Liberation Serif", serif;
      --font-size-text: 11pt;
      --font-size-h1: 12pt;
      --line-height: 1.3;
      --page-margin-top: 0mm;
      --page-margin-right: 15mm;
      --page-margin-bottom: 0mm;
      --page-margin-left: 15mm;
      --margin-page: var(--page-margin-top) var(--page-margin-right) var(--page-margin-bottom) var(--page-margin-left);
  }

  /* A4 Container */
  .document-page {
      background: white;
      width: 210mm;
      min-height: 297mm;
      margin: 0 auto;
      padding: var(--margin-page);
      box-shadow: none;
      color: #000;
      font-family: var(--font-main);
      box-sizing: border-box;
  }

  /* --- 2. TYPOGRAPHY --- */

  .document-page p {
      font-size: var(--font-size-text);
      line-height: var(--line-height);
      text-align: justify;
      margin-bottom: 8pt;
      text-indent: 0;
      margin-top: 0;
  }

  .document-page h1.doc-title {
      text-align: center;
      font-size: 14pt;
      font-weight: bold;
      text-transform: uppercase;
      margin-bottom: 20pt;
      text-indent: 0;
      margin-top: 0;
  }

  .doc-meta {
      display: flex;
      justify-content: space-between;
      margin-bottom: 18pt;
      font-size: var(--font-size-text);
      font-family: var(--font-main);
  }

  .document-page h2 {
      font-size: var(--font-size-h1);
      text-align: center;
      margin-top: 18pt;
      margin-bottom: 10pt;
      text-indent: 0;
      font-weight: bold;
      text-transform: uppercase;
  }

  /* --- 3. NUMBERING --- */
  .contract-body {
      counter-reset: section;
  }

  section.clause {
      counter-increment: section;
  }

  section.clause h2::before {
      content: counter(section) ". ";
  }

  .text-clause {
      display: block;
      text-align: justify;
      margin-bottom: 6pt;
  }

  /* --- 4. TABLES --- */
  table.doc-table {
      width: 100%;
      border-collapse: collapse;
      margin: 10pt 0;
      font-size: 10pt;
      font-family: var(--font-main);
  }

  table.doc-table th, table.doc-table td {
      border: 1px solid #000;
      padding: 4pt;
      vertical-align: top;
      text-align: left;
  }

  table.doc-table th {
      font-weight: bold;
      text-align: left;
      vertical-align: middle;
      background-color: #f3f4f6;
  }

  /* --- 5. SIGNATURES --- */
  .signatures-section {
      margin-top: 20pt;
      page-break-inside: avoid;
  }

  .signatures-table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      font-size: 11pt;
      border: 1px dashed #8c8c8c;
  }

  .signatures-cell {
      width: 50%;
      vertical-align: top;
      border: 1px dashed #8c8c8c;
      padding: 10pt 12pt;
      box-sizing: border-box;
      text-align: left;
  }

  .signatures-cell-top {
      min-height: 220pt;
  }

  .signatures-cell-bottom {
      min-height: 110pt;
  }

  .party-header {
      font-size: 15pt;
      font-weight: bold;
      margin: 0 0 10pt;
  }

  .details-line {
      margin: 0 0 8pt;
      line-height: 1.25;
      text-align: left;
  }

  .details-subheader {
      margin: 20pt 0 10pt;
      font-size: 12pt;
      font-weight: bold;
      text-align: left;
  }

  .party-sign-header {
      margin: 0 0 10pt;
      font-size: 14pt;
      font-weight: bold;
  }

  .party-sign-name {
      margin: 0 0 14pt;
      min-height: 20pt;
      text-align: left;
  }

  .party-signature-row {
      display: flex;
      align-items: flex-end;
      gap: 8pt;
      margin-bottom: 10pt;
  }

  .sign-line {
      flex: 1;
      border-bottom: 1px solid #000;
      min-height: 1px;
  }

  .sign-inline-name {
      white-space: nowrap;
      font-weight: bold;
  }

  .party-sign-date {
      margin-top: 6pt;
      text-align: left;
  }

  .document-page h2,
  .document-page .doc-table,
  .document-page .summary {
      break-inside: avoid;
      page-break-inside: avoid;
  }

  .appendix-page-break {
      break-before: page;
      page-break-before: always;
      margin-top: 0;
      padding-top: 0;
  }

`;

interface ContractDocumentPreviewProps {
  number: string;
  counterparty?: Counterparty;
  invoice?: Invoice;
  supplierProfileId?: string;
  pricingConfig?: Partial<PricingConfig>;
  settings?: AppSettings | null;
  contentId?: string;
  paymentTermsDays?: number;
  hasPrepayment?: boolean;
  prepaymentPercent?: number;
  penaltyPercentPerDay?: number;
  includeDelivery?: boolean;
  deliveryDate?: string | null;
}

const toTrimmedString = (value?: string | null) => String(value ?? '').trim();
const hasValue = (value?: string | null) => toTrimmedString(value).length > 0;

const formatDateForDocument = (value?: string | null) => {
  const raw = toTrimmedString(value);
  if (!raw) {
    return '';
  }

  const isoMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw);
  if (isoMatch) {
    return `${isoMatch[3]}.${isoMatch[2]}.${isoMatch[1]}`;
  }

  return raw;
};

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

const resolveCounterpartyType = (counterparty?: Counterparty): CounterpartyLegalType =>
  resolveLegalType(counterparty?.legalType, counterparty?.name);

const resolveSupplierType = (supplier?: Partial<SupplierCompanyProfile>): CounterpartyLegalType =>
  resolveLegalType(supplier?.legalType, supplier?.companyName);

const stripIpPrefix = (value?: string) =>
  toTrimmedString(value).replace(/^ип\s+/i, '').replace(/^индивидуальный предприниматель\s+/i, '').trim();

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

const formatCounterpartyDisplayName = (counterparty?: Counterparty) => {
  const rawName = toTrimmedString(counterparty?.name);
  if (!rawName) {
    return 'Название организации';
  }

  const legalType = resolveCounterpartyType(counterparty);
  if (legalType === 'ip') {
    return /^ип\s+/i.test(rawName) ? rawName : `ИП ${rawName}`;
  }

  return rawName;
};

const formatSupplierDisplayName = (supplier?: Partial<SupplierCompanyProfile>) => {
  const rawName = toTrimmedString(supplier?.companyName);
  if (!rawName) {
    return 'Название организации';
  }

  const legalType = resolveSupplierType(supplier);
  if (legalType === 'ip') {
    return /^ип\s+/i.test(rawName) ? rawName : `ИП ${rawName}`;
  }

  return rawName;
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
    const normalizedAccounts = source.bankAccounts.map((account) => normalizeBankAccount(account)).filter(hasBankAccountValue);
    if (normalizedAccounts.length > 0) {
      return normalizedAccounts[0];
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

export const ContractDocumentPreview: React.FC<ContractDocumentPreviewProps> = ({
  number,
  counterparty,
  invoice,
  supplierProfileId,
  pricingConfig,
  settings,
  contentId = 'contract-content',
  paymentTermsDays = 10,
  hasPrepayment = true,
  prepaymentPercent = 100,
  penaltyPercentPerDay = 0,
  includeDelivery = true,
  deliveryDate = null,
}) => {
  const today = new Date();
  const monthName = today.toLocaleString('ru', { month: 'long' });
  const dateStr = `«${today.getDate()}» ${monthName.charAt(0).toUpperCase() + monthName.slice(1)} ${today.getFullYear()} года`;
  const signatureDateStr = `«${today.getDate()}» ${monthName.charAt(0).toUpperCase() + monthName.slice(1)} ${today.getFullYear()} г.`;
  const formatCurrency = (amount: number) =>
    amount.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' ₽';
  const normalizedPricingConfig = normalizePricingConfig({
    ...pricingConfig,
    vatRate: pricingConfig?.vatRate ?? invoice?.vatRate,
    vatMode: pricingConfig?.vatMode ?? invoice?.vatMode,
  });
  const effectivePricingConfig = { ...normalizedPricingConfig, markupMode: 'per_item' as const };
  const pricing = buildInvoicePricing(invoice, effectivePricingConfig);
  const normalizedPaymentTerms = Number.isFinite(Number(paymentTermsDays)) ? Math.max(1, Math.round(Number(paymentTermsDays))) : 10;
  const normalizedPrepaymentPercent = Number.isFinite(Number(prepaymentPercent))
    ? Math.max(0, Number(prepaymentPercent))
    : 100;
  const hasPrepaymentEnabled = Boolean(hasPrepayment) && normalizedPrepaymentPercent > 0;
  const normalizedPenaltyPercent = Number.isFinite(Number(penaltyPercentPerDay))
    ? Math.max(0, Number(penaltyPercentPerDay))
    : 0;
  const hasPenalty = normalizedPenaltyPercent > 0;
  const deliveryDateLabel = formatDateForDocument(deliveryDate);
  const isVatDisabled = normalizedPricingConfig.vatRate === 'none';
  const isZeroVat = normalizedPricingConfig.vatRate === '0';
  const vatTableLabel = isZeroVat
    ? 'НДС 0%'
    : normalizedPricingConfig.vatMode === 'included'
      ? `В т.ч. НДС ${normalizedPricingConfig.vatRate}%`
      : `НДС ${normalizedPricingConfig.vatRate}% сверху`;
  const vatClauseText = isVatDisabled
    ? '1.2 НДС не облагается (согласно применяемой системе налогообложения Поставщика).'
    : isZeroVat
      ? '1.2 К поставке применяется налоговая ставка НДС 0%.'
      : normalizedPricingConfig.vatMode === 'included'
        ? `1.2 Цена Товара включает НДС по ставке ${normalizedPricingConfig.vatRate}% (в том числе ${formatCurrency(
            pricing.vatAmount
          )}).`
        : `1.2 НДС по ставке ${normalizedPricingConfig.vatRate}% начисляется сверх стоимости Товара и составляет ${formatCurrency(
            pricing.vatAmount
          )}.`;
  const vatPaymentText = isVatDisabled
    ? 'НДС не облагается.'
    : isZeroVat
      ? 'Применяется ставка НДС 0%.'
      : normalizedPricingConfig.vatMode === 'included'
        ? `Стоимость включает НДС ${normalizedPricingConfig.vatRate}% в размере ${formatCurrency(pricing.vatAmount)}.`
        : `НДС ${normalizedPricingConfig.vatRate}% начисляется сверх стоимости и составляет ${formatCurrency(pricing.vatAmount)}.`;
  const subtotalBeforeVat = pricing.subtotalExcludingVat;
  const supplierProfile = resolveSupplierProfile(settings, invoice?.supplierProfileId || supplierProfileId);
  const supplierType = resolveSupplierType(supplierProfile);
  const supplierName = formatSupplierDisplayName(supplierProfile);
  const supplierNameForRequisites = toTrimmedString(supplierName);
  const supplierCompanyName = toTrimmedString(supplierProfile.companyName);
  const supplierPersonNameRaw = stripIpPrefix(supplierCompanyName);
  const supplierRepresentativeRaw =
    toTrimmedString(supplierProfile.directorGenitive) || supplierPersonNameRaw || supplierCompanyName;
  const supplierRepresentative = toTrimmedString(supplierRepresentativeRaw);
  const supplierRepresentativeShort = toTrimmedString(toSignatureShortName(supplierRepresentativeRaw));
  const supplierAddress = toTrimmedString(supplierProfile.legalAddress);
  const supplierPhone = toTrimmedString(supplierProfile.phone);
  const supplierEmail = toTrimmedString(supplierProfile.email);
  const supplierInn = toTrimmedString(supplierProfile.inn);
  const supplierRegistrationLabel = supplierType === 'ip' ? 'ОГРНИП' : 'ОГРН';
  const supplierRegistrationValue = toTrimmedString(
    supplierType === 'ip' ? supplierProfile.ogrnip : supplierProfile.ogrn,
  );
  const supplierKppValue = toTrimmedString(supplierProfile.kpp);
  const invoiceSupplierBankAccount = normalizeBankAccount(invoice?.supplierBankAccount);
  const supplierPrimaryBankAccount = hasBankAccountValue(invoiceSupplierBankAccount)
    ? invoiceSupplierBankAccount
    : resolvePrimaryBankAccount(supplierProfile);
  const supplierCheckingAccount = toTrimmedString(supplierPrimaryBankAccount.checkingAccount);
  const supplierCorrespondentAccount = toTrimmedString(supplierPrimaryBankAccount.correspondentAccount);
  const supplierBankName = toTrimmedString(supplierPrimaryBankAccount.bankName);
  const supplierBik = toTrimmedString(supplierPrimaryBankAccount.bik);
  const supplierSignatureTitle = supplierType === 'ooo' && supplierNameForRequisites
    ? `Директор ${supplierNameForRequisites}`
    : supplierNameForRequisites;
  const counterpartyType = resolveCounterpartyType(counterparty);
  const buyerName = formatCounterpartyDisplayName(counterparty);
  const buyerNameForRequisites = toTrimmedString(buyerName);
  const buyerInn = toTrimmedString(counterparty?.inn);
  const buyerAddress = toTrimmedString(counterparty?.address);
  const buyerEmail = toTrimmedString(counterparty?.email);
  const buyerPrimaryBankAccount = resolvePrimaryBankAccount(counterparty);
  const buyerRegistrationLabel = counterpartyType === 'ip' ? 'ОГРНИП' : 'ОГРН';
  const buyerOgrnValue = toTrimmedString(counterpartyType === 'ip' ? counterparty?.ogrnip : counterparty?.ogrn);
  const buyerKppValue = toTrimmedString(counterparty?.kpp);
  const buyerCheckingAccount = toTrimmedString(buyerPrimaryBankAccount.checkingAccount);
  const buyerCorrespondentAccount = toTrimmedString(buyerPrimaryBankAccount.correspondentAccount);
  const buyerBankName = toTrimmedString(buyerPrimaryBankAccount.bankName);
  const buyerBik = toTrimmedString(buyerPrimaryBankAccount.bik);
  const buyerContactNameRaw = toTrimmedString(counterparty?.directorName || counterparty?.contactPerson);
  const buyerDirectorName = toTrimmedString(buyerContactNameRaw);
  const buyerPhone = toTrimmedString((counterparty as (Counterparty & { phone?: string }) | undefined)?.phone);
  const buyerSignerRaw =
    counterpartyType === 'ooo'
      ? buyerContactNameRaw || toTrimmedString(counterparty?.name)
      : stripIpPrefix(counterparty?.name) || buyerContactNameRaw;
  const buyerSignerShortName = toTrimmedString(toSignatureShortName(buyerSignerRaw));
  const buyerSignatureTitle = counterpartyType === 'ooo' && buyerNameForRequisites
    ? `Директор ${buyerNameForRequisites}`
    : buyerNameForRequisites;
  const buyerIntroIpNameSource =
    stripIpPrefix(counterparty?.directorName) ||
    stripIpPrefix(counterparty?.contactPerson) ||
    stripIpPrefix(counterparty?.name) ||
    toTrimmedString(counterparty?.name);
  const buyerIntroIpName = buyerIntroIpNameSource
    ? `Индивидуальный предприниматель ${buyerIntroIpNameSource}`
    : 'Индивидуальный предприниматель';
  const supplierIntroName =
    supplierType === 'ip'
      ? `Индивидуальный предприниматель ${supplierPersonNameRaw || supplierCompanyName || ''}`.trim()
      : supplierNameForRequisites || 'Поставщик';
  const supplierRegistrationText = hasValue(supplierRegistrationValue)
    ? `${supplierRegistrationLabel} ${supplierRegistrationValue}`
    : '';

  const supplierDetailsLines = [
    { label: 'Наименование', value: supplierNameForRequisites },
    { label: 'ФИО', value: supplierRepresentative },
    { label: 'Адрес', value: supplierAddress },
    { label: 'Тел.', value: supplierPhone },
    { label: 'ИНН', value: supplierInn },
    ...(supplierType === 'ooo' ? [{ label: 'КПП', value: supplierKppValue }] : []),
    { label: supplierRegistrationLabel, value: supplierRegistrationValue },
  ].filter((item) => hasValue(item.value));

  const supplierPaymentLines = [
    { label: 'Р/с', value: supplierCheckingAccount },
    { label: 'Получатель', value: supplierNameForRequisites },
    { label: 'Банк', value: supplierBankName },
    { label: 'Контактный телефон', value: supplierPhone },
    { label: 'К/с', value: supplierCorrespondentAccount },
    { label: 'БИК', value: supplierBik },
  ].filter((item) => hasValue(item.value));

  const buyerDetailsLines = [
    { label: 'Наименование', value: buyerNameForRequisites },
    { label: 'ФИО', value: buyerDirectorName },
    { label: 'Адрес', value: buyerAddress },
    { label: 'Тел.', value: buyerPhone },
    { label: 'ИНН', value: buyerInn },
    ...(counterpartyType === 'ooo' ? [{ label: 'КПП', value: buyerKppValue }] : []),
    { label: buyerRegistrationLabel, value: buyerOgrnValue },
  ].filter((item) => hasValue(item.value));

  const buyerPaymentLines = [
    { label: 'Р/с', value: buyerCheckingAccount },
    { label: 'Получатель', value: buyerNameForRequisites },
    { label: 'Банк', value: buyerBankName },
    { label: 'К/с', value: buyerCorrespondentAccount },
    { label: 'БИК', value: buyerBik },
  ].filter((item) => hasValue(item.value));

  const emailLines = [
    hasValue(supplierEmail) ? `Электронная почта Поставщика: ${supplierEmail}` : null,
    hasValue(buyerEmail) ? `Электронная почта Покупателя: ${buyerEmail}` : null,
  ].filter((item): item is string => Boolean(item));

  return (
    <>
      <style>{CONTRACT_DOCUMENT_CSS}</style>
      <div className="preview-root">
        <div id={contentId} className="document-page">
          <h1 className="doc-title">ДОГОВОР ПОСТАВКИ № {number.replace('Д-', '')}</h1>

          <div className="doc-meta">
            <span>г. Екатеринбург</span>
            <span>{dateStr}</span>
          </div>

          <p style={{ textIndent: '1cm' }}>
            <strong>{supplierIntroName}</strong>
            {supplierRegistrationText ? <> , действуя на основании {supplierRegistrationText}</> : ''}
            , именуемый в дальнейшем «ПОСТАВЩИК», с одной стороны, и
          </p>
          <p style={{ textIndent: '1cm' }}>
            {counterpartyType === 'ooo' ? (
              <>
                <strong>{buyerNameForRequisites || 'Покупатель'}</strong>
                {buyerDirectorName ? (
                  <>
                    , в лице директора <strong>{buyerDirectorName}</strong>, действующего на основании Устава
                  </>
                ) : (
                  ''
                )}
                , именуемое в дальнейшем «ПОКУПАТЕЛЬ», с другой стороны, далее вместе именуемые СТОРОНЫ, заключили
                настоящий Договор о нижеследующем:
              </>
            ) : (
              <>
                <strong>{buyerIntroIpName}</strong>, именуемый в дальнейшем «ПОКУПАТЕЛЬ», с другой стороны, далее вместе
                именуемые СТОРОНЫ, заключили настоящий Договор о нижеследующем:
              </>
            )}
          </p>

          <div className="contract-body">
            <section className="clause">
              <h2>ПРЕДМЕТ ДОГОВОРА</h2>
              <div className="text-clause">
                1.1 Поставщик обязан поставить, а Покупатель принять и оплатить товар в порядке и сроки,
                предусмотренные настоящим Договором, согласно следующей спецификации:
              </div>

              <table className="doc-table">
                <thead>
                  <tr>
                    <th style={{ width: '5%', textAlign: 'center' }}>№</th>
                    <th style={{ width: '40%' }}>Наименование товаров, работ, услуг</th>
                    <th style={{ width: '10%', textAlign: 'center' }}>Кол-во</th>
                    <th style={{ width: '10%', textAlign: 'center' }}>Ед. изм.</th>
                    <th style={{ width: '15%' }}>Цена за единицу</th>
                    <th style={{ width: '20%' }}>Общая сумма</th>
                  </tr>
                </thead>
                <tbody>
                  {pricing.items.length > 0 ? (
                    pricing.items.map((item, i) => (
                      <tr key={item.id || String(i)}>
                        <td style={{ textAlign: 'center' }}>{i + 1}</td>
                        <td style={item.isAdjustment ? { fontStyle: 'italic' } : undefined}>{item.description}</td>
                        <td style={{ textAlign: 'center' }}>{item.quantity}</td>
                        <td style={{ textAlign: 'center' }}>{item.unit}</td>
                        <td style={{ textAlign: 'right' }}>{formatCurrency(item.unitPrice)}</td>
                        <td style={{ textAlign: 'right' }}>{formatCurrency(item.lineTotal)}</td>
                      </tr>
                    ))
                  ) : (
                    [1, 2].map((_, i) => (
                      <tr key={i}>
                        <td style={{ textAlign: 'center' }}>{i + 1}</td>
                        <td style={{ fontStyle: 'italic', color: '#999' }}>Выберите счет для заполнения...</td>
                        <td />
                        <td />
                        <td />
                        <td />
                      </tr>
                    ))
                  )}
                  {invoice && (
                    <>
                      <tr>
                        <td colSpan={5} style={{ textAlign: 'right' }}>
                          Подытог
                        </td>
                        <td style={{ textAlign: 'right' }}>{formatCurrency(subtotalBeforeVat)}</td>
                      </tr>
                      {!isVatDisabled && (
                        <tr>
                          <td colSpan={5} style={{ textAlign: 'right' }}>
                            {vatTableLabel}
                          </td>
                          <td style={{ textAlign: 'right' }}>{formatCurrency(pricing.vatAmount)}</td>
                        </tr>
                      )}
                      <tr>
                        <td colSpan={5} style={{ textAlign: 'right', fontWeight: 700 }}>
                          Итого к оплате
                        </td>
                        <td style={{ textAlign: 'right', fontWeight: 700 }}>{formatCurrency(pricing.total)}</td>
                      </tr>
                    </>
                  )}
                </tbody>
              </table>

              <div className="text-clause">{vatClauseText}</div>
            </section>

            <section className="clause">
              <h2>СТОИМОСТЬ И ПОРЯДОК ОПЛАТЫ</h2>
              <div className="text-clause">
                2.1. Общая стоимость Товара по настоящему Договору составляет{' '}
                {invoice
                  ? `${formatCurrency(pricing.total)} (Сумма прописью не указана в предпросмотре).`
                  : 'сумму, определяемую по спецификации к настоящему Договору.'}{' '}
                {vatPaymentText}
              </div>
              <div className="text-clause">
                {hasPrepaymentEnabled
                  ? `2.2. Покупатель вносит ${normalizedPrepaymentPercent.toLocaleString('ru-RU')}% предоплату путем перечисления денежных средств на расчетный счет Продавца в течение ${normalizedPaymentTerms} календарных дней с даты выставления счета в размере ${
                      invoice ? formatCurrency(pricing.total) : 'суммы, указанной в счете'
                    }.`
                  : `2.2. Оплата производится Покупателем в течение ${normalizedPaymentTerms} календарных дней с даты выставления счета путем перечисления денежных средств на расчетный счет Продавца.`}
              </div>
              {hasPrepaymentEnabled && (
                <div className="text-clause">
                  2.3. Поставщик приступает к выполнению обязательств по договору с даты внесения предоплаты.
                </div>
              )}
            </section>

            <section className="clause">
              <h2>ПОРЯДОК ПЕРЕДАЧИ ТОВАРА</h2>
              <div className="text-clause">
                {includeDelivery && deliveryDateLabel
                  ? `3.1. Товар передается Покупателю не позднее ${deliveryDateLabel}.`
                  : '3.1. Товар передается Покупателю в течение 40 календарных дней с даты зачисления средств.'}
              </div>
              <div className="text-clause">
                3.2. Поставщик осуществляет доставку Товара Покупателю собственными силами и средствами до города
                Покупателя.
              </div>
              <div className="text-clause">3.3. Разгрузку Товара осуществляет Покупатель.</div>
              <div className="text-clause">
                3.4. Факт приёма-передачи товара подтверждается подписанием товарной накладной или иного сопроводительного
                документа транспортной компании, в котором указано, что Покупатель получил товар в полном объеме и без
                претензий.
              </div>
            </section>

            <section className="clause">
              <h2>ГАРАНТИЙНЫЙ СРОК</h2>
              <div className="text-clause">
                4.1. В отношении передаваемого Товара устанавливается гарантийный срок 12 месяцев с даты передачи Товара
                от Поставщика к Покупателю.
              </div>
              <div className="text-clause">
                4.2. Поставщик несет ответственность за недостатки Товара, обнаруженные в пределах гарантийного срока,
                если не докажет, что они произошли вследствие нормального износа или нарушения условий эксплуатации
                Покупателем.
              </div>
            </section>

            <section className="clause">
              <h2>ОТВЕТСТВЕННОСТЬ СТОРОН</h2>
              <div className="text-clause">
                5.1. Стороны несут ответственность за неисполнение (ненадлежащее исполнение) своих обязательств в
                соответствии с законодательством Российской Федерации и Договором.
              </div>
              {hasPenalty && (
                <div className="text-clause">
                  5.2. За просрочку исполнения денежного обязательства виновная Сторона уплачивает пеню в размере{' '}
                  {normalizedPenaltyPercent.toLocaleString('ru-RU')}% от суммы просроченного обязательства за каждый день
                  просрочки.
                </div>
              )}
            </section>

            <section className="clause">
              <h2>ОБЯЗАТЕЛЬСТВА НЕПРЕОДОЛИМОЙ СИЛЫ</h2>
              <div className="text-clause">
                6.1. Стороны освобождаются от ответственности за неисполнение обязательств по Договору в случае, если
                неисполнение обязательств явилось следствием действия непреодолимой силы.
              </div>
              <div className="text-clause">
                6.2. Сторона, которая не может исполнить обязательства, должна в разумный срок приступить к их исполнению
                в случае, если обстоятельства непреодолимой силы прекратили своё действие и надлежащее исполнение стало
                возможным.
              </div>
            </section>

            <section className="clause">
              <h2>РАЗРЕШЕНИЕ СПОРОВ</h2>
              <div className="text-clause">
                7.1. Возникающие из Договора споры разрешаются в досудебном порядке путем направления претензионного
                письма. Срок рассмотрения претензионного письма составляет 10 рабочих дней с момента получения. В случае,
                если разрешение спора в досудебном порядке признано Сторонами невозможным, спор подлежит рассмотрению в
                судебном порядке в соответствии с законодательством Российской Федерации.
              </div>
            </section>

            <section className="clause">
              <h2>ЗАКЛЮЧИТЕЛЬНЫЕ ПОЛОЖЕНИЯ</h2>
              <div className="text-clause">
                8.1. Способом направления документов (в том числе актов, претензий и т. д.) является отправка электронного
                сообщения по электронной почте:
              </div>
              {emailLines.map((line, index) => (
                <div key={`email-line-${index}`} className="text-clause">
                  8.1.{index + 1}. {line}
                </div>
              ))}
              <div className="text-clause">
                8.2. Оригиналы документов направляются Стороной почтовым отправлением по запросу другой Стороны в течение
                7 рабочих дней.
              </div>
              <div className="text-clause">
                8.3. Договор вступает в силу с момента подписания его Сторонами и действует до полного исполнения Сторонами
                обязательств по Договору.
              </div>
              <div className="text-clause">8.4. Автоматическое продление срока действия Договора не предусмотрено.</div>
              <div className="text-clause">
                8.5. Договор составлен в двух экземплярах на русском языке, по одному для каждой из Сторон.
              </div>
            </section>

            <section className="clause">
              <h2>РЕКВИЗИТЫ И ПОДПИСИ СТОРОН</h2>

              <table className="signatures-table">
                <colgroup>
                  <col style={{ width: '50%' }} />
                  <col style={{ width: '50%' }} />
                </colgroup>
                <tbody>
                  <tr>
                    <td className="signatures-cell signatures-cell-top">
                      <div className="party-header">ПРОДАВЕЦ:</div>
                      {supplierDetailsLines.map((line) => (
                        <div key={`supplier-details-${line.label}`} className="details-line">
                          <strong>{line.label}:</strong> {line.value}
                        </div>
                      ))}
                      {supplierPaymentLines.length > 0 && (
                        <div className="details-subheader">Платежные реквизиты Продавца:</div>
                      )}
                      {supplierPaymentLines.map((line) => (
                        <div key={`supplier-payment-${line.label}`} className="details-line">
                          <strong>{line.label}:</strong> {line.value}
                        </div>
                      ))}
                    </td>
                    <td className="signatures-cell signatures-cell-top">
                      <div className="party-header">ПОКУПАТЕЛЬ:</div>
                      {buyerDetailsLines.map((line) => (
                        <div key={`buyer-details-${line.label}`} className="details-line">
                          <strong>{line.label}:</strong> {line.value}
                        </div>
                      ))}
                      {buyerPaymentLines.length > 0 && (
                        <div className="details-subheader">Платежные реквизиты Покупателя:</div>
                      )}
                      {buyerPaymentLines.map((line) => (
                        <div key={`buyer-payment-${line.label}`} className="details-line">
                          <strong>{line.label}:</strong> {line.value}
                        </div>
                      ))}
                    </td>
                  </tr>
                  <tr>
                    <td className="signatures-cell signatures-cell-bottom">
                      <div className="party-sign-header">От Продавца:</div>
                      <div className="party-sign-name">{supplierSignatureTitle}</div>
                      <div className="party-signature-row">
                        <div className="sign-line" />
                        {supplierRepresentativeShort && (
                          <span className="sign-inline-name">/ {supplierRepresentativeShort} /</span>
                        )}
                      </div>
                      <div className="party-sign-date">{signatureDateStr}</div>
                    </td>
                    <td className="signatures-cell signatures-cell-bottom">
                      <div className="party-sign-header">От Покупателя:</div>
                      <div className="party-sign-name">{buyerSignatureTitle}</div>
                      <div className="party-signature-row">
                        <div className="sign-line" />
                        {buyerSignerShortName && (
                          <span className="sign-inline-name">/ {buyerSignerShortName} /</span>
                        )}
                      </div>
                      <div className="party-sign-date">{signatureDateStr}</div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </section>
          </div>
        </div>
      </div>
    </>
  );
};
