import React, { useEffect, useMemo, useState } from 'react';
import { Badge, Button, Card, Input, Select } from '../components/ui';
import { Icons } from '../constants';
import { AppSettings, BankAccount, Contract, ContractType, Counterparty, CounterpartyLegalType, Invoice, SupplierCompanyProfile, VatMode, VatRate, View } from '../types';
import {
  api,
  CreateCounterpartyPayload,
  CreateInvoicePayload,
  UpdateContractPayload,
  UpdateCounterpartyPayload,
  UpdateInvoicePayload,
} from '../services/api';
import { buildContractDocumentName, buildInvoiceDocumentName } from '../utils/documentNaming';
import { buildInvoiceDocument, INVOICE_LOGO_URL } from '../utils/invoiceDocument';
import { getVatModeLabel, getVatRateLabel } from '../utils/contractPricing';

export type DocumentFilter = 'all' | 'contracts' | 'invoices' | 'counterparties';

interface DocumentsByCounterpartyProps {
  onNavigate: (view: View) => void;
  onFilterChange?: (filter: DocumentFilter) => void;
  onOpenContract: (contractId: string) => void;
  onOpenInvoice: (invoiceId: string) => void;
  contracts: Contract[];
  invoices: Invoice[];
  counterparties: Counterparty[];
  settings: AppSettings | null;
  defaultFilter?: DocumentFilter;
  onCreateCounterparty: (payload: CreateCounterpartyPayload) => Promise<Counterparty>;
  onCreateInvoice: (payload: CreateInvoicePayload) => Promise<Invoice>;
  onStartContractFromInvoice: (invoiceId: string) => void;
  onUpdateCounterparty: (counterpartyId: string, payload: UpdateCounterpartyPayload) => Promise<Counterparty>;
  onUpdateInvoice: (invoiceId: string, payload: UpdateInvoicePayload) => Promise<Invoice>;
  onUpdateContract: (contractId: string, payload: UpdateContractPayload) => Promise<Contract>;
  onDeleteCounterparty: (counterpartyId: string) => Promise<void>;
  onDeleteInvoice: (invoiceId: string) => Promise<void>;
  onDeleteContract: (contractId: string) => Promise<void>;
}

interface DocumentSection {
  key: string;
  counterparty: Counterparty | null;
  contracts: Contract[];
  invoices: Invoice[];
}

interface InvoiceItemForm {
  id: string;
  description: string;
  quantity: string;
  price: string;
  unit: string;
}

const parseRuDate = (value: string) => {
  const [day, month, year] = value.split('.').map(Number);
  if (!day || !month || !year) {
    return 0;
  }

  return new Date(year, month - 1, day).getTime();
};

const getContractBadgeType = (status: Contract['status']): 'success' | 'warning' | 'neutral' => {
  if (status === 'Подписан') {
    return 'success';
  }

  if (status === 'На согласовании') {
    return 'warning';
  }

  return 'neutral';
};

const getInvoiceBadgeType = (status: Invoice['status']): 'success' | 'warning' =>
  status === 'Оплачен' ? 'success' : 'warning';

const formatMoney = (amount: number, currency: string) =>
  amount.toLocaleString('ru-RU', { style: 'currency', currency, maximumFractionDigits: 0 });

const formatCounterpartyName = (counterparty: Counterparty) => {
  const type =
    counterparty.legalType === 'ip' ||
    counterparty.legalType === 'ooo' ||
    counterparty.legalType === 'ao' ||
    counterparty.legalType === 'person'
      ? counterparty.legalType
      : 'ooo';
  const rawName = counterparty.name || '';
  if (type === 'ip') {
    return /^ип\s+/i.test(rawName) ? rawName : `ИП ${rawName}`;
  }
  return rawName;
};

const isCounterpartyCompanyType = (legalType: CounterpartyLegalType) => legalType === 'ooo' || legalType === 'ao';

const getCounterpartyTypeLabel = (legalType?: CounterpartyLegalType) => {
  switch (legalType) {
    case 'ip':
      return 'ИП';
    case 'ao':
      return 'АО';
    case 'person':
      return 'Физ. лицо';
    case 'ooo':
    default:
      return 'ООО';
  }
};

const getCounterpartyNameFieldLabel = (legalType: CounterpartyLegalType) => {
  if (legalType === 'ip') return 'ФИО предпринимателя';
  if (legalType === 'person') return 'ФИО';
  return 'Наименование';
};

const getCounterpartyNamePlaceholder = (legalType: CounterpartyLegalType) => {
  if (legalType === 'ooo') return 'ООО "Ромашка"';
  if (legalType === 'ao') return 'АО "Ромашка"';
  return 'Петров Петр Петрович';
};

const formatDateRu = (date = new Date()) =>
  date.toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });

const resolveAbsoluteLogoUrl = () => {
  if (typeof window === 'undefined') {
    return INVOICE_LOGO_URL;
  }

  if (/^https?:\/\//i.test(INVOICE_LOGO_URL) || INVOICE_LOGO_URL.startsWith('data:')) {
    return INVOICE_LOGO_URL;
  }

  return new URL(INVOICE_LOGO_URL, window.location.origin).toString();
};

const resolveSupplierProfiles = (settings: AppSettings | null): SupplierCompanyProfile[] => {
  if (!settings) {
    return [];
  }

  if (Array.isArray(settings.companyProfiles) && settings.companyProfiles.length > 0) {
    return settings.companyProfiles;
  }

  return [
    {
      id: settings.activeCompanyProfileId || 'company-legacy',
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
      bik: settings.bik,
      correspondentAccount: settings.correspondentAccount,
      checkingAccount: settings.checkingAccount,
      bankAccounts: settings.bankAccounts,
    },
  ];
};

const createEmptyBankAccount = (): BankAccount => ({
  bankName: '',
  checkingAccount: '',
  correspondentAccount: '',
  bik: '',
});

const normalizeBankAccount = (value?: Partial<BankAccount> | null): BankAccount => ({
  bankName: String(value?.bankName ?? '').trim(),
  checkingAccount: String(value?.checkingAccount ?? '').trim(),
  correspondentAccount: String(value?.correspondentAccount ?? '').trim(),
  bik: String(value?.bik ?? '').trim(),
});

const hasBankAccountValues = (value: BankAccount) =>
  Boolean(value.bankName || value.checkingAccount || value.correspondentAccount || value.bik);

const normalizeBankAccounts = (
  bankAccounts?: Array<Partial<BankAccount>> | null,
  fallback?: Partial<BankAccount> | null,
): BankAccount[] => {
  if (Array.isArray(bankAccounts)) {
    const normalized = bankAccounts.map((account) => normalizeBankAccount(account)).filter(hasBankAccountValues);
    if (normalized.length > 0) {
      return normalized;
    }
  }

  const normalizedFallback = normalizeBankAccount(fallback);
  if (hasBankAccountValues(normalizedFallback)) {
    return [normalizedFallback];
  }

  return [];
};

const getPrimaryBankAccount = (bankAccounts: BankAccount[]): BankAccount => bankAccounts[0] || createEmptyBankAccount();

const GOODS_SALE_EXTENDED_TEMPLATE_NAME = 'Договор купли-продажи товара (расширенный, конфиденциальность)';
const GOODS_SALE_EXTENDED_TEMPLATE_IDS = new Set(['t5', 'tpl-goods-sale-extended-conf-2026']);
const SUPPLY_LEGAL_ENTITIES_TEMPLATE_NAME = 'Договор поставки (юрлица и ИП, расширенный)';
const SUPPLY_LEGAL_ENTITIES_TEMPLATE_IDS = new Set(['tpl-supply-legal-entities-2026']);
const isLegalEntityOrIpType = (legalType?: CounterpartyLegalType | string) =>
  legalType === 'ooo' || legalType === 'ao' || legalType === 'ip';
const stripIpPrefix = (value?: string) => String(value || '').trim().replace(/^ип\s+/iu, '');

const toTrimmedString = (value: unknown) => String(value ?? '').trim();

const toContractDataObject = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' ? (value as Record<string, unknown>) : {};

const DEFAULT_PERSON_COUNTERPARTY_VALUES = {
  name: 'Слижук Дмитрий Васильевич',
  inn: '',
  address: 'Ростовская область город Миллерово улица 19 съезд КПСС д99',
  contactPerson: 'Слижук Дмитрий Васильевич',
  email: '',
  phone: '89613289518',
  passportSeries: '6017',
  passportNumber: '004863',
  passportIssuedBy: 'МЕЖРАЙОННЫМ ОТДЕЛОМ УФМС РОССИИ ПО РОСТОВСКОЙ ОБЛАСТИ В ГОРОДЕ МИЛЛЕРОВО',
  passportIssuedDate: '21.09.2016',
  passportDepartmentCode: '',
  registrationAddress: 'Ростовская область город Миллерово улица 19 съезд КПСС д99',
  residenceAddress: 'Ростовская область город Миллерово улица 19 съезд КПСС д99',
};

const createEmptyCounterpartyForm = () => ({
  legalType: 'ooo' as CounterpartyLegalType,
  name: '',
  inn: '',
  address: '',
  contactPerson: '',
  email: '',
  phone: '',
  directorName: '',
  ogrn: '',
  kpp: '',
  ogrnip: '',
  passportSeries: '',
  passportNumber: '',
  passportIssuedBy: '',
  passportIssuedDate: '',
  passportDepartmentCode: '',
  registrationAddress: '',
  residenceAddress: '',
  bankAccounts: [createEmptyBankAccount()],
});

const createCounterpartyFormFromEntity = (counterparty: Counterparty) => {
  const bankAccounts = normalizeBankAccounts(counterparty.bankAccounts, counterparty);
  return {
    legalType:
      counterparty.legalType === 'ip' ||
      counterparty.legalType === 'ooo' ||
      counterparty.legalType === 'ao' ||
      counterparty.legalType === 'person'
        ? counterparty.legalType
        : ('ooo' as CounterpartyLegalType),
    name: counterparty.name || '',
    inn: counterparty.inn || '',
    address: counterparty.address || '',
    contactPerson: counterparty.contactPerson || '',
    email: counterparty.email || '',
    phone: counterparty.phone || '',
    directorName: counterparty.directorName || '',
    ogrn: counterparty.ogrn || '',
    kpp: counterparty.kpp || '',
    ogrnip: counterparty.ogrnip || '',
    passportSeries: counterparty.passportSeries || '',
    passportNumber: counterparty.passportNumber || '',
    passportIssuedBy: counterparty.passportIssuedBy || '',
    passportIssuedDate: counterparty.passportIssuedDate || '',
    passportDepartmentCode: counterparty.passportDepartmentCode || '',
    registrationAddress: counterparty.registrationAddress || '',
    residenceAddress: counterparty.residenceAddress || '',
    bankAccounts: bankAccounts.length > 0 ? bankAccounts : [createEmptyBankAccount()],
  };
};

const createEmptyInvoiceForm = () => ({
  counterpartyId: '',
  number: '',
  date: formatDateRu(),
  paymentDueDate: '',
  status: 'Не оплачен' as Invoice['status'],
  currency: 'RUB',
  commissionPercent: '6',
  vatRate: 'none' as VatRate,
  vatMode: 'included' as VatMode,
  supplierProfileId: '',
  items: [createEmptyInvoiceItemForm()],
});

const createEmptyInvoiceItemForm = (): InvoiceItemForm => ({
  id: `invoice-item-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
  description: '',
  quantity: '1',
  price: '0',
  unit: 'усл.',
});

const createInvoiceItemFormFromEntity = (item: Partial<Invoice['items'][number]>): InvoiceItemForm => ({
  id: String(item?.id || `invoice-item-${Date.now()}-${Math.floor(Math.random() * 1000)}`),
  description: String(item?.description || ''),
  quantity: item?.quantity == null ? '1' : String(item.quantity),
  price: item?.price == null ? '0' : String(item.price),
  unit: String(item?.unit || 'усл.'),
});

const createInvoiceFormFromEntity = (invoice: Invoice) => {
  const sourceItems =
    Array.isArray(invoice.items) && invoice.items.length > 0
      ? invoice.items
      : [{ description: '', quantity: 1, price: invoice.amount || 0, unit: 'усл.' }];

  return {
    counterpartyId: invoice.counterpartyId || '',
    number: invoice.number || '',
    date: invoice.date || formatDateRu(),
    paymentDueDate: invoice.paymentDueDate || '',
    status: invoice.status,
    currency: invoice.currency || 'RUB',
    commissionPercent: invoice.commissionPercent == null ? '6' : String(invoice.commissionPercent),
    vatRate: invoice.vatRate || 'none',
    vatMode: invoice.vatMode || 'included',
    supplierProfileId: invoice.supplierProfileId || '',
    items: sourceItems.map((item) => createInvoiceItemFormFromEntity(item)),
  };
};

const createEmptyContractForm = () => ({
  number: '',
  title: '',
  type: ContractType.SERVICE,
  counterpartyId: '',
  invoiceId: '',
  status: 'Черновик' as Contract['status'],
  amount: '',
  paymentTerms: '10',
  paymentMode: 'full_prepayment' as 'full_prepayment' | 'partial_prepayment' | 'custom',
  customPaymentTerms: '',
  includeDelivery: true,
  deliveryDate: '',
  signingCity: '',
  deliveryCity: '',
  deliveryTermDays: '35',
  deliveryTermBasis: 'с даты поступления полной оплаты',
  deliveryCostPayer: 'seller' as 'seller' | 'buyer' | '',
  deliveryMethod: 'ТК/курьер по согласованию Сторон',
  purchasePurpose: 'business' as 'personal' | 'business',
  supplierTaxBasis: 'УСН, без НДС',
  confidentialityPenaltyAmount: '30000',
  buyerFullName: '',
  buyerPhone: '',
  buyerEmail: '',
  buyerPassportSeries: '',
  buyerPassportNumber: '',
  buyerPassportIssuedBy: '',
  buyerPassportIssuedDate: '',
  buyerPassportDepartmentCode: '',
  buyerRegistrationAddress: '',
  buyerResidenceAddress: '',
  supplierSignerPosition: '',
  supplierSignerName: '',
  supplierSignerBasis: '',
  buyerSignerPosition: '',
  buyerSignerName: '',
  buyerSignerBasis: '',
});

const createContractFormFromEntity = (contract: Contract) => {
  const contractData = toContractDataObject(contract.contractData);
  const privateBuyerRf = toContractDataObject(contractData.privateBuyerRf);
  const deliveryCostPayer = toTrimmedString(contractData.deliveryCostPayer);
  const purchasePurpose = toTrimmedString(contractData.purchasePurpose);
  const rawConfAmount = contractData.confidentialityPenaltyAmount;
  const rawHasPrepayment = contractData.hasPrepayment;
  const hasPrepayment = rawHasPrepayment == null ? true : Boolean(rawHasPrepayment);
  const rawPrepaymentPercent = Number(contractData.prepaymentPercent);
  const prepaymentPercent =
    Number.isFinite(rawPrepaymentPercent) && rawPrepaymentPercent >= 0 ? Math.min(100, rawPrepaymentPercent) : 100;
  const customPaymentTerms = toTrimmedString(contractData.customPaymentTerms || contractData.custom_payment_terms);
  const paymentMode =
    !hasPrepayment || prepaymentPercent <= 0
      ? 'custom'
      : prepaymentPercent >= 100
        ? 'full_prepayment'
        : 'partial_prepayment';
  const buyerSignerPosition = toTrimmedString(contractData.buyerSignerPosition || contractData.buyer_signer_position);
  const buyerSignerName = toTrimmedString(contractData.buyerSignerName || contractData.buyer_signer_name);
  const buyerSignerBasis = toTrimmedString(contractData.buyerSignerBasis || contractData.buyer_signer_basis);
  const supplierSignerPosition = toTrimmedString(contractData.supplierSignerPosition || contractData.supplier_signer_position);
  const supplierSignerName = toTrimmedString(contractData.supplierSignerName || contractData.supplier_signer_name);
  const supplierSignerBasis = toTrimmedString(contractData.supplierSignerBasis || contractData.supplier_signer_basis);

  return {
    number: contract.number || '',
    title: contract.title || '',
    type: contract.type,
    counterpartyId: contract.counterparty?.id || '',
    invoiceId: contract.invoiceId || '',
    status: contract.status,
    amount: contract.amount == null ? '' : String(contract.amount),
    paymentTerms: contract.paymentTerms == null ? '10' : String(contract.paymentTerms),
    paymentMode,
    customPaymentTerms,
    prepaymentPercent: String(prepaymentPercent),
    includeDelivery: Boolean(contract.includeDelivery),
    deliveryDate: contract.deliveryDate || '',
    signingCity: toTrimmedString(contractData.signingCity),
    deliveryCity: toTrimmedString(contractData.deliveryCity),
    deliveryTermDays:
      contractData.deliveryTermDays == null || toTrimmedString(contractData.deliveryTermDays) === ''
        ? '35'
        : String(contractData.deliveryTermDays),
    deliveryTermBasis: toTrimmedString(contractData.deliveryTermBasis) || 'с даты поступления полной оплаты',
    deliveryCostPayer: deliveryCostPayer === 'buyer' ? 'buyer' : deliveryCostPayer === 'seller' ? 'seller' : '',
    deliveryMethod: toTrimmedString(contractData.deliveryMethod) || 'ТК/курьер по согласованию Сторон',
    purchasePurpose: purchasePurpose === 'business' ? 'business' : 'personal',
    supplierTaxBasis: toTrimmedString(contractData.supplierTaxBasis) || 'УСН, без НДС',
    confidentialityPenaltyAmount:
      rawConfAmount == null || toTrimmedString(rawConfAmount) === '' ? '' : String(rawConfAmount),
    buyerFullName: toTrimmedString(privateBuyerRf.fullName) || toTrimmedString(contract.counterparty?.name),
    buyerPhone: toTrimmedString(privateBuyerRf.phone) || toTrimmedString(contract.counterparty?.phone),
    buyerEmail: toTrimmedString(privateBuyerRf.email) || toTrimmedString(contract.counterparty?.email),
    buyerPassportSeries: toTrimmedString(privateBuyerRf.passportSeries),
    buyerPassportNumber: toTrimmedString(privateBuyerRf.passportNumber),
    buyerPassportIssuedBy: toTrimmedString(privateBuyerRf.passportIssuedBy),
    buyerPassportIssuedDate: toTrimmedString(privateBuyerRf.passportIssuedDate),
    buyerPassportDepartmentCode: toTrimmedString(privateBuyerRf.passportDepartmentCode),
    buyerRegistrationAddress: toTrimmedString(privateBuyerRf.registrationAddress) || toTrimmedString(contract.counterparty?.registrationAddress),
    buyerResidenceAddress: toTrimmedString(privateBuyerRf.residenceAddress) || toTrimmedString(contract.counterparty?.residenceAddress),
    supplierSignerPosition,
    supplierSignerName,
    supplierSignerBasis,
    buyerSignerPosition,
    buyerSignerName,
    buyerSignerBasis,
  };
};

const createBuyerContractFieldsFromCounterparty = (counterparty?: Counterparty | null) => ({
  buyerFullName: toTrimmedString(counterparty?.name),
  buyerPhone: toTrimmedString(counterparty?.phone),
  buyerEmail: toTrimmedString(counterparty?.email),
  buyerPassportSeries: toTrimmedString(counterparty?.passportSeries),
  buyerPassportNumber: toTrimmedString(counterparty?.passportNumber),
  buyerPassportIssuedBy: toTrimmedString(counterparty?.passportIssuedBy),
  buyerPassportIssuedDate: toTrimmedString(counterparty?.passportIssuedDate),
  buyerPassportDepartmentCode: toTrimmedString(counterparty?.passportDepartmentCode),
  buyerRegistrationAddress: toTrimmedString(counterparty?.registrationAddress),
  buyerResidenceAddress: toTrimmedString(counterparty?.residenceAddress),
});

export const DocumentsByCounterparty: React.FC<DocumentsByCounterpartyProps> = ({
  onNavigate,
  onFilterChange,
  onOpenContract,
  onOpenInvoice,
  contracts,
  invoices,
  counterparties,
  settings,
  defaultFilter = 'all',
  onCreateCounterparty,
  onCreateInvoice,
  onStartContractFromInvoice,
  onUpdateCounterparty,
  onUpdateInvoice,
  onUpdateContract,
  onDeleteCounterparty,
  onDeleteInvoice,
  onDeleteContract,
}) => {
  const [activeFilter, setActiveFilter] = useState<DocumentFilter>(defaultFilter);
  const [isCounterpartyFormOpen, setIsCounterpartyFormOpen] = useState(false);
  const [isInvoiceFormOpen, setIsInvoiceFormOpen] = useState(false);
  const [isContractFormOpen, setIsContractFormOpen] = useState(false);
  const [editingCounterpartyId, setEditingCounterpartyId] = useState<string | null>(null);
  const [editingInvoiceId, setEditingInvoiceId] = useState<string | null>(null);
  const [editingContractId, setEditingContractId] = useState<string | null>(null);
  const [isSavingCounterparty, setIsSavingCounterparty] = useState(false);
  const [isSavingInvoice, setIsSavingInvoice] = useState(false);
  const [isSavingContract, setIsSavingContract] = useState(false);
  const [deletingCounterpartyId, setDeletingCounterpartyId] = useState<string | null>(null);
  const [deletingInvoiceId, setDeletingInvoiceId] = useState<string | null>(null);
  const [deletingContractId, setDeletingContractId] = useState<string | null>(null);
  const [counterpartyError, setCounterpartyError] = useState<string | null>(null);
  const [invoiceError, setInvoiceError] = useState<string | null>(null);
  const [contractError, setContractError] = useState<string | null>(null);
  const [counterpartyForm, setCounterpartyForm] = useState(createEmptyCounterpartyForm);
  const [invoiceForm, setInvoiceForm] = useState(createEmptyInvoiceForm);
  const [contractForm, setContractForm] = useState(createEmptyContractForm);
  const [downloadingInvoiceFile, setDownloadingInvoiceFile] = useState<{ invoiceId: string; format: 'pdf' | 'docx' } | null>(
    null,
  );

  useEffect(() => {
    setActiveFilter(defaultFilter);
  }, [defaultFilter]);

  const supplierProfiles = useMemo(() => resolveSupplierProfiles(settings), [settings]);

  useEffect(() => {
    if (!isInvoiceFormOpen || supplierProfiles.length === 0) {
      return;
    }

    const hasValidProfile = supplierProfiles.some((profile) => profile.id === invoiceForm.supplierProfileId);
    if (!hasValidProfile) {
      setInvoiceForm((prev) => ({
        ...prev,
        supplierProfileId: settings?.activeCompanyProfileId || supplierProfiles[0].id,
      }));
    }
  }, [invoiceForm.supplierProfileId, isInvoiceFormOpen, settings?.activeCompanyProfileId, supplierProfiles]);

  const applyActiveFilter = (nextFilter: DocumentFilter) => {
    setActiveFilter(nextFilter);
    onFilterChange?.(nextFilter);
  };

  const invoicesById = useMemo(() => new Map(invoices.map((invoice) => [invoice.id, invoice])), [invoices]);
  const counterpartiesById = useMemo(() => new Map(counterparties.map((counterparty) => [counterparty.id, counterparty])), [counterparties]);
  const contractsById = useMemo(() => new Map(contracts.map((contract) => [contract.id, contract])), [contracts]);
  const editingContractEntity = useMemo(
    () => (editingContractId ? contractsById.get(editingContractId) || null : null),
    [contractsById, editingContractId],
  );
  const editingContractData = useMemo(
    () => toContractDataObject(editingContractEntity?.contractData),
    [editingContractEntity?.contractData],
  );
  const isEditingGoodsSaleExtendedContract = useMemo(() => {
    if (!editingContractEntity) {
      return false;
    }

    const templateName = toTrimmedString(editingContractEntity.templateName);
    const templateId = toTrimmedString(editingContractEntity.templateId);
    const contractScenario = toTrimmedString(editingContractData.contractScenario);

    return (
      templateName === GOODS_SALE_EXTENDED_TEMPLATE_NAME ||
      GOODS_SALE_EXTENDED_TEMPLATE_IDS.has(templateId) ||
      contractScenario === 'private_person_goods_sale'
    );
  }, [editingContractData.contractScenario, editingContractEntity]);
  const editingContractLinkedInvoice = useMemo(
    () => (editingContractEntity?.invoiceId ? invoicesById.get(editingContractEntity.invoiceId) || null : null),
    [editingContractEntity?.invoiceId, invoicesById],
  );
  const editingContractVatRate = (editingContractLinkedInvoice?.vatRate || editingContractEntity?.vatRate || 'none') as VatRate;
  const editingContractSupplierProfile = useMemo(() => {
    if (supplierProfiles.length === 0) {
      return null;
    }

    const supplierProfileId = editingContractEntity?.supplierProfileId;
    if (supplierProfileId) {
      const byId = supplierProfiles.find((profile) => profile.id === supplierProfileId);
      if (byId) {
        return byId;
      }
    }

    if (settings?.activeCompanyProfileId) {
      const active = supplierProfiles.find((profile) => profile.id === settings.activeCompanyProfileId);
      if (active) {
        return active;
      }
    }

    return supplierProfiles[0] || null;
  }, [editingContractEntity?.supplierProfileId, settings?.activeCompanyProfileId, supplierProfiles]);
  const isEditingGoodsSaleSellerPerson = editingContractSupplierProfile?.legalType === 'person';
  const isEditingSupplyLegalEntitiesContract = useMemo(() => {
    if (!editingContractEntity) {
      return false;
    }
    const templateName = toTrimmedString(editingContractEntity.templateName);
    const templateId = toTrimmedString(editingContractEntity.templateId);
    const contractScenario = toTrimmedString(editingContractData.contractScenario);
    return (
      templateName === SUPPLY_LEGAL_ENTITIES_TEMPLATE_NAME ||
      SUPPLY_LEGAL_ENTITIES_TEMPLATE_IDS.has(templateId) ||
      contractScenario === 'supply_legal_entities'
    );
  }, [editingContractData.contractScenario, editingContractEntity]);
  const editingContractCounterparty = useMemo(() => {
    if (contractForm.counterpartyId) {
      return counterpartiesById.get(contractForm.counterpartyId) || null;
    }
    return editingContractEntity?.counterparty || null;
  }, [contractForm.counterpartyId, counterpartiesById, editingContractEntity?.counterparty]);
  const defaultSupplierSigner = useMemo(() => {
    if (editingContractSupplierProfile?.legalType === 'ip') {
      return {
        position: 'индивидуальный предприниматель',
        name: stripIpPrefix(editingContractSupplierProfile.companyName),
        basis: 'свидетельства о государственной регистрации в качестве ИП',
      };
    }
    return {
      position: 'директор',
      name: toTrimmedString(editingContractSupplierProfile?.directorName || editingContractSupplierProfile?.directorGenitive),
      basis: 'Устава',
    };
  }, [editingContractSupplierProfile]);
  const defaultBuyerSigner = useMemo(() => {
    const buyerType = editingContractCounterparty?.legalType;
    return {
      position: buyerType === 'ip' ? 'индивидуальный предприниматель' : 'директор',
      name: toTrimmedString(
        editingContractCounterparty?.directorName || editingContractCounterparty?.contactPerson || editingContractCounterparty?.name
      ),
      basis: buyerType === 'ip' ? 'свидетельства о государственной регистрации в качестве ИП' : 'Устава',
    };
  }, [editingContractCounterparty]);

  useEffect(() => {
    if (!isContractFormOpen || !isEditingSupplyLegalEntitiesContract) {
      return;
    }
    setContractForm((prev) => ({
      ...prev,
      deliveryCostPayer: 'buyer',
      supplierSignerPosition: prev.supplierSignerPosition || defaultSupplierSigner.position,
      supplierSignerName: prev.supplierSignerName || defaultSupplierSigner.name,
      supplierSignerBasis: prev.supplierSignerBasis || defaultSupplierSigner.basis,
      buyerSignerPosition: prev.buyerSignerPosition || defaultBuyerSigner.position,
      buyerSignerName: prev.buyerSignerName || defaultBuyerSigner.name,
      buyerSignerBasis: prev.buyerSignerBasis || defaultBuyerSigner.basis,
    }));
  }, [
    defaultBuyerSigner.basis,
    defaultBuyerSigner.name,
    defaultBuyerSigner.position,
    defaultSupplierSigner.basis,
    defaultSupplierSigner.name,
    defaultSupplierSigner.position,
    isContractFormOpen,
    isEditingSupplyLegalEntitiesContract,
  ]);

  const contractsByInvoiceId = useMemo(() => {
    const map = new Map<string, Contract[]>();

    contracts.forEach((contract) => {
      if (!contract.invoiceId) {
        return;
      }

      const linkedContracts = map.get(contract.invoiceId) || [];
      linkedContracts.push(contract);
      map.set(contract.invoiceId, linkedContracts);
    });

    return map;
  }, [contracts]);

  const sections = useMemo<DocumentSection[]>(() => {
    const byCounterparty = new Map<string, DocumentSection>();

    const ensureSection = (counterparty: Counterparty): DocumentSection => {
      const existing = byCounterparty.get(counterparty.id);
      if (existing) {
        return existing;
      }

      const created: DocumentSection = {
        key: counterparty.id,
        counterparty,
        contracts: [],
        invoices: [],
      };
      byCounterparty.set(counterparty.id, created);
      return created;
    };

    counterparties.forEach((counterparty) => ensureSection(counterparty));

    contracts.forEach((contract) => {
      ensureSection(contract.counterparty).contracts.push(contract);
    });

    const attachedInvoiceIds = new Set<string>();

    contracts.forEach((contract) => {
      if (!contract.invoiceId) {
        return;
      }

      const invoice = invoicesById.get(contract.invoiceId);
      if (!invoice) {
        return;
      }

      const section = ensureSection(contract.counterparty);
      if (!section.invoices.some((item) => item.id === invoice.id)) {
        section.invoices.push(invoice);
      }
      attachedInvoiceIds.add(invoice.id);
    });

    invoices.forEach((invoice) => {
      if (attachedInvoiceIds.has(invoice.id)) {
        return;
      }

      if (!invoice.counterpartyId) {
        return;
      }

      const linkedCounterparty = counterparties.find((counterparty) => counterparty.id === invoice.counterpartyId);
      if (!linkedCounterparty) {
        return;
      }

      const section = ensureSection(linkedCounterparty);
      if (!section.invoices.some((item) => item.id === invoice.id)) {
        section.invoices.push(invoice);
      }
      attachedInvoiceIds.add(invoice.id);
    });

    byCounterparty.forEach((section) => {
      section.contracts.sort((a, b) => parseRuDate(b.createdAt) - parseRuDate(a.createdAt));
      section.invoices.sort((a, b) => parseRuDate(b.date) - parseRuDate(a.date));
    });

    const ordered = Array.from(byCounterparty.values()).sort((a, b) =>
      (a.counterparty?.name || '').localeCompare(b.counterparty?.name || '', 'ru'),
    );

    const unlinkedInvoices = invoices
      .filter((invoice) => !attachedInvoiceIds.has(invoice.id))
      .sort((a, b) => parseRuDate(b.date) - parseRuDate(a.date));

    if (unlinkedInvoices.length > 0) {
      ordered.push({
        key: 'unlinked-invoices',
        counterparty: null,
        contracts: [],
        invoices: unlinkedInvoices,
      });
    }

    return ordered;
  }, [contracts, counterparties, invoices, invoicesById]);

  const totalItemsCount = contracts.length + invoices.length;

  const filters: Array<{ id: DocumentFilter; label: string }> = [
    { id: 'all', label: `Все (${totalItemsCount})` },
    { id: 'contracts', label: `Договоры (${contracts.length})` },
    { id: 'invoices', label: `Счета (${invoices.length})` },
    { id: 'counterparties', label: `Контрагенты (${counterparties.length})` },
  ];

  const visibleSections = useMemo(() => {
    return sections.filter((section) => {
      if (activeFilter === 'contracts') {
        return section.contracts.length > 0;
      }

      if (activeFilter === 'invoices') {
        return section.invoices.length > 0;
      }

      if (activeFilter === 'counterparties') {
        return Boolean(section.counterparty);
      }

      return section.contracts.length > 0 || section.invoices.length > 0;
    });
  }, [activeFilter, sections]);

  const counterpartiesWithStats = useMemo(() => {
    const statsById = new Map<string, { contractsCount: number; invoicesCount: number }>();

    sections.forEach((section) => {
      if (!section.counterparty) {
        return;
      }

      statsById.set(section.counterparty.id, {
        contractsCount: section.contracts.length,
        invoicesCount: section.invoices.length,
      });
    });

    return counterparties
      .map((counterparty) => {
        const stats = statsById.get(counterparty.id) || { contractsCount: 0, invoicesCount: 0 };
        return {
          counterparty,
          contractsCount: stats.contractsCount,
          invoicesCount: stats.invoicesCount,
        };
      })
      .sort((a, b) => formatCounterpartyName(a.counterparty).localeCompare(formatCounterpartyName(b.counterparty), 'ru'));
  }, [counterparties, sections]);

  const resetCounterpartyForm = () => {
    setCounterpartyForm(createEmptyCounterpartyForm());
    setEditingCounterpartyId(null);
  };

  const resetInvoiceForm = () => {
    setInvoiceForm(createEmptyInvoiceForm());
    setEditingInvoiceId(null);
  };

  const resetContractForm = () => {
    setContractForm(createEmptyContractForm());
    setEditingContractId(null);
  };

  const closeCounterpartyForm = () => {
    setIsCounterpartyFormOpen(false);
    setCounterpartyError(null);
    resetCounterpartyForm();
  };

  const closeInvoiceForm = () => {
    setIsInvoiceFormOpen(false);
    setInvoiceError(null);
    resetInvoiceForm();
  };

  const closeContractForm = () => {
    setIsContractFormOpen(false);
    setContractError(null);
    resetContractForm();
  };

  const openCreateCounterpartyForm = () => {
    setCounterpartyError(null);
    resetCounterpartyForm();
    setIsInvoiceFormOpen(false);
    setIsContractFormOpen(false);
    setIsCounterpartyFormOpen(true);
  };

  const openEditCounterpartyForm = (counterparty: Counterparty) => {
    setCounterpartyError(null);
    setCounterpartyForm(createCounterpartyFormFromEntity(counterparty));
    setEditingCounterpartyId(counterparty.id);
    setIsInvoiceFormOpen(false);
    setIsContractFormOpen(false);
    setIsCounterpartyFormOpen(true);
  };

  const openCreateInvoiceForm = () => {
    setInvoiceError(null);
    resetInvoiceForm();
    setIsCounterpartyFormOpen(false);
    setIsContractFormOpen(false);
    setIsInvoiceFormOpen(true);
  };

  const openEditInvoiceForm = (invoice: Invoice) => {
    setInvoiceError(null);
    setInvoiceForm(createInvoiceFormFromEntity(invoice));
    setEditingInvoiceId(invoice.id);
    setIsCounterpartyFormOpen(false);
    setIsContractFormOpen(false);
    setIsInvoiceFormOpen(true);
    applyActiveFilter('invoices');
  };

  const openEditContractForm = (contract: Contract) => {
    setContractError(null);
    setContractForm(createContractFormFromEntity(contract));
    setEditingContractId(contract.id);
    setIsCounterpartyFormOpen(false);
    setIsInvoiceFormOpen(false);
    setIsContractFormOpen(true);
    applyActiveFilter('contracts');
  };

  const updateCounterpartyBankAccountField = (index: number, key: keyof BankAccount, value: string) => {
    setCounterpartyForm((prev) => {
      const current =
        prev.bankAccounts && prev.bankAccounts.length > 0
          ? [...prev.bankAccounts]
          : [createEmptyBankAccount()];
      const currentItem = current[index] || createEmptyBankAccount();
      const nextItem: BankAccount = { ...currentItem, [key]: value };
      current[index] = nextItem;
      return { ...prev, bankAccounts: current };
    });
  };

  const addCounterpartyBankAccount = () => {
    setCounterpartyForm((prev) => {
      const current = prev.bankAccounts ? [...prev.bankAccounts] : [];
      current.push(createEmptyBankAccount());
      return { ...prev, bankAccounts: current };
    });
  };

  const removeCounterpartyBankAccount = (index: number) => {
    setCounterpartyForm((prev) => {
      const current =
        prev.bankAccounts && prev.bankAccounts.length > 0
          ? [...prev.bankAccounts]
          : [createEmptyBankAccount()];

      if (current.length <= 1) {
        return { ...prev, bankAccounts: [createEmptyBankAccount()] };
      }

      const next = current.filter((_, itemIndex) => itemIndex !== index);
      return { ...prev, bankAccounts: next.length > 0 ? next : [createEmptyBankAccount()] };
    });
  };

  const updateInvoiceItemField = (index: number, key: keyof InvoiceItemForm, value: string) => {
    setInvoiceForm((prev) => {
      const current = prev.items && prev.items.length > 0 ? [...prev.items] : [createEmptyInvoiceItemForm()];
      const currentItem = current[index] || createEmptyInvoiceItemForm();
      current[index] = { ...currentItem, [key]: value };
      return { ...prev, items: current };
    });
  };

  const addInvoiceItem = () => {
    setInvoiceForm((prev) => {
      const current = prev.items ? [...prev.items] : [];
      current.push(createEmptyInvoiceItemForm());
      return { ...prev, items: current };
    });
  };

  const removeInvoiceItem = (index: number) => {
    setInvoiceForm((prev) => {
      const current = prev.items && prev.items.length > 0 ? [...prev.items] : [createEmptyInvoiceItemForm()];

      if (current.length <= 1) {
        return { ...prev, items: [createEmptyInvoiceItemForm()] };
      }

      const next = current.filter((_, itemIndex) => itemIndex !== index);
      return { ...prev, items: next.length > 0 ? next : [createEmptyInvoiceItemForm()] };
    });
  };

  const handleSaveCounterparty = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setCounterpartyError(null);

    if (!counterpartyForm.name.trim()) {
      setCounterpartyError('Введите название контрагента.');
      return;
    }

    if (counterpartyForm.legalType !== 'person' && !counterpartyForm.inn.trim()) {
      setCounterpartyError('Введите ИНН контрагента.');
      return;
    }

    if (isCounterpartyCompanyType(counterpartyForm.legalType) && !counterpartyForm.directorName.trim()) {
      setCounterpartyError('Для ООО/АО укажите ФИО руководителя.');
      return;
    }

    const normalizedBankAccounts = normalizeBankAccounts(counterpartyForm.bankAccounts);
    const primaryBankAccount = getPrimaryBankAccount(normalizedBankAccounts);

    const payload = {
      legalType: counterpartyForm.legalType,
      name: counterpartyForm.name.trim(),
      inn: counterpartyForm.inn.trim(),
      address: (counterpartyForm.legalType === 'person'
        ? (counterpartyForm.registrationAddress || counterpartyForm.address)
        : counterpartyForm.address
      ).trim(),
      contactPerson: counterpartyForm.contactPerson.trim(),
      email: counterpartyForm.email.trim(),
      phone: counterpartyForm.phone.trim(),
      directorName: counterpartyForm.directorName.trim(),
      ogrn: counterpartyForm.ogrn.trim(),
      kpp: counterpartyForm.kpp.trim(),
      ogrnip: counterpartyForm.ogrnip.trim(),
      passportSeries: counterpartyForm.passportSeries.trim(),
      passportNumber: counterpartyForm.passportNumber.trim(),
      passportIssuedBy: counterpartyForm.passportIssuedBy.trim(),
      passportIssuedDate: counterpartyForm.passportIssuedDate.trim(),
      passportDepartmentCode: counterpartyForm.passportDepartmentCode.trim(),
      registrationAddress: counterpartyForm.registrationAddress.trim(),
      residenceAddress: counterpartyForm.residenceAddress.trim(),
      bankAccounts: normalizedBankAccounts,
      bankName: primaryBankAccount.bankName,
      checkingAccount: primaryBankAccount.checkingAccount,
      correspondentAccount: primaryBankAccount.correspondentAccount,
      bik: primaryBankAccount.bik,
    };

    setIsSavingCounterparty(true);
    try {
      if (editingCounterpartyId) {
        await onUpdateCounterparty(editingCounterpartyId, payload);
      } else {
        await onCreateCounterparty(payload);
      }
      closeCounterpartyForm();
    } catch (error) {
      setCounterpartyError(
        error instanceof Error
          ? error.message
          : editingCounterpartyId
            ? 'Не удалось обновить контрагента.'
            : 'Не удалось создать контрагента.',
      );
    } finally {
      setIsSavingCounterparty(false);
    }
  };

  const handleSaveInvoice = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setInvoiceError(null);

    if (!invoiceForm.items || invoiceForm.items.length === 0) {
      setInvoiceError('Добавьте хотя бы одну позицию счета.');
      return;
    }

    const normalizedItems = [];
    for (let index = 0; index < invoiceForm.items.length; index += 1) {
      const item = invoiceForm.items[index];
      const quantity = Number(item.quantity);
      const price = Number(item.price);

      if (!item.description.trim()) {
        setInvoiceError(`Заполните описание позиции №${index + 1}.`);
        return;
      }

      if (!Number.isFinite(quantity) || quantity <= 0) {
        setInvoiceError(`Количество в позиции №${index + 1} должно быть больше 0.`);
        return;
      }

      if (!Number.isFinite(price) || price < 0) {
        setInvoiceError(`Цена в позиции №${index + 1} должна быть неотрицательной.`);
        return;
      }

      normalizedItems.push({
        description: item.description.trim(),
        quantity,
        price,
        unit: item.unit.trim() || 'шт',
      });
    }

    const payload = {
      number: invoiceForm.number.trim() || undefined,
      date: invoiceForm.date.trim() || undefined,
      paymentDueDate: invoiceForm.paymentDueDate.trim() || undefined,
      status: invoiceForm.status,
      currency: invoiceForm.currency.trim() || 'RUB',
      commissionPercent:
        invoiceForm.commissionPercent.trim() === ''
          ? undefined
          : Number(invoiceForm.commissionPercent),
      vatRate: invoiceForm.vatRate,
      vatMode: invoiceForm.vatMode,
      supplierProfileId: invoiceForm.supplierProfileId || undefined,
      counterpartyId: invoiceForm.counterpartyId || undefined,
      items: normalizedItems,
    };

    if (
      payload.commissionPercent != null &&
      (!Number.isFinite(payload.commissionPercent) || payload.commissionPercent < 0)
    ) {
      setInvoiceError('Процент комиссии должен быть неотрицательным числом.');
      return;
    }

    setIsSavingInvoice(true);
    try {
      if (editingInvoiceId) {
        await onUpdateInvoice(editingInvoiceId, payload);
      } else {
        await onCreateInvoice(payload);
      }

      closeInvoiceForm();
      applyActiveFilter('invoices');
    } catch (error) {
      setInvoiceError(
        error instanceof Error
          ? error.message
          : editingInvoiceId
            ? 'Не удалось обновить счет.'
            : 'Не удалось создать счет.',
      );
    } finally {
      setIsSavingInvoice(false);
    }
  };

  const handleSaveContract = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setContractError(null);

    if (!editingContractId) {
      setContractError('Не выбран договор для редактирования.');
      return;
    }

    if (!contractForm.number.trim()) {
      setContractError('Введите номер договора.');
      return;
    }

    if (!contractForm.counterpartyId) {
      setContractError('Выберите контрагента.');
      return;
    }

    const paymentTerms = Number(contractForm.paymentTerms);
    if (!Number.isFinite(paymentTerms) || paymentTerms <= 0) {
      setContractError('Срок оплаты должен быть больше 0.');
      return;
    }

    let amount: number | null = null;
    if (contractForm.amount.trim()) {
      amount = Number(contractForm.amount);
      if (!Number.isFinite(amount) || amount < 0) {
        setContractError('Сумма должна быть неотрицательной.');
        return;
      }
    }

    let contractDataPatch: Record<string, unknown> | undefined;
    if (isEditingGoodsSaleExtendedContract) {
      const deliveryTermDays =
        contractForm.deliveryTermDays.trim() === '' ? null : Number(contractForm.deliveryTermDays);
      if (deliveryTermDays != null && (!Number.isFinite(deliveryTermDays) || deliveryTermDays <= 0)) {
        setContractError('Срок поставки (календарных дней) должен быть больше 0.');
        return;
      }

      const confidentialityPenaltyAmount =
        contractForm.confidentialityPenaltyAmount.trim() === '' ? null : Number(contractForm.confidentialityPenaltyAmount);
      if (
        confidentialityPenaltyAmount != null &&
        (!Number.isFinite(confidentialityPenaltyAmount) || confidentialityPenaltyAmount < 0)
      ) {
        setContractError('Штраф за нарушение конфиденциальности должен быть неотрицательным.');
        return;
      }

      if (editingContractVatRate === 'none' && !isEditingGoodsSaleSellerPerson && !contractForm.supplierTaxBasis.trim()) {
        setContractError('Укажите основание/режим без НДС.');
        return;
      }
      if (!contractForm.buyerFullName.trim()) {
        setContractError('Укажите ФИО покупателя (для шаблона купли-продажи).');
        return;
      }
      if (!contractForm.buyerPassportSeries.trim() || !contractForm.buyerPassportNumber.trim()) {
        setContractError('Укажите серию и номер паспорта покупателя.');
        return;
      }
      if (!contractForm.buyerRegistrationAddress.trim() && !contractForm.buyerResidenceAddress.trim()) {
        setContractError('Укажите адрес покупателя (регистрации или проживания).');
        return;
      }
      if (!contractForm.buyerPhone.trim()) {
        setContractError('Укажите телефон покупателя (используется для уведомлений).');
        return;
      }

      contractDataPatch = {
        signingCity: contractForm.signingCity.trim(),
        deliveryCity: contractForm.deliveryCity.trim(),
        deliveryTermDays,
        deliveryTermBasis: contractForm.deliveryTermBasis.trim(),
        deliveryCostPayer: contractForm.deliveryCostPayer,
        deliveryMethod: contractForm.deliveryMethod.trim(),
        purchasePurpose: contractForm.purchasePurpose,
        supplierTaxBasis:
          editingContractVatRate === 'none' && !isEditingGoodsSaleSellerPerson ? contractForm.supplierTaxBasis.trim() : '',
        confidentialityPenaltyAmount,
        privateBuyerRf: {
          fullName: contractForm.buyerFullName.trim(),
          phone: contractForm.buyerPhone.trim(),
          email: contractForm.buyerEmail.trim(),
          passportSeries: contractForm.buyerPassportSeries.trim(),
          passportNumber: contractForm.buyerPassportNumber.trim(),
          passportIssuedBy: contractForm.buyerPassportIssuedBy.trim(),
          passportIssuedDate: contractForm.buyerPassportIssuedDate.trim(),
          passportDepartmentCode: contractForm.buyerPassportDepartmentCode.trim(),
          registrationAddress: contractForm.buyerRegistrationAddress.trim(),
          residenceAddress: contractForm.buyerResidenceAddress.trim(),
        },
      };
    }
    if (isEditingSupplyLegalEntitiesContract) {
      const buyerType = editingContractCounterparty?.legalType;
      const supplierType = editingContractSupplierProfile?.legalType;
      if (!isLegalEntityOrIpType(supplierType) || !isLegalEntityOrIpType(buyerType)) {
        setContractError('Шаблон "юрлица и ИП" доступен только для сторон типов ООО/АО/ИП. Физлица не поддерживаются.');
        return;
      }
      const parsedPrepaymentPercent = Number(contractForm.prepaymentPercent);
      const prepaymentPercent =
        Number.isFinite(parsedPrepaymentPercent) && parsedPrepaymentPercent >= 0
          ? Math.min(100, Math.max(0, parsedPrepaymentPercent))
          : 0;
      const hasPrepayment = contractForm.paymentMode !== 'custom';
      if (contractForm.paymentMode === 'partial_prepayment' && (prepaymentPercent <= 0 || prepaymentPercent >= 100)) {
        setContractError('Для частичной предоплаты процент должен быть в диапазоне от 0.01 до 99.99.');
        return;
      }
      if (contractForm.paymentMode === 'custom' && !contractForm.customPaymentTerms.trim()) {
        setContractError('Для режима «Иное условие оплаты» заполните текст условия.');
        return;
      }
      contractDataPatch = {
        ...(contractDataPatch || {}),
        contractScenario: 'supply_legal_entities',
        deliveryCostPayer: 'buyer',
        hasPrepayment,
        prepaymentPercent: contractForm.paymentMode === 'full_prepayment' ? 100 : hasPrepayment ? prepaymentPercent : 0,
        customPaymentTerms: contractForm.paymentMode === 'custom' ? contractForm.customPaymentTerms.trim() : '',
        supplierSignerPosition: contractForm.supplierSignerPosition.trim(),
        supplierSignerName: contractForm.supplierSignerName.trim(),
        supplierSignerBasis: contractForm.supplierSignerBasis.trim(),
        buyerSignerPosition: contractForm.buyerSignerPosition.trim(),
        buyerSignerName: contractForm.buyerSignerName.trim(),
        buyerSignerBasis: contractForm.buyerSignerBasis.trim(),
      };
    }

    setIsSavingContract(true);
    try {
      await onUpdateContract(editingContractId, {
        number: contractForm.number.trim(),
        title: contractForm.title.trim() || undefined,
        type: contractForm.type,
        status: contractForm.status,
        counterpartyId: contractForm.counterpartyId,
        invoiceId: contractForm.invoiceId || null,
        amount,
        paymentTerms,
        includeDelivery: contractForm.includeDelivery,
        deliveryDate: contractForm.includeDelivery ? contractForm.deliveryDate.trim() || null : null,
        contractData: contractDataPatch,
      });
      closeContractForm();
    } catch (error) {
      setContractError(error instanceof Error ? error.message : 'Не удалось обновить договор.');
    } finally {
      setIsSavingContract(false);
    }
  };

  const showDeleteError = (message: string) => {
    if (typeof window !== 'undefined') {
      window.alert(message);
    }
  };

  const handleDeleteCounterparty = async (counterparty: Counterparty) => {
    const name = formatCounterpartyName(counterparty);
    const isConfirmed = window.confirm(`Удалить контрагента "${name}"?`);
    if (!isConfirmed) {
      return;
    }

    setCounterpartyError(null);
    setDeletingCounterpartyId(counterparty.id);
    try {
      await onDeleteCounterparty(counterparty.id);
      if (editingCounterpartyId === counterparty.id) {
        closeCounterpartyForm();
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось удалить контрагента.';
      setCounterpartyError(message);
      showDeleteError(message);
    } finally {
      setDeletingCounterpartyId((currentId) => (currentId === counterparty.id ? null : currentId));
    }
  };

  const handleDeleteInvoice = async (invoice: Invoice) => {
    const label = invoice.number || invoice.id;
    const isConfirmed = window.confirm(`Удалить счет "${label}"?`);
    if (!isConfirmed) {
      return;
    }

    setInvoiceError(null);
    setDeletingInvoiceId(invoice.id);
    try {
      await onDeleteInvoice(invoice.id);
      if (editingInvoiceId === invoice.id) {
        closeInvoiceForm();
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось удалить счет.';
      setInvoiceError(message);
      showDeleteError(message);
    } finally {
      setDeletingInvoiceId((currentId) => (currentId === invoice.id ? null : currentId));
    }
  };

  const handleDeleteContract = async (contract: Contract) => {
    const label = contract.number || contract.id;
    const isConfirmed = window.confirm(`Удалить договор "${label}"?`);
    if (!isConfirmed) {
      return;
    }

    setContractError(null);
    setDeletingContractId(contract.id);
    try {
      await onDeleteContract(contract.id);
      if (editingContractId === contract.id) {
        closeContractForm();
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось удалить договор.';
      setContractError(message);
      showDeleteError(message);
    } finally {
      setDeletingContractId((currentId) => (currentId === contract.id ? null : currentId));
    }
  };

  const resolveInvoiceCounterparty = (invoice: Invoice, fallbackCounterparty?: Counterparty | null) => {
    if (invoice.counterpartyId) {
      return counterpartiesById.get(invoice.counterpartyId) || fallbackCounterparty || null;
    }

    return fallbackCounterparty || null;
  };
  const handleCreateContractFromInvoice = async (invoice: Invoice, fallbackCounterparty?: Counterparty | null) => {
    const linkedCounterparty = resolveInvoiceCounterparty(invoice, fallbackCounterparty);
    if (!linkedCounterparty?.id) {
      const message = 'Нельзя создать договор: у счета не указан контрагент.';
      setContractError(message);
      if (typeof window !== 'undefined') {
        window.alert(message);
      }
      return;
    }

    setContractError(null);
    onStartContractFromInvoice(invoice.id);
  };

  const isInvoiceFileDownloading = (invoiceId: string, format: 'pdf' | 'docx') =>
    downloadingInvoiceFile?.invoiceId === invoiceId && downloadingInvoiceFile?.format === format;

  const handleDownloadInvoice = async (
    invoice: Invoice,
    format: 'pdf' | 'docx',
    fallbackCounterparty?: Counterparty | null,
  ) => {
    const resolvedCounterparty = resolveInvoiceCounterparty(invoice, fallbackCounterparty);
    const fileName = buildInvoiceDocumentName(invoice, resolvedCounterparty?.name);

    setDownloadingInvoiceFile({ invoiceId: invoice.id, format });

    try {
      const invoiceDocument = buildInvoiceDocument({
        invoice,
        counterparty: resolvedCounterparty,
        settings,
        logoSrc: resolveAbsoluteLogoUrl(),
      });

      const blob = await api.generateContractFile(format, {
        html: invoiceDocument.html,
        css: invoiceDocument.css,
        fileName,
      });

      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `${fileName}.${format}`;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      window.URL.revokeObjectURL(url);
    } catch (error) {
      const message = error instanceof Error ? error.message : `Не удалось скачать счет в формате ${format.toUpperCase()}.`;
      setInvoiceError(message);
      showDeleteError(message);
    } finally {
      setDownloadingInvoiceFile((current) =>
        current?.invoiceId === invoice.id && current.format === format ? null : current,
      );
    }
  };

  const isEditingCounterparty = Boolean(editingCounterpartyId);
  const isEditingInvoice = Boolean(editingInvoiceId);
  const counterpartyBankAccounts =
    counterpartyForm.bankAccounts && counterpartyForm.bankAccounts.length > 0
      ? counterpartyForm.bankAccounts
      : [createEmptyBankAccount()];
  const invoiceItems = invoiceForm.items && invoiceForm.items.length > 0 ? invoiceForm.items : [createEmptyInvoiceItemForm()];

  return (
    <div className="space-y-6">
      <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">Документы по контрагентам</h1>
          <p className="text-slate-500 dark:text-slate-400">В одном месте договоры и счета, сгруппированные по контрагентам.</p>
          <div className="mt-4 inline-flex rounded-xl border border-slate-200 dark:border-slate-700 p-1 bg-slate-100/80 dark:bg-slate-800/70">
            {filters.map((filter) => {
              const isActive = activeFilter === filter.id;
              return (
                <button
                  key={filter.id}
                  onClick={() => {
                    applyActiveFilter(filter.id);
                  }}
                  className={`px-3 py-1.5 rounded-lg text-xs sm:text-sm font-medium transition-colors ${
                    isActive
                      ? 'bg-white text-blue-600 shadow-sm dark:bg-slate-900 dark:text-blue-400'
                      : 'text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100'
                  }`}
                >
                  {filter.label}
                </button>
              );
            })}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant={isCounterpartyFormOpen ? 'secondary' : 'outline'}
            icon={<Icons.Users className="w-4 h-4" />}
            onClick={() => {
              if (isCounterpartyFormOpen && !isEditingCounterparty) {
                closeCounterpartyForm();
                return;
              }
              openCreateCounterpartyForm();
            }}
          >
            Новый контрагент
          </Button>
          <Button
            variant={isInvoiceFormOpen ? 'secondary' : 'outline'}
            icon={<Icons.Receipt className="w-4 h-4" />}
            onClick={() => {
              if (isInvoiceFormOpen && !isEditingInvoice) {
                closeInvoiceForm();
                return;
              }
              openCreateInvoiceForm();
            }}
          >
            Новый счет
          </Button>
          <Button icon={<Icons.Plus className="w-4 h-4" />} onClick={() => onNavigate('create-contract')}>
            Новый договор
          </Button>
        </div>
      </div>

      {isCounterpartyFormOpen && (
        <Card className="p-5">
          <form className="space-y-4" onSubmit={handleSaveCounterparty}>
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">
                {isEditingCounterparty ? 'Редактировать контрагента' : 'Добавить контрагента'}
              </h2>
              <button
                type="button"
                className="text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
                onClick={closeCounterpartyForm}
              >
                <Icons.X className="w-4 h-4" />
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Select
                label="Тип контрагента"
                value={counterpartyForm.legalType}
                onChange={(event) =>
                  setCounterpartyForm((prev) => {
                    const nextType = event.target.value as CounterpartyLegalType;
                    if (nextType !== 'person' || prev.legalType === 'person' || isEditingCounterparty) {
                      return { ...prev, legalType: nextType };
                    }

                    return {
                      ...prev,
                      legalType: nextType,
                      ...DEFAULT_PERSON_COUNTERPARTY_VALUES,
                    };
                  })
                }
                options={[
                  { value: 'ooo', label: 'ООО' },
                  { value: 'ao', label: 'АО' },
                  { value: 'ip', label: 'ИП' },
                  { value: 'person', label: 'Физ. лицо' },
                ]}
              />
              <Input
                label={getCounterpartyNameFieldLabel(counterpartyForm.legalType)}
                value={counterpartyForm.name}
                onChange={(event) => setCounterpartyForm((prev) => ({ ...prev, name: event.target.value }))}
                placeholder={getCounterpartyNamePlaceholder(counterpartyForm.legalType)}
              />
              <Input
                label={counterpartyForm.legalType === 'person' ? 'ИНН (необязательно)' : 'ИНН'}
                value={counterpartyForm.inn}
                onChange={(event) => setCounterpartyForm((prev) => ({ ...prev, inn: event.target.value }))}
                placeholder={counterpartyForm.legalType === 'person' ? 'Можно оставить пустым' : '7701234567'}
              />
              {isCounterpartyCompanyType(counterpartyForm.legalType) ? (
                <>
                  <Input
                    label="Руководитель (ФИО)"
                    value={counterpartyForm.directorName}
                    onChange={(event) => setCounterpartyForm((prev) => ({ ...prev, directorName: event.target.value }))}
                    placeholder="Иванов Иван Иванович"
                  />
                  <Input
                    label="ОГРН"
                    value={counterpartyForm.ogrn}
                    onChange={(event) => setCounterpartyForm((prev) => ({ ...prev, ogrn: event.target.value }))}
                    placeholder="1127746000000"
                  />
                  <Input
                    label="КПП"
                    value={counterpartyForm.kpp}
                    onChange={(event) => setCounterpartyForm((prev) => ({ ...prev, kpp: event.target.value }))}
                    placeholder="770101001"
                  />
                </>
              ) : counterpartyForm.legalType === 'ip' ? (
                <Input
                  label="ОГРНИП"
                  value={counterpartyForm.ogrnip}
                  onChange={(event) => setCounterpartyForm((prev) => ({ ...prev, ogrnip: event.target.value }))}
                  placeholder="315665800000000"
                />
              ) : (
                <div className="hidden md:block" />
              )}

              <Input
                label="Контактное лицо"
                value={counterpartyForm.contactPerson}
                onChange={(event) => setCounterpartyForm((prev) => ({ ...prev, contactPerson: event.target.value }))}
                placeholder={isCounterpartyCompanyType(counterpartyForm.legalType) ? 'Иванов Иван' : 'Петров Петр'}
              />
              <Input
                label="Телефон"
                value={counterpartyForm.phone}
                onChange={(event) => setCounterpartyForm((prev) => ({ ...prev, phone: event.target.value }))}
                placeholder="+7XXXXXXXXXX"
              />
              <Input
                label="Email"
                type="email"
                value={counterpartyForm.email}
                onChange={(event) => setCounterpartyForm((prev) => ({ ...prev, email: event.target.value }))}
                placeholder="manager@company.ru"
              />
              {counterpartyForm.legalType === 'person' ? (
                <>
                  <Input
                    label="Серия паспорта"
                    value={counterpartyForm.passportSeries}
                    onChange={(event) => setCounterpartyForm((prev) => ({ ...prev, passportSeries: event.target.value }))}
                    placeholder="6017"
                  />
                  <Input
                    label="Номер паспорта"
                    value={counterpartyForm.passportNumber}
                    onChange={(event) => setCounterpartyForm((prev) => ({ ...prev, passportNumber: event.target.value }))}
                    placeholder="004863"
                  />
                  <div className="md:col-span-2">
                    <Input
                      label="Кем выдан паспорт"
                      value={counterpartyForm.passportIssuedBy}
                      onChange={(event) =>
                        setCounterpartyForm((prev) => ({ ...prev, passportIssuedBy: event.target.value }))
                      }
                      placeholder="УФМС..."
                    />
                  </div>
                  <Input
                    label="Дата выдачи паспорта"
                    value={counterpartyForm.passportIssuedDate}
                    onChange={(event) =>
                      setCounterpartyForm((prev) => ({ ...prev, passportIssuedDate: event.target.value }))
                    }
                    placeholder="21.09.2016"
                  />
                  <Input
                    label="Код подразделения"
                    value={counterpartyForm.passportDepartmentCode}
                    onChange={(event) =>
                      setCounterpartyForm((prev) => ({ ...prev, passportDepartmentCode: event.target.value }))
                    }
                    placeholder="___-___"
                  />
                  <div className="md:col-span-2">
                    <Input
                      label="Адрес регистрации"
                      value={counterpartyForm.registrationAddress}
                      onChange={(event) =>
                        setCounterpartyForm((prev) => ({ ...prev, registrationAddress: event.target.value }))
                      }
                      placeholder="Адрес регистрации"
                    />
                  </div>
                  <div className="md:col-span-2">
                    <Input
                      label="Адрес проживания"
                      value={counterpartyForm.residenceAddress}
                      onChange={(event) =>
                        setCounterpartyForm((prev) => ({ ...prev, residenceAddress: event.target.value }))
                      }
                      placeholder="Адрес проживания"
                    />
                  </div>
                </>
              ) : null}
              <div className="md:col-span-2">
                <Input
                  label={counterpartyForm.legalType === 'person' ? 'Адрес (общий)' : 'Адрес'}
                  value={counterpartyForm.address}
                  onChange={(event) => setCounterpartyForm((prev) => ({ ...prev, address: event.target.value }))}
                  placeholder="г. Москва, ул. Пример, д. 1"
                />
              </div>
              <div className="md:col-span-2 flex items-center justify-between gap-2">
                <div className="text-xs font-semibold text-slate-600 dark:text-slate-400 uppercase tracking-wide">
                  Банковские реквизиты
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  icon={<Icons.Plus className="w-4 h-4" />}
                  onClick={addCounterpartyBankAccount}
                >
                  Добавить счет
                </Button>
              </div>
              <div className="md:col-span-2 space-y-3">
                {counterpartyBankAccounts.map((account, index) => (
                  <div
                    key={`counterparty-bank-account-${index}`}
                    className="rounded-lg border border-slate-200 dark:border-slate-700 p-3"
                  >
                    <div className="flex items-center justify-between gap-2 mb-3">
                      <p className="text-sm font-medium text-slate-800 dark:text-slate-200">Счет {index + 1}</p>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        icon={<Icons.Trash className="w-4 h-4" />}
                        onClick={() => removeCounterpartyBankAccount(index)}
                        disabled={counterpartyBankAccounts.length <= 1}
                      >
                        Удалить
                      </Button>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      <div className="md:col-span-2">
                        <Input
                          label="Банк"
                          value={account.bankName}
                          onChange={(event) => updateCounterpartyBankAccountField(index, 'bankName', event.target.value)}
                          placeholder="ПАО Сбербанк"
                        />
                      </div>
                      <Input
                        label="Расчетный счет"
                        value={account.checkingAccount}
                        onChange={(event) =>
                          updateCounterpartyBankAccountField(index, 'checkingAccount', event.target.value)
                        }
                        placeholder="40702810938000000000"
                      />
                      <Input
                        label="Корр. счет"
                        value={account.correspondentAccount}
                        onChange={(event) =>
                          updateCounterpartyBankAccountField(index, 'correspondentAccount', event.target.value)
                        }
                        placeholder="30101810400000000225"
                      />
                      <Input
                        label="БИК"
                        value={account.bik}
                        onChange={(event) => updateCounterpartyBankAccountField(index, 'bik', event.target.value)}
                        placeholder="044525225"
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {counterpartyError && <p className="text-sm text-red-600 dark:text-red-400">{counterpartyError}</p>}

            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={closeCounterpartyForm}>
                Отмена
              </Button>
              <Button type="submit" disabled={isSavingCounterparty}>
                {isSavingCounterparty
                  ? 'Сохраняю...'
                  : isEditingCounterparty
                    ? 'Сохранить изменения'
                    : 'Сохранить контрагента'}
              </Button>
            </div>
          </form>
        </Card>
      )}

      {isInvoiceFormOpen && (
        <Card className="p-5">
          <form className="space-y-4" onSubmit={handleSaveInvoice}>
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">
                {isEditingInvoice ? 'Редактировать счет' : 'Добавить счет'}
              </h2>
              <button
                type="button"
                className="text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
                onClick={closeInvoiceForm}
              >
                <Icons.X className="w-4 h-4" />
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Select
                label="Контрагент"
                value={invoiceForm.counterpartyId}
                onChange={(event) => setInvoiceForm((prev) => ({ ...prev, counterpartyId: event.target.value }))}
                options={[
                  { value: '', label: 'Без привязки к контрагенту' },
                  ...counterparties.map((counterparty) => ({
                    value: counterparty.id,
                    label: formatCounterpartyName(counterparty),
                  })),
                ]}
              />
              <Select
                label="Статус"
                value={invoiceForm.status}
                onChange={(event) => setInvoiceForm((prev) => ({ ...prev, status: event.target.value as Invoice['status'] }))}
                options={[
                  { value: 'Не оплачен', label: 'Не оплачен' },
                  { value: 'Оплачен', label: 'Оплачен' },
                ]}
              />
              <Select
                label="Профиль компании"
                value={invoiceForm.supplierProfileId}
                onChange={(event) => setInvoiceForm((prev) => ({ ...prev, supplierProfileId: event.target.value }))}
                options={
                  supplierProfiles.length > 0
                    ? supplierProfiles.map((profile, index) => ({
                        value: profile.id,
                        label: profile.companyName || `Компания ${index + 1}`,
                      }))
                    : [{ value: '', label: 'Нет профилей компании в настройках' }]
                }
              />
              <Input
                label="Номер счета (необязательно)"
                value={invoiceForm.number}
                onChange={(event) => setInvoiceForm((prev) => ({ ...prev, number: event.target.value }))}
                placeholder="СЧ-2026-001"
              />
              <Input
                label="Дата (дд.мм.гггг)"
                value={invoiceForm.date}
                onChange={(event) => setInvoiceForm((prev) => ({ ...prev, date: event.target.value }))}
                placeholder="16.02.2026"
              />
              <Input
                label="Оплатить до (дд.мм.гггг)"
                value={invoiceForm.paymentDueDate}
                onChange={(event) => setInvoiceForm((prev) => ({ ...prev, paymentDueDate: event.target.value }))}
                placeholder="26.02.2026"
              />
              <Input
                label="Валюта"
                value={invoiceForm.currency}
                onChange={(event) => setInvoiceForm((prev) => ({ ...prev, currency: event.target.value.toUpperCase() }))}
                placeholder="RUB"
              />
              <Input
                label="Процент комиссии"
                type="number"
                min={0}
                step="0.1"
                value={invoiceForm.commissionPercent}
                onChange={(event) => setInvoiceForm((prev) => ({ ...prev, commissionPercent: event.target.value }))}
                placeholder="6"
              />
              <Select
                label="Ставка НДС"
                value={invoiceForm.vatRate}
                onChange={(event) => setInvoiceForm((prev) => ({ ...prev, vatRate: event.target.value as VatRate }))}
                options={[
                  { value: 'none', label: getVatRateLabel('none') },
                  { value: '0', label: getVatRateLabel('0') },
                  { value: '10', label: getVatRateLabel('10') },
                  { value: '20', label: getVatRateLabel('20') },
                ]}
              />
              <Select
                label="Режим НДС"
                value={invoiceForm.vatMode}
                onChange={(event) => setInvoiceForm((prev) => ({ ...prev, vatMode: event.target.value as VatMode }))}
                options={[
                  { value: 'included', label: getVatModeLabel('included') },
                  { value: 'on_top', label: getVatModeLabel('on_top') },
                ]}
              />
            </div>

            <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-3">
              <div className="text-sm font-medium text-slate-900 dark:text-slate-100 mb-3">Позиции счета</div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[1060px] text-sm">
                  <thead>
                    <tr className="text-left text-slate-600 dark:text-slate-300 border-b border-slate-200 dark:border-slate-700">
                      <th className="px-2 py-2 font-medium w-16">№</th>
                      <th className="px-2 py-2 font-medium min-w-[360px]">Наименование товаров, работ, услуг</th>
                      <th className="px-2 py-2 font-medium w-28">Кол-во</th>
                      <th className="px-2 py-2 font-medium w-28">Ед. изм.</th>
                      <th className="px-2 py-2 font-medium w-40">Цена за единицу</th>
                      <th className="px-2 py-2 font-medium w-44">Общая сумма</th>
                      <th className="px-2 py-2 font-medium w-16"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {invoiceItems.map((item, index) => {
                      const quantity = Number(item.quantity);
                      const price = Number(item.price);
                      const lineTotal =
                        Number.isFinite(quantity) && Number.isFinite(price) ? quantity * price : 0;

                      return (
                        <tr key={item.id} className="border-b border-slate-100 dark:border-slate-800 align-top">
                          <td className="px-2 py-2">
                            <span className="inline-flex h-10 w-10 items-center justify-center rounded-md border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200">
                              {index + 1}
                            </span>
                          </td>
                          <td className="px-2 py-2">
                            <input
                              value={item.description}
                              onChange={(event) => updateInvoiceItemField(index, 'description', event.target.value)}
                              placeholder="Наименование"
                              className="w-full px-3 py-2 border rounded-md shadow-sm placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 dark:bg-slate-900 dark:text-slate-100 dark:border-slate-700 dark:placeholder-slate-600 border-slate-300"
                            />
                          </td>
                          <td className="px-2 py-2">
                            <input
                              type="number"
                              min={1}
                              step="0.01"
                              value={item.quantity}
                              onChange={(event) => updateInvoiceItemField(index, 'quantity', event.target.value)}
                              className="w-full px-3 py-2 border rounded-md shadow-sm placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 dark:bg-slate-900 dark:text-slate-100 dark:border-slate-700 dark:placeholder-slate-600 border-slate-300"
                            />
                          </td>
                          <td className="px-2 py-2">
                            <input
                              value={item.unit}
                              onChange={(event) => updateInvoiceItemField(index, 'unit', event.target.value)}
                              className="w-full px-3 py-2 border rounded-md shadow-sm placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 dark:bg-slate-900 dark:text-slate-100 dark:border-slate-700 dark:placeholder-slate-600 border-slate-300"
                            />
                          </td>
                          <td className="px-2 py-2">
                            <input
                              type="number"
                              min={0}
                              step="0.01"
                              value={item.price}
                              onChange={(event) => updateInvoiceItemField(index, 'price', event.target.value)}
                              className="w-full px-3 py-2 border rounded-md shadow-sm placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 dark:bg-slate-900 dark:text-slate-100 dark:border-slate-700 dark:placeholder-slate-600 border-slate-300"
                            />
                          </td>
                          <td className="px-2 py-2">
                            <div className="h-10 px-3 rounded-md border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 flex items-center text-slate-800 dark:text-slate-200 whitespace-nowrap">
                              {lineTotal.toLocaleString('ru-RU', { maximumFractionDigits: 2 })}
                            </div>
                          </td>
                          <td className="px-2 py-2">
                            <button
                              type="button"
                              onClick={() => removeInvoiceItem(index)}
                              disabled={invoiceItems.length <= 1}
                              className="inline-flex items-center justify-center h-10 w-10 rounded-md border border-slate-300 text-slate-500 hover:text-red-600 hover:border-red-300 disabled:opacity-50 disabled:cursor-not-allowed dark:border-slate-700 dark:text-slate-400 dark:hover:text-red-300 dark:hover:border-red-800"
                              title="Удалить позицию"
                            >
                              <Icons.Trash className="w-4 h-4" />
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <div className="mt-3 flex justify-start">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  icon={<Icons.Plus className="w-4 h-4" />}
                  onClick={addInvoiceItem}
                >
                  Добавить позицию
                </Button>
              </div>
            </div>

            {invoiceError && <p className="text-sm text-red-600 dark:text-red-400">{invoiceError}</p>}

            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={closeInvoiceForm}>
                Отмена
              </Button>
              <Button type="submit" disabled={isSavingInvoice}>
                {isSavingInvoice ? 'Сохраняю...' : isEditingInvoice ? 'Сохранить изменения' : 'Сохранить счет'}
              </Button>
            </div>
          </form>
        </Card>
      )}

      {isContractFormOpen && (
        <Card className="p-5">
          <form className="space-y-4" onSubmit={handleSaveContract}>
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">Редактировать договор</h2>
              <button
                type="button"
                className="text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
                onClick={closeContractForm}
              >
                <Icons.X className="w-4 h-4" />
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Input
                label="Номер договора"
                value={contractForm.number}
                onChange={(event) => setContractForm((prev) => ({ ...prev, number: event.target.value }))}
                placeholder="Д-2026-001"
              />
              <Input
                label="Название"
                value={contractForm.title}
                onChange={(event) => setContractForm((prev) => ({ ...prev, title: event.target.value }))}
                placeholder="Договор оказания услуг"
              />
              <Select
                label="Тип договора"
                value={contractForm.type}
                onChange={(event) => setContractForm((prev) => ({ ...prev, type: event.target.value as ContractType }))}
                options={[
                  { value: ContractType.SERVICE, label: ContractType.SERVICE },
                  { value: ContractType.SUPPLY, label: ContractType.SUPPLY },
                  { value: ContractType.NDA, label: ContractType.NDA },
                  { value: ContractType.RENTAL, label: ContractType.RENTAL },
                ]}
              />
              <Select
                label="Статус"
                value={contractForm.status}
                onChange={(event) => setContractForm((prev) => ({ ...prev, status: event.target.value as Contract['status'] }))}
                options={[
                  { value: 'Черновик', label: 'Черновик' },
                  { value: 'На согласовании', label: 'На согласовании' },
                  { value: 'Подписан', label: 'Подписан' },
                  { value: 'Истек', label: 'Истек' },
                ]}
              />
              <Select
                label="Контрагент"
                value={contractForm.counterpartyId}
                onChange={(event) =>
                  setContractForm((prev) => {
                    const nextCounterpartyId = event.target.value;
                    if (!isEditingGoodsSaleExtendedContract) {
                      return { ...prev, counterpartyId: nextCounterpartyId };
                    }

                    const selectedCounterparty = counterpartiesById.get(nextCounterpartyId) || null;
                    return {
                      ...prev,
                      counterpartyId: nextCounterpartyId,
                      ...createBuyerContractFieldsFromCounterparty(selectedCounterparty),
                    };
                  })
                }
                options={[
                  { value: '', label: 'Выберите контрагента...' },
                  ...counterparties.map((counterparty) => ({
                    value: counterparty.id,
                    label: formatCounterpartyName(counterparty),
                  })),
                ]}
              />
              <Select
                label="Связанный счет"
                value={contractForm.invoiceId}
                onChange={(event) => setContractForm((prev) => ({ ...prev, invoiceId: event.target.value }))}
                options={[
                  { value: '', label: 'Без связанного счета' },
                  ...invoices.map((invoice) => ({
                    value: invoice.id,
                    label: `${invoice.number} (${invoice.amount.toLocaleString('ru-RU')} ${invoice.currency})`,
                  })),
                ]}
              />
              <Input
                label="Сумма"
                type="number"
                min={0}
                step="0.01"
                value={contractForm.amount}
                onChange={(event) => setContractForm((prev) => ({ ...prev, amount: event.target.value }))}
                placeholder="0"
              />
              <Input
                label="Срок оплаты (дни)"
                type="number"
                min={1}
                step="1"
                value={contractForm.paymentTerms}
                onChange={(event) => setContractForm((prev) => ({ ...prev, paymentTerms: event.target.value }))}
              />
              <div className="md:col-span-2">
                <label className="inline-flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
                  <input
                    type="checkbox"
                    checked={contractForm.includeDelivery}
                    onChange={(event) => setContractForm((prev) => ({ ...prev, includeDelivery: event.target.checked }))}
                    className="h-4 w-4 text-blue-600"
                  />
                  Включить условие о сроке поставки
                </label>
              </div>
              {contractForm.includeDelivery && (
                <Input
                  label="Дата поставки (дд.мм.гггг)"
                  value={contractForm.deliveryDate}
                  onChange={(event) => setContractForm((prev) => ({ ...prev, deliveryDate: event.target.value }))}
                  placeholder="31.12.2026"
                />
              )}
            </div>

            {isEditingGoodsSaleExtendedContract && (
              <div className="rounded-lg border border-indigo-200 bg-indigo-50/70 dark:bg-indigo-900/20 dark:border-indigo-900/60 p-4 space-y-4">
                <div>
                  <h3 className="text-sm font-semibold text-indigo-900 dark:text-indigo-200">
                    Доп. условия шаблона купли-продажи
                  </h3>
                  <p className="mt-1 text-xs text-indigo-700 dark:text-indigo-300">
                    Эти поля влияют на текст расширенного шаблона договора и будут сохранены в параметрах договора.
                  </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <Input
                    label="Город подписания договора"
                    value={contractForm.signingCity}
                    onChange={(event) => setContractForm((prev) => ({ ...prev, signingCity: event.target.value }))}
                    placeholder="Челябинск"
                  />
                  <Input
                    label="Город доставки"
                    value={contractForm.deliveryCity}
                    onChange={(event) => setContractForm((prev) => ({ ...prev, deliveryCity: event.target.value }))}
                    placeholder="Челябинск"
                  />
                  <Input
                    label="Срок поставки (календарных дней)"
                    type="number"
                    min={1}
                    step="1"
                    value={contractForm.deliveryTermDays}
                    onChange={(event) => setContractForm((prev) => ({ ...prev, deliveryTermDays: event.target.value }))}
                  />
                  <Select
                    label="Кто оплачивает доставку"
                    value={contractForm.deliveryCostPayer}
                    onChange={(event) =>
                      setContractForm((prev) => ({
                        ...prev,
                        deliveryCostPayer: event.target.value as typeof prev.deliveryCostPayer,
                      }))
                    }
                    options={[
                      { value: 'seller', label: 'Поставщик (включено в цену)' },
                      { value: 'buyer', label: 'Покупатель (отдельно)' },
                      { value: '', label: 'Выбрать...' },
                    ]}
                  />
                  <div className="md:col-span-2">
                    <Input
                      label="Основание отсчета срока поставки"
                      value={contractForm.deliveryTermBasis}
                      onChange={(event) => setContractForm((prev) => ({ ...prev, deliveryTermBasis: event.target.value }))}
                      placeholder="с даты поступления полной оплаты"
                    />
                  </div>
                  <div className="md:col-span-2">
                    <Input
                      label="Способ доставки"
                      value={contractForm.deliveryMethod}
                      onChange={(event) => setContractForm((prev) => ({ ...prev, deliveryMethod: event.target.value }))}
                      placeholder="ТК/курьер по согласованию Сторон"
                    />
                  </div>
                  <Select
                    label="Цель покупки"
                    value={contractForm.purchasePurpose}
                    onChange={(event) =>
                      setContractForm((prev) => ({
                        ...prev,
                        purchasePurpose: event.target.value as typeof prev.purchasePurpose,
                      }))
                    }
                    options={[
                      { value: 'personal', label: 'Для личных нужд' },
                      { value: 'business', label: 'Для предпринимательской деятельности' },
                    ]}
                  />
                  <Input
                    label="Штраф за нарушение конфиденциальности, ₽"
                    type="number"
                    min={0}
                    step="1"
                    value={contractForm.confidentialityPenaltyAmount}
                    onChange={(event) =>
                      setContractForm((prev) => ({ ...prev, confidentialityPenaltyAmount: event.target.value }))
                    }
                    placeholder="30000"
                  />
                  {editingContractVatRate === 'none' && (
                    isEditingGoodsSaleSellerPerson ? (
                      <div className="md:col-span-2 rounded-md border border-indigo-200 dark:border-indigo-900/60 bg-indigo-50/70 dark:bg-indigo-900/20 px-3 py-2 text-xs text-indigo-800 dark:text-indigo-200">
                        Для продавца-физлица в договоре будет указано: «НДС не начисляется».
                      </div>
                    ) : (
                      <div className="md:col-span-2">
                        <Input
                          label="Основание/режим без НДС"
                          value={contractForm.supplierTaxBasis}
                          onChange={(event) => setContractForm((prev) => ({ ...prev, supplierTaxBasis: event.target.value }))}
                          placeholder="УСН, без НДС"
                        />
                      </div>
                    )
                  )}
                </div>

                <div className="border-t border-indigo-200/70 dark:border-indigo-900/50 pt-4">
                  <h4 className="text-sm font-semibold text-indigo-900 dark:text-indigo-200">
                    Данные покупателя для шаблона (паспорт/контакты)
                  </h4>
                  <p className="mt-1 text-xs text-indigo-700 dark:text-indigo-300">
                    Эти данные используются в тексте договора и реквизитах покупателя (без привязки к шаблонным заглушкам).
                  </p>

                  <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div className="md:col-span-2">
                      <Input
                        label="ФИО покупателя"
                        value={contractForm.buyerFullName}
                        onChange={(event) => setContractForm((prev) => ({ ...prev, buyerFullName: event.target.value }))}
                        placeholder="Петров Петр Петрович"
                      />
                    </div>
                    <Input
                      label="Телефон покупателя"
                      value={contractForm.buyerPhone}
                      onChange={(event) => setContractForm((prev) => ({ ...prev, buyerPhone: event.target.value }))}
                      placeholder="+7..."
                    />
                    <Input
                      label="Email покупателя"
                      type="email"
                      value={contractForm.buyerEmail}
                      onChange={(event) => setContractForm((prev) => ({ ...prev, buyerEmail: event.target.value }))}
                      placeholder="(можно оставить пустым)"
                    />
                    <Input
                      label="Серия паспорта"
                      value={contractForm.buyerPassportSeries}
                      onChange={(event) =>
                        setContractForm((prev) => ({ ...prev, buyerPassportSeries: event.target.value }))
                      }
                      placeholder="4511"
                    />
                    <Input
                      label="Номер паспорта"
                      value={contractForm.buyerPassportNumber}
                      onChange={(event) =>
                        setContractForm((prev) => ({ ...prev, buyerPassportNumber: event.target.value }))
                      }
                      placeholder="654321"
                    />
                    <div className="md:col-span-2">
                      <Input
                        label="Кем выдан паспорт"
                        value={contractForm.buyerPassportIssuedBy}
                        onChange={(event) =>
                          setContractForm((prev) => ({ ...prev, buyerPassportIssuedBy: event.target.value }))
                        }
                      />
                    </div>
                    <Input
                      label="Дата выдачи паспорта"
                      value={contractForm.buyerPassportIssuedDate}
                      onChange={(event) =>
                        setContractForm((prev) => ({ ...prev, buyerPassportIssuedDate: event.target.value }))
                      }
                      placeholder="21.09.2016 или 2016-09-21"
                    />
                    <Input
                      label="Код подразделения"
                      value={contractForm.buyerPassportDepartmentCode}
                      onChange={(event) =>
                        setContractForm((prev) => ({ ...prev, buyerPassportDepartmentCode: event.target.value }))
                      }
                      placeholder="000-000"
                    />
                    <div className="md:col-span-2">
                      <Input
                        label="Адрес регистрации"
                        value={contractForm.buyerRegistrationAddress}
                        onChange={(event) =>
                          setContractForm((prev) => ({ ...prev, buyerRegistrationAddress: event.target.value }))
                        }
                      />
                    </div>
                    <div className="md:col-span-2">
                      <Input
                        label="Адрес проживания (если отличается)"
                        value={contractForm.buyerResidenceAddress}
                        onChange={(event) =>
                          setContractForm((prev) => ({ ...prev, buyerResidenceAddress: event.target.value }))
                        }
                      />
                    </div>
                  </div>
                </div>
              </div>
            )}
            {isEditingSupplyLegalEntitiesContract && (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50/70 dark:bg-emerald-900/20 dark:border-emerald-900/60 p-4 space-y-4">
                <div>
                  <h3 className="text-sm font-semibold text-emerald-900 dark:text-emerald-200">
                    Подписанты для шаблона «юрлица и ИП»
                  </h3>
                  <p className="mt-1 text-xs text-emerald-700 dark:text-emerald-300">
                    Значения сохраняются в параметрах договора и используются для автоподстановки в документ.
                  </p>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <Select
                    label="Режим оплаты"
                    value={contractForm.paymentMode}
                    onChange={(event) =>
                      setContractForm((prev) => ({
                        ...prev,
                        paymentMode: event.target.value as typeof prev.paymentMode,
                      }))
                    }
                    options={[
                      { value: 'full_prepayment', label: '100% предоплата' },
                      { value: 'partial_prepayment', label: 'Частичная предоплата + доплата' },
                      { value: 'custom', label: 'Иное условие оплаты' },
                    ]}
                  />
                  {contractForm.paymentMode === 'partial_prepayment' && (
                    <Input
                      label="Размер предоплаты, %"
                      type="number"
                      min={0.01}
                      max={99.99}
                      step="0.01"
                      value={contractForm.prepaymentPercent}
                      onChange={(event) => setContractForm((prev) => ({ ...prev, prepaymentPercent: event.target.value }))}
                    />
                  )}
                  {contractForm.paymentMode === 'custom' && (
                    <div className="md:col-span-2">
                      <Input
                        label="Иное условие оплаты"
                        value={contractForm.customPaymentTerms}
                        onChange={(event) => setContractForm((prev) => ({ ...prev, customPaymentTerms: event.target.value }))}
                        placeholder="Оплата по согласованному графику"
                      />
                    </div>
                  )}
                  <Input
                    label="Поставщик: должность подписанта"
                    value={contractForm.supplierSignerPosition}
                    onChange={(event) => setContractForm((prev) => ({ ...prev, supplierSignerPosition: event.target.value }))}
                    placeholder={defaultSupplierSigner.position || 'директор'}
                  />
                  <Input
                    label="Поставщик: ФИО подписанта"
                    value={contractForm.supplierSignerName}
                    onChange={(event) => setContractForm((prev) => ({ ...prev, supplierSignerName: event.target.value }))}
                    placeholder={defaultSupplierSigner.name || 'Иванов Иван Иванович'}
                  />
                  <div className="md:col-span-2">
                    <Input
                      label="Поставщик: основание полномочий"
                      value={contractForm.supplierSignerBasis}
                      onChange={(event) => setContractForm((prev) => ({ ...prev, supplierSignerBasis: event.target.value }))}
                      placeholder={defaultSupplierSigner.basis || 'Устава'}
                    />
                  </div>
                  <Input
                    label="Покупатель: должность подписанта"
                    value={contractForm.buyerSignerPosition}
                    onChange={(event) => setContractForm((prev) => ({ ...prev, buyerSignerPosition: event.target.value }))}
                    placeholder={defaultBuyerSigner.position || 'директор'}
                  />
                  <Input
                    label="Покупатель: ФИО подписанта"
                    value={contractForm.buyerSignerName}
                    onChange={(event) => setContractForm((prev) => ({ ...prev, buyerSignerName: event.target.value }))}
                    placeholder={defaultBuyerSigner.name || 'Петров Петр Петрович'}
                  />
                  <div className="md:col-span-2">
                    <Input
                      label="Покупатель: основание полномочий"
                      value={contractForm.buyerSignerBasis}
                      onChange={(event) => setContractForm((prev) => ({ ...prev, buyerSignerBasis: event.target.value }))}
                      placeholder={defaultBuyerSigner.basis || 'Устава'}
                    />
                  </div>
                </div>
              </div>
            )}

            {contractError && <p className="text-sm text-red-600 dark:text-red-400">{contractError}</p>}

            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={closeContractForm}>
                Отмена
              </Button>
              <Button type="submit" disabled={isSavingContract}>
                {isSavingContract ? 'Сохраняю...' : 'Сохранить договор'}
              </Button>
            </div>
          </form>
        </Card>
      )}

      {activeFilter === 'counterparties' ? (
        <>
          {counterpartiesWithStats.length === 0 && (
            <Card className="p-8 text-center text-slate-600 dark:text-slate-300">
              Список контрагентов пока пуст.
            </Card>
          )}

          {counterpartiesWithStats.map(({ counterparty, contractsCount, invoicesCount }) => (
            <Card key={counterparty.id} className="p-5 space-y-4">
              <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                    {formatCounterpartyName(counterparty)}
                  </h2>
                  <p className="text-sm text-slate-500 dark:text-slate-400">
                    {getCounterpartyTypeLabel(counterparty.legalType)} • ИНН {counterparty.inn}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Badge type="neutral">Договоры: {contractsCount}</Badge>
                  <Badge type="info">Счета: {invoicesCount}</Badge>
                  <Button
                    size="sm"
                    variant="outline"
                    icon={<Icons.Edit className="w-4 h-4" />}
                    onClick={() => openEditCounterpartyForm(counterparty)}
                  >
                    Редактировать
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="border-red-200 text-red-600 hover:bg-red-50 hover:text-red-700 dark:border-red-900/60 dark:text-red-300 dark:hover:bg-red-900/30 dark:hover:text-red-200"
                    icon={<Icons.Trash className="w-4 h-4" />}
                    onClick={() => handleDeleteCounterparty(counterparty)}
                    disabled={deletingCounterpartyId === counterparty.id}
                  >
                    {deletingCounterpartyId === counterparty.id ? 'Удаляю...' : 'Удалить'}
                  </Button>
                </div>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm text-slate-600 dark:text-slate-300">
                <div>
                  <span className="text-slate-500 dark:text-slate-400">Контакт:</span>{' '}
                  {counterparty.contactPerson || 'Не указан'}
                </div>
                <div>
                  <span className="text-slate-500 dark:text-slate-400">Email:</span>{' '}
                  {counterparty.email || 'Не указан'}
                </div>
                <div>
                  <span className="text-slate-500 dark:text-slate-400">Счетов:</span>{' '}
                  {normalizeBankAccounts(counterparty.bankAccounts, counterparty).length || 'Не указаны'}
                </div>
                <div className="md:col-span-2">
                  <span className="text-slate-500 dark:text-slate-400">Адрес:</span>{' '}
                  {counterparty.address || 'Не указан'}
                </div>
              </div>
            </Card>
          ))}
        </>
      ) : (
        <>
          {visibleSections.length === 0 && (
            <Card className="p-8 text-center text-slate-600 dark:text-slate-300">
              Для выбранного типа документов данных пока нет.
            </Card>
          )}

          {visibleSections.map((section) => {
            const invoicesByIdInSection = new Map<string, Invoice>(
              section.invoices.map((invoice) => [invoice.id, invoice] as [string, Invoice]),
            );
            const usedInvoiceIds = new Set<string>();
            const pairedRows: Array<{
              key: string;
              date: string;
              invoice?: Invoice;
              contract?: Contract;
            }> = [];

            section.contracts.forEach((contract) => {
              const linkedInvoice = contract.invoiceId ? invoicesByIdInSection.get(contract.invoiceId) : undefined;
              if (linkedInvoice) {
                usedInvoiceIds.add(linkedInvoice.id);
              }

              pairedRows.push({
                key: `pair-${contract.id}`,
                date: linkedInvoice?.date || contract.createdAt || '',
                invoice: linkedInvoice,
                contract,
              });
            });

            section.invoices.forEach((invoice) => {
              if (usedInvoiceIds.has(invoice.id)) {
                return;
              }

              pairedRows.push({
                key: `invoice-only-${invoice.id}`,
                date: invoice.date || '',
                invoice,
              });
            });

            pairedRows.sort((a, b) => parseRuDate(b.date) - parseRuDate(a.date));

            return (
              <Card key={section.key} className="p-5 space-y-5">
                <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
                  <div>
                    <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                      {section.counterparty ? formatCounterpartyName(section.counterparty) : 'Счета без контрагента'}
                    </h2>
                    {section.counterparty ? (
                      <p className="text-sm text-slate-500 dark:text-slate-400">
                        ИНН {section.counterparty.inn}
                      </p>
                    ) : (
                      <p className="text-sm text-slate-500 dark:text-slate-400">
                        Эти счета не связаны ни с одним договором.
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge type="neutral">Договоры: {section.contracts.length}</Badge>
                    <Badge type="info">Счета: {section.invoices.length}</Badge>
                    {section.counterparty && (
                      <>
                        <Button
                          size="sm"
                          variant="outline"
                          icon={<Icons.Edit className="w-4 h-4" />}
                          onClick={() => openEditCounterpartyForm(section.counterparty)}
                        >
                          Редактировать
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          className="border-red-200 text-red-600 hover:bg-red-50 hover:text-red-700 dark:border-red-900/60 dark:text-red-300 dark:hover:bg-red-900/30 dark:hover:text-red-200"
                          icon={<Icons.Trash className="w-4 h-4" />}
                          onClick={() => handleDeleteCounterparty(section.counterparty)}
                          disabled={deletingCounterpartyId === section.counterparty.id}
                        >
                          {deletingCounterpartyId === section.counterparty.id ? 'Удаляю...' : 'Удалить'}
                        </Button>
                      </>
                    )}
                  </div>
                </div>

                {activeFilter === 'all' ? (
                  <div className="space-y-3">
                    {pairedRows.length === 0 ? (
                      <p className="text-sm text-slate-500 dark:text-slate-400">Нет документов для этого контрагента.</p>
                    ) : (
                      pairedRows.map((row) => {
                        const linkedContracts = row.invoice ? contractsByInvoiceId.get(row.invoice.id) || [] : [];
                        const invoiceCounterparty = row.invoice
                          ? resolveInvoiceCounterparty(row.invoice, section.counterparty)
                          : null;
                        const invoiceCounterpartyName = invoiceCounterparty?.name;
                        const invoiceFileName = row.invoice
                          ? buildInvoiceDocumentName(row.invoice, invoiceCounterpartyName)
                          : '';
                        const contractFileName = row.contract ? buildContractDocumentName(row.contract) : '';

                        return (
                          <div
                            key={row.key}
                            className="rounded-xl border border-slate-200 dark:border-slate-800 p-3 bg-slate-50/30 dark:bg-slate-900/30 space-y-3"
                          >
                            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                              За {row.date || 'дату не указали'}
                            </div>
                            <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
                              <div className="border border-slate-200 dark:border-slate-800 rounded-lg p-3 bg-white/80 dark:bg-slate-900/60">
                                <div className="flex items-center justify-between mb-2">
                                  <div className="text-sm font-medium text-slate-900 dark:text-slate-100">Счет</div>
                                  {row.invoice ? (
                                    <Badge type={getInvoiceBadgeType(row.invoice.status)}>{row.invoice.status}</Badge>
                                  ) : (
                                    <Badge type="neutral">Нет счета</Badge>
                                  )}
                                </div>
                                {row.invoice ? (
                                  <>
                                    <div className="font-mono text-sm font-medium text-slate-900 dark:text-slate-100">
                                      {row.invoice.number}
                                    </div>
                                    <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-1 break-all">
                                      {invoiceFileName}
                                    </div>
                                    <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">{row.invoice.date}</div>
                                    <div className="mt-3 flex items-end justify-between gap-3">
                                      <div className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                                        {formatMoney(row.invoice.amount, row.invoice.currency)}
                                      </div>
                                      <div className="text-right">
                                        <div className="text-xs text-slate-500 dark:text-slate-400">
                                          {row.invoice.items.length} поз.
                                        </div>
                                        <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                                          Комиссия: {(row.invoice.commissionPercent ?? 6).toLocaleString('ru-RU')}%
                                        </div>
                                      </div>
                                    </div>
                                    <div className="mt-3 pt-2 border-t border-slate-200 dark:border-slate-800 text-xs text-slate-500 dark:text-slate-400">
                                      {linkedContracts.length > 0 ? (
                                        <div className="flex flex-wrap items-center gap-2">
                                          <span>Связан с договором:</span>
                                          {linkedContracts.slice(0, 2).map((contract) => (
                                            <button
                                              key={contract.id}
                                              onClick={() => onOpenContract(contract.id)}
                                              className="text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
                                            >
                                              {contract.number}
                                            </button>
                                          ))}
                                          {linkedContracts.length > 2 && <span>+{linkedContracts.length - 2}</span>}
                                        </div>
                                      ) : (
                                        <span>Без привязки к договору</span>
                                      )}
                                    </div>
                                    <div className="mt-3 flex flex-wrap items-center gap-2">
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        icon={<Icons.Download className="w-4 h-4" />}
                                        onClick={() => handleDownloadInvoice(row.invoice, 'docx', invoiceCounterparty)}
                                        disabled={Boolean(downloadingInvoiceFile)}
                                      >
                                        {isInvoiceFileDownloading(row.invoice.id, 'docx') ? 'Генерация...' : 'Word'}
                                      </Button>
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        icon={<Icons.FileText className="w-4 h-4" />}
                                        onClick={() => handleDownloadInvoice(row.invoice, 'pdf', invoiceCounterparty)}
                                        disabled={Boolean(downloadingInvoiceFile)}
                                      >
                                        {isInvoiceFileDownloading(row.invoice.id, 'pdf') ? 'Генерация...' : 'PDF'}
                                      </Button>
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        icon={<Icons.Edit className="w-4 h-4" />}
                                        onClick={() => openEditInvoiceForm(row.invoice)}
                                      >
                                        Редактировать
                                      </Button>
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        className="border-red-200 text-red-600 hover:bg-red-50 hover:text-red-700 dark:border-red-900/60 dark:text-red-300 dark:hover:bg-red-900/30 dark:hover:text-red-200"
                                        icon={<Icons.Trash className="w-4 h-4" />}
                                        onClick={() => handleDeleteInvoice(row.invoice)}
                                        disabled={deletingInvoiceId === row.invoice.id}
                                      >
                                        {deletingInvoiceId === row.invoice.id ? 'Удаляю...' : 'Удалить'}
                                      </Button>
                                      <Button
                                        size="sm"
                                        variant="ghost"
                                        icon={<Icons.ChevronRight className="w-4 h-4" />}
                                        onClick={() => onOpenInvoice(row.invoice.id)}
                                      >
                                        Открыть
                                      </Button>
                                    </div>
                                  </>
                                ) : (
                                  <p className="text-sm text-slate-500 dark:text-slate-400">Счет не найден для этой даты.</p>
                                )}
                              </div>

                              <div className="border border-slate-200 dark:border-slate-800 rounded-lg p-3 bg-white/80 dark:bg-slate-900/60">
                                <div className="flex items-center justify-between mb-2">
                                  <div className="text-sm font-medium text-slate-900 dark:text-slate-100">Договор</div>
                                  {row.contract ? (
                                    <Badge type={getContractBadgeType(row.contract.status)}>{row.contract.status}</Badge>
                                  ) : (
                                    <Badge type="neutral">Нет договора</Badge>
                                  )}
                                </div>
                                {row.contract ? (
                                  <>
                                    <div className="font-mono text-xs text-slate-500 dark:text-slate-400">{row.contract.number}</div>
                                    <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-1 break-all">
                                      {contractFileName}
                                    </div>
                                    <div className="font-medium text-slate-900 dark:text-slate-100 truncate mt-1">
                                      {row.contract.title}
                                    </div>
                                    <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                                      {row.contract.createdAt}
                                    </div>
                                    {typeof row.contract.amount === 'number' && (
                                      <div className="mt-3 text-lg font-semibold text-slate-900 dark:text-slate-100">
                                        {row.contract.amount.toLocaleString('ru-RU', { maximumFractionDigits: 0 })} ₽
                                      </div>
                                    )}
                                    <div className="mt-3 flex items-center gap-2">
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        icon={<Icons.Edit className="w-4 h-4" />}
                                        onClick={() => openEditContractForm(row.contract)}
                                      >
                                        Редактировать
                                      </Button>
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        className="border-red-200 text-red-600 hover:bg-red-50 hover:text-red-700 dark:border-red-900/60 dark:text-red-300 dark:hover:bg-red-900/30 dark:hover:text-red-200"
                                        icon={<Icons.Trash className="w-4 h-4" />}
                                        onClick={() => handleDeleteContract(row.contract)}
                                        disabled={deletingContractId === row.contract.id}
                                      >
                                        {deletingContractId === row.contract.id ? 'Удаляю...' : 'Удалить'}
                                      </Button>
                                      <Button
                                        size="sm"
                                        variant="ghost"
                                        icon={<Icons.ChevronRight className="w-4 h-4" />}
                                        onClick={() => onOpenContract(row.contract.id)}
                                      >
                                        Открыть
                                      </Button>
                                    </div>
                                  </>
                                ) : (
                                  <div className="space-y-3">
                                    <p className="text-sm text-slate-500 dark:text-slate-400">Договор не найден для этой даты.</p>
                                    {row.invoice && (
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        icon={<Icons.Plus className="w-4 h-4" />}
                                        onClick={() => handleCreateContractFromInvoice(row.invoice, invoiceCounterparty)}
                                      >
                                        Создать договор из счета
                                      </Button>
                                    )}
                                  </div>
                                )}
                              </div>
                            </div>
                          </div>
                        );
                      })
                    )}
                  </div>
                ) : (
                  <>
                    {activeFilter !== 'invoices' && (
                      <div className="space-y-3">
                        <div className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-300">
                          <Icons.FileText className="w-4 h-4" />
                          Договоры
                        </div>
                        {section.contracts.length === 0 ? (
                          <p className="text-sm text-slate-500 dark:text-slate-400">Нет договоров для этого контрагента.</p>
                        ) : (
                          <div className="space-y-2">
                            {section.contracts.map((contract) => (
                              <div
                                key={contract.id}
                                className="w-full border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-3 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                              >
                                <div className="flex items-start justify-between gap-3">
                                  <div className="min-w-0">
                                    <div className="font-mono text-xs text-slate-500 dark:text-slate-400">{contract.number}</div>
                                    <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-1 break-all">
                                      {buildContractDocumentName(contract)}
                                    </div>
                                    <div className="font-medium text-slate-900 dark:text-slate-100 truncate">{contract.title}</div>
                                    <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">{contract.createdAt}</div>
                                  </div>
                                  <div className="flex items-center gap-2 shrink-0">
                                    {typeof contract.amount === 'number' && (
                                      <span className="hidden sm:inline text-xs text-slate-600 dark:text-slate-400">
                                        {contract.amount.toLocaleString('ru-RU', { maximumFractionDigits: 0 })} ₽
                                      </span>
                                    )}
                                    <Badge type={getContractBadgeType(contract.status)}>{contract.status}</Badge>
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      icon={<Icons.Edit className="w-4 h-4" />}
                                      onClick={() => openEditContractForm(contract)}
                                    >
                                      Редактировать
                                    </Button>
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      className="border-red-200 text-red-600 hover:bg-red-50 hover:text-red-700 dark:border-red-900/60 dark:text-red-300 dark:hover:bg-red-900/30 dark:hover:text-red-200"
                                      icon={<Icons.Trash className="w-4 h-4" />}
                                      onClick={() => handleDeleteContract(contract)}
                                      disabled={deletingContractId === contract.id}
                                    >
                                      {deletingContractId === contract.id ? 'Удаляю...' : 'Удалить'}
                                    </Button>
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      icon={<Icons.ChevronRight className="w-4 h-4" />}
                                      onClick={() => onOpenContract(contract.id)}
                                    >
                                      Открыть
                                    </Button>
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    {activeFilter !== 'contracts' && (
                      <div className="space-y-3">
                        <div className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-300">
                          <Icons.Receipt className="w-4 h-4" />
                          Счета
                        </div>
                        {section.invoices.length === 0 ? (
                          <p className="text-sm text-slate-500 dark:text-slate-400">Нет счетов для этого контрагента.</p>
                        ) : (
                          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                            {section.invoices.map((invoice) => {
                              const linkedContracts = contractsByInvoiceId.get(invoice.id) || [];
                              const invoiceCounterparty = resolveInvoiceCounterparty(invoice, section.counterparty);
                              return (
                                <div
                                  key={invoice.id}
                                  className="border border-slate-200 dark:border-slate-800 rounded-lg p-3 bg-slate-50/50 dark:bg-slate-900/50"
                                >
                                  <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
                                    <div>
                                      <div className="font-mono text-sm font-medium text-slate-900 dark:text-slate-100">{invoice.number}</div>
                                      <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-1 break-all">
                                        {buildInvoiceDocumentName(
                                          invoice,
                                          invoiceCounterparty?.name,
                                        )}
                                      </div>
                                      <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">{invoice.date}</div>
                                    </div>
                                    <div className="flex flex-wrap items-center gap-2">
                                      <Badge type={getInvoiceBadgeType(invoice.status)}>{invoice.status}</Badge>
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        icon={<Icons.Download className="w-4 h-4" />}
                                        onClick={() => handleDownloadInvoice(invoice, 'docx', invoiceCounterparty)}
                                        disabled={Boolean(downloadingInvoiceFile)}
                                      >
                                        {isInvoiceFileDownloading(invoice.id, 'docx') ? 'Генерация...' : 'Word'}
                                      </Button>
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        icon={<Icons.FileText className="w-4 h-4" />}
                                        onClick={() => handleDownloadInvoice(invoice, 'pdf', invoiceCounterparty)}
                                        disabled={Boolean(downloadingInvoiceFile)}
                                      >
                                        {isInvoiceFileDownloading(invoice.id, 'pdf') ? 'Генерация...' : 'PDF'}
                                      </Button>
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        icon={<Icons.Edit className="w-4 h-4" />}
                                        onClick={() => openEditInvoiceForm(invoice)}
                                      >
                                        Редактировать
                                      </Button>
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        className="border-red-200 text-red-600 hover:bg-red-50 hover:text-red-700 dark:border-red-900/60 dark:text-red-300 dark:hover:bg-red-900/30 dark:hover:text-red-200"
                                        icon={<Icons.Trash className="w-4 h-4" />}
                                        onClick={() => handleDeleteInvoice(invoice)}
                                        disabled={deletingInvoiceId === invoice.id}
                                      >
                                        {deletingInvoiceId === invoice.id ? 'Удаляю...' : 'Удалить'}
                                      </Button>
                                      <Button
                                        size="sm"
                                        variant="ghost"
                                        icon={<Icons.ChevronRight className="w-4 h-4" />}
                                        onClick={() => onOpenInvoice(invoice.id)}
                                      >
                                        Открыть
                                      </Button>
                                    </div>
                                  </div>
                                  <div className="mt-3 flex items-end justify-between gap-3">
                                    <div className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                                      {formatMoney(invoice.amount, invoice.currency)}
                                    </div>
                                    <div className="text-right">
                                      <div className="text-xs text-slate-500 dark:text-slate-400">{invoice.items.length} поз.</div>
                                      <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                                        Комиссия: {(invoice.commissionPercent ?? 6).toLocaleString('ru-RU')}%
                                      </div>
                                    </div>
                                  </div>
                                  <div className="mt-3 pt-2 border-t border-slate-200 dark:border-slate-800 text-xs text-slate-500 dark:text-slate-400">
                                    {linkedContracts.length > 0 ? (
                                      <div className="flex flex-wrap items-center gap-2">
                                        <span>Связан с договором:</span>
                                        {linkedContracts.slice(0, 2).map((contract) => (
                                          <button
                                            key={contract.id}
                                            onClick={() => onOpenContract(contract.id)}
                                            className="text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
                                          >
                                            {contract.number}
                                          </button>
                                        ))}
                                        {linkedContracts.length > 2 && <span>+{linkedContracts.length - 2}</span>}
                                      </div>
                                    ) : (
                                      <div className="flex flex-wrap items-center gap-2">
                                        <span>Без привязки к договору</span>
                                        <Button
                                          size="sm"
                                          variant="outline"
                                          icon={<Icons.Plus className="w-4 h-4" />}
                                          onClick={() => handleCreateContractFromInvoice(invoice, invoiceCounterparty)}
                                        >
                                          Создать договор из счета
                                        </Button>
                                      </div>
                                    )}
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    )}
                  </>
                )}
              </Card>
            );
          })}
        </>
      )}
    </div>
  );
};
