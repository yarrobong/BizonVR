import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Card, Button, Input, Select } from '../components/ui';
import { Icons } from '../constants';
import {
  AppSettings,
  BankAccount,
  Contract,
  ContractType,
  Counterparty,
  CounterpartyLegalType,
  Invoice,
  InvoiceItem,
  PrivatePersonRfProfile,
  SupplierCompanyProfile,
  Template,
  VatMode,
  VatRate,
} from '../types';
import { api, CreateCounterpartyPayload } from '../services/api';
import { ContractDocumentPreview, CONTRACT_DOCUMENT_CSS } from '../components/ContractDocumentPreview';
import {
  buildInvoicePricing,
  DEFAULT_PRICING_CONFIG,
  getVatModeLabel,
  getVatRateLabel,
  normalizePricingConfig,
} from '../utils/contractPricing';
import { buildContractDocumentName, buildInvoiceDocumentName } from '../utils/documentNaming';
import { buildInvoiceDocument, INVOICE_LOGO_URL } from '../utils/invoiceDocument';

interface WizardProps {
  onCancel: () => void;
  onFinish: (createdContractId?: string) => void;
  counterparties: Counterparty[];
  invoices: Invoice[];
  initialInvoiceId?: string | null;
  templates: Template[];
  settings: AppSettings | null;
  onContractCreated: () => Promise<void>;
}

interface WizardFormData {
  type: ContractType;
  templateId: string;
  counterpartyId: string;
  paymentTerms: string;
  includeDelivery: boolean;
  deliveryDate: string;
  number: string;
  hasPrepayment: boolean;
  prepaymentPercent: string;
  paymentMode: 'full_prepayment' | 'partial_prepayment' | 'custom';
  customPaymentTerms: string;
  penaltyPercentPerDay: string;
  signingCity: string;
  deliveryCity: string;
  deliveryTermDays: string;
  deliveryTermBasis: string;
  deliveryCostPayer: 'seller' | 'buyer' | '';
  deliveryMethod: string;
  purchasePurpose: 'personal' | 'business';
  supplierTaxBasis: string;
  confidentialityPenaltyAmount: string;
  supplierSignerPosition: string;
  supplierSignerName: string;
  supplierSignerBasis: string;
  buyerSignerPosition: string;
  buyerSignerName: string;
  buyerSignerBasis: string;
}

interface CounterpartyDraft {
  legalType: CounterpartyLegalType;
  inn: string;
  name: string;
  kpp: string;
  address: string;
  contactPerson: string;
  email: string;
  directorName: string;
  ogrn: string;
  ogrnip: string;
  bankName: string;
  bik: string;
  checkingAccount: string;
  correspondentAccount: string;
}

interface InvoiceItemDraft {
  id: string;
  description: string;
  quantity: string;
  unit: string;
  price: string;
}

interface InvoiceDraft {
  date: string;
  paymentDueDate: string;
  commissionPercent: string;
  currency: string;
  vatRate: VatRate;
  vatMode: VatMode;
  supplierProfileId: string;
  supplierBankAccountKey: string;
  items: InvoiceItemDraft[];
}

type PrivateBuyerRfDraft = Pick<
  PrivatePersonRfProfile,
  | 'fullName'
  | 'passportSeries'
  | 'passportNumber'
  | 'passportIssuedBy'
  | 'passportIssuedDate'
  | 'passportDepartmentCode'
  | 'registrationAddress'
  | 'residenceAddress'
  | 'phone'
  | 'email'
>;

type GoodsSaleExtendedContractData = {
  signingCity?: string;
  deliveryCity?: string;
  deliveryTermDays?: number;
  deliveryTermBasis?: string;
  deliveryCostPayer?: 'seller' | 'buyer';
  deliveryMethod?: string;
  purchasePurpose?: 'personal' | 'business';
  supplierTaxBasis?: string;
  confidentialityPenaltyAmount?: number;
};

interface WizardStep {
  num: number;
  title: string;
  description: string;
}

const VAT_MODE_OPTIONS: Array<{ value: VatMode; title: string; description: string }> = [
  {
    value: 'included',
    title: getVatModeLabel('included'),
    description: 'Цена уже включает налог, НДС выделяется справочно.',
  },
  {
    value: 'on_top',
    title: getVatModeLabel('on_top'),
    description: 'Цена без НДС, налог начисляется сверху к итогу.',
  },
];

const WIZARD_STEPS: WizardStep[] = [
  {
    num: 1,
    title: 'Работа с контрагентом',
    description: 'Поиск по ИНН, проверка реквизитов и банковских данных.',
  },
  {
    num: 2,
    title: 'Формирование Счета',
    description: 'Позиции, НДС, дедлайн оплаты и авто-нумерация счета.',
  },
  {
    num: 3,
    title: 'Настройка и генерация Договора',
    description: 'Шаблон, сроки, аванс и пени для автоматической сборки договора.',
  },
  {
    num: 4,
    title: 'Завершение и экспорт',
    description: 'Единая сделка: предпросмотр, архив, email и выгрузка в ЭДО.',
  },
];

const formatCurrency = (amount: number) =>
  amount.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' ₽';

const toDigits = (value?: string) => String(value || '').replace(/\D/g, '');

const todayIsoDate = () => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
};

const addDaysIso = (baseIso: string, days: number) => {
  if (!baseIso) {
    return '';
  }
  const date = new Date(baseIso);
  if (Number.isNaN(date.getTime())) {
    return '';
  }
  date.setDate(date.getDate() + days);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
};

const isoToRuDate = (value?: string) => {
  const raw = String(value || '').trim();
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw);
  if (!match) {
    return raw;
  }
  return `${match[3]}.${match[2]}.${match[1]}`;
};

const ruToIsoDate = (value?: string) => {
  const raw = String(value || '').trim();
  const match = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(raw);
  if (!match) {
    return raw;
  }
  return `${match[3]}-${match[2]}-${match[1]}`;
};

const resolveAbsoluteLogoUrl = () => {
  if (typeof window === 'undefined') {
    return INVOICE_LOGO_URL;
  }

  if (/^https?:\/\//i.test(INVOICE_LOGO_URL) || INVOICE_LOGO_URL.startsWith('data:')) {
    return INVOICE_LOGO_URL;
  }

  return new URL(INVOICE_LOGO_URL, window.location.origin).toString();
};

const createEmptyInvoiceItem = (): InvoiceItemDraft => ({
  id: `wizard-item-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
  description: '',
  quantity: '1',
  unit: 'шт',
  price: '0',
});

const createInitialCounterpartyDraft = (): CounterpartyDraft => ({
  legalType: 'ooo',
  inn: '',
  name: '',
  kpp: '',
  address: '',
  contactPerson: '',
  email: '',
  directorName: '',
  ogrn: '',
  ogrnip: '',
  bankName: '',
  bik: '',
  checkingAccount: '',
  correspondentAccount: '',
});

const createInitialInvoiceDraft = (): InvoiceDraft => {
  const date = todayIsoDate();
  return {
    date,
    paymentDueDate: addDaysIso(date, 5),
    commissionPercent: String(DEFAULT_PRICING_CONFIG.markupPercent),
    currency: 'RUB',
    vatRate: DEFAULT_PRICING_CONFIG.vatRate,
    vatMode: DEFAULT_PRICING_CONFIG.vatMode,
    supplierProfileId: '',
    supplierBankAccountKey: '',
    items: [createEmptyInvoiceItem()],
  };
};

const createInitialPrivateBuyerRfDraft = (): PrivateBuyerRfDraft => ({
  fullName: 'Слижук Дмитрий Васильевич',
  passportSeries: '6017',
  passportNumber: '004863',
  passportIssuedBy: 'МЕЖРАЙОННЫМ ОТДЕЛОМ УФМС РОССИИ ПО РОСТОВСКОЙ ОБЛАСТИ В ГОРОДЕ МИЛЛЕРОВО',
  passportIssuedDate: '21.09.2016',
  passportDepartmentCode: '',
  registrationAddress: 'Ростовская область город Миллерово улица 19 съезд КПСС д99',
  residenceAddress: 'Ростовская область город Миллерово улица 19 съезд КПСС д99',
  phone: '89613289518',
  email: '',
});

const normalizePrivateBuyerRfDraft = (value?: Partial<PrivateBuyerRfDraft> | null): PrivateBuyerRfDraft => ({
  fullName: String(value?.fullName || '').trim(),
  passportSeries: String(value?.passportSeries || '').trim(),
  passportNumber: String(value?.passportNumber || '').trim(),
  passportIssuedBy: String(value?.passportIssuedBy || '').trim(),
  passportIssuedDate: String(value?.passportIssuedDate || '').trim(),
  passportDepartmentCode: String(value?.passportDepartmentCode || '').trim(),
  registrationAddress: String(value?.registrationAddress || '').trim(),
  residenceAddress: String(value?.residenceAddress || '').trim(),
  phone: String(value?.phone || '').trim(),
  email: String(value?.email || '').trim(),
});

const isPrivatePersonGoodsSaleTemplate = (template?: Template | null) => {
  if (!template) {
    return false;
  }

  const id = String(template.id || '').trim();
  const name = String(template.name || '').trim().toLowerCase();
  return (
    id === 't5' ||
    id === 'tpl-goods-sale-extended-conf-2026' ||
    (name.includes('купли') && name.includes('продаж') && name.includes('конфиден'))
  );
};

const isSupplyLegalEntitiesTemplate = (template?: Template | null) => {
  if (!template) {
    return false;
  }

  const id = String(template.id || '').trim();
  const name = String(template.name || '').trim().toLowerCase();
  return (
    id === 'tpl-supply-legal-entities-2026' ||
    (name.includes('поставк') && name.includes('юрлиц') && name.includes('ип') && name.includes('расшир'))
  );
};
const isTemplateCompatibleForParties = (
  template: Template,
  supplierType?: CounterpartyLegalType | string,
  buyerType?: CounterpartyLegalType | string,
) => {
  if (isSupplyLegalEntitiesTemplate(template)) {
    return isLegalEntityOrIpType(supplierType) && isLegalEntityOrIpType(buyerType);
  }
  if (isPrivatePersonGoodsSaleTemplate(template)) {
    return (supplierType === 'ip' || supplierType === 'person') && buyerType === 'person';
  }
  return true;
};

const normalizeBankAccount = (value?: Partial<BankAccount> | null) => ({
  bankName: String(value?.bankName || '').trim(),
  checkingAccount: String(value?.checkingAccount || '').trim(),
  correspondentAccount: String(value?.correspondentAccount || '').trim(),
  bik: String(value?.bik || '').trim(),
});

const hasBankAccountValues = (value?: { bankName?: string; checkingAccount?: string; correspondentAccount?: string; bik?: string }) =>
  Boolean(value?.bankName || value?.checkingAccount || value?.correspondentAccount || value?.bik);

const isCounterpartyCompanyType = (legalType: CounterpartyLegalType) => legalType === 'ooo' || legalType === 'ao';
const isLegalEntityOrIpType = (legalType?: CounterpartyLegalType | string) =>
  legalType === 'ooo' || legalType === 'ao' || legalType === 'ip';
const stripIpPrefix = (value?: string) => String(value || '').trim().replace(/^ип\s+/iu, '');

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

const resolveSupplierProfiles = (settings: AppSettings | null) => {
  if (!settings) {
    return [];
  }

  if (Array.isArray(settings.companyProfiles) && settings.companyProfiles.length > 0) {
    return settings.companyProfiles;
  }

  return [
    {
      id: 'company-legacy',
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

const resolveSupplierBankAccounts = (settings: AppSettings | null, supplierProfileId: string) => {
  if (!settings) {
    return [];
  }

  const profiles = resolveSupplierProfiles(settings);
  const selectedProfile =
    profiles.find((profile) => profile.id === supplierProfileId) ||
    profiles.find((profile) => profile.id === settings.activeCompanyProfileId) ||
    profiles[0];

  const sourceAccounts =
    Array.isArray(selectedProfile?.bankAccounts) && selectedProfile.bankAccounts.length > 0
      ? selectedProfile.bankAccounts
      : Array.isArray(settings.bankAccounts) && settings.bankAccounts.length > 0
        ? settings.bankAccounts
        : [
            {
              bankName: settings.bankName,
              checkingAccount: settings.checkingAccount,
              correspondentAccount: settings.correspondentAccount,
              bik: settings.bik,
            },
          ];

  return sourceAccounts.map((account) => normalizeBankAccount(account)).filter(hasBankAccountValues);
};

const getPrimarySupplierPaymentSource = (supplier?: SupplierCompanyProfile | null) => {
  const profile = supplier || null;
  if (!profile) {
    return null;
  }

  const firstBankAccount = Array.isArray(profile.bankAccounts) && profile.bankAccounts.length > 0 ? profile.bankAccounts[0] : null;
  return {
    bankName: String(firstBankAccount?.bankName || profile.bankName || '').trim(),
    checkingAccount: String(firstBankAccount?.checkingAccount || profile.checkingAccount || '').trim(),
    correspondentAccount: String(firstBankAccount?.correspondentAccount || profile.correspondentAccount || '').trim(),
    bik: String(firstBankAccount?.bik || profile.bik || '').trim(),
    cardNumber: String(firstBankAccount?.cardNumber || profile.cardNumber || '').trim(),
    sbpPhone: String(firstBankAccount?.sbpPhone || profile.sbpPhone || profile.phone || '').trim(),
  };
};

const hasSellerPersonAnyPaymentMethod = (supplier?: SupplierCompanyProfile | null): boolean => {
  const payment = getPrimarySupplierPaymentSource(supplier);
  if (!payment) {
    return false;
  }

  const hasBankRequisites = Boolean(
    payment.bankName && payment.checkingAccount && payment.correspondentAccount && payment.bik,
  );

  return Boolean(payment.cardNumber || payment.sbpPhone || hasBankRequisites);
};

const getGoodsSaleTemplateMissingFields = ({
  selectedSupplierProfile,
  buyer,
  formData,
  vatRate,
}: {
  selectedSupplierProfile?: SupplierCompanyProfile | null;
  buyer: PrivateBuyerRfDraft;
  formData: WizardFormData;
  vatRate: VatRate;
}): string[] => {
  const missing: string[] = [];
  const supplier = selectedSupplierProfile || null;

  if (!supplier) {
    missing.push('Профиль продавца: выберите/настройте активный профиль компании');
    return missing;
  }

  if (supplier.legalType !== 'ip' && supplier.legalType !== 'person') {
    missing.push('Профиль продавца: для этого шаблона используйте профиль типа ИП или Физлицо (РФ)');
  }
  if (supplier.legalType === 'ip') {
    if (!String(supplier.inn || '').trim()) {
      missing.push('Профиль продавца (ИП): ИНН');
    }
    if (!String(supplier.ogrnip || '').trim()) {
      missing.push('Профиль продавца (ИП): ОГРНИП');
    }
  }
  if (supplier.legalType === 'person') {
    if (!String(supplier.companyName || '').trim()) {
      missing.push('Профиль продавца (физлицо): ФИО');
    }
    if (!String(supplier.passportSeries || '').trim() || !String(supplier.passportNumber || '').trim()) {
      missing.push('Профиль продавца (физлицо): серия и номер паспорта');
    }
  }
  if (!String(supplier.legalAddress || supplier.registrationAddress || supplier.residenceAddress || '').trim()) {
    missing.push('Профиль продавца: адрес');
  }
  if (!String(supplier.phone || '').trim()) {
    missing.push('Профиль продавца: телефон');
  }
  if (supplier.legalType !== 'person' && !String(supplier.bankName || '').trim()) {
    missing.push('Профиль продавца: банк');
  }
  if (supplier.legalType !== 'person' && !String(supplier.checkingAccount || '').trim()) {
    missing.push('Профиль продавца: расчетный счет');
  }
  if (supplier.legalType !== 'person' && !String(supplier.bik || '').trim()) {
    missing.push('Профиль продавца: БИК');
  }
  if (supplier.legalType !== 'person' && !String(supplier.correspondentAccount || '').trim()) {
    missing.push('Профиль продавца: корреспондентский счет');
  }
  if (supplier.legalType === 'person' && !hasSellerPersonAnyPaymentMethod(supplier)) {
    missing.push('Профиль продавца (физлицо): укажите минимум один способ оплаты (карта, СБП или полные банковские реквизиты)');
  }

  if (!buyer.phone.trim()) {
    missing.push('Покупатель: телефон');
  }

  if (!formData.signingCity.trim()) {
    missing.push('Шаблон: город подписания');
  }
  if (!formData.deliveryCity.trim()) {
    missing.push('Шаблон: город доставки');
  }
  if (!formData.deliveryTermDays.trim()) {
    missing.push('Шаблон: срок поставки (дни)');
  }
  if (!formData.deliveryTermBasis.trim()) {
    missing.push('Шаблон: основание отсчета срока поставки');
  }
  if (!formData.deliveryCostPayer) {
    missing.push('Шаблон: кто оплачивает доставку');
  }
  if (!formData.deliveryMethod.trim()) {
    missing.push('Шаблон: способ доставки');
  }
  if (!formData.confidentialityPenaltyAmount.trim()) {
    missing.push('Шаблон: размер штрафа по конфиденциальности');
  }
  if (vatRate === 'none' && supplier.legalType !== 'person' && !formData.supplierTaxBasis.trim()) {
    missing.push('Шаблон: основание/режим без НДС');
  }

  return missing;
};

const mapCounterpartyToDraft = (counterparty: Counterparty): CounterpartyDraft => ({
  legalType:
    counterparty.legalType === 'ip' ||
    counterparty.legalType === 'ooo' ||
    counterparty.legalType === 'ao' ||
    counterparty.legalType === 'person'
      ? counterparty.legalType
      : 'ooo',
  inn: counterparty.inn || '',
  name: counterparty.name || '',
  kpp: counterparty.kpp || '',
  address: counterparty.address || '',
  contactPerson: counterparty.contactPerson || '',
  email: counterparty.email || '',
  directorName: counterparty.directorName || '',
  ogrn: counterparty.ogrn || '',
  ogrnip: counterparty.ogrnip || '',
  bankName: counterparty.bankName || '',
  bik: counterparty.bik || '',
  checkingAccount: counterparty.checkingAccount || '',
  correspondentAccount: counterparty.correspondentAccount || '',
});

const draftCounterpartyToEntity = (draft: CounterpartyDraft): Counterparty => ({
  id: 'wizard-draft-counterparty',
  legalType: draft.legalType,
  name: draft.name.trim(),
  inn: draft.inn.trim(),
  kpp: draft.kpp.trim(),
  address: draft.address.trim(),
  contactPerson: draft.contactPerson.trim(),
  email: draft.email.trim(),
  directorName: draft.directorName.trim(),
  ogrn: draft.ogrn.trim(),
  ogrnip: draft.ogrnip.trim(),
  bankName: draft.bankName.trim(),
  bik: draft.bik.trim(),
  checkingAccount: draft.checkingAccount.trim(),
  correspondentAccount: draft.correspondentAccount.trim(),
  bankAccounts: [
    {
      bankName: draft.bankName.trim(),
      bik: draft.bik.trim(),
      checkingAccount: draft.checkingAccount.trim(),
      correspondentAccount: draft.correspondentAccount.trim(),
    },
  ],
});

const normalizeDraftInvoiceItems = (items: InvoiceItemDraft[]): InvoiceItem[] =>
  items
    .map((item) => {
      const quantity = Number(item.quantity || 0);
      const price = Number(item.price || 0);
      return {
        id: item.id,
        description: String(item.description || '').trim(),
        quantity: Number.isFinite(quantity) ? quantity : 0,
        price: Number.isFinite(price) ? price : 0,
        unit: String(item.unit || 'шт').trim() || 'шт',
      };
    })
    .filter((item) => item.description.length > 0 || item.quantity > 0 || item.price > 0);

const validateLineItems = (items: InvoiceItem[]) => {
  if (items.length === 0) {
    return 'Добавьте минимум одну позицию.';
  }

  for (let index = 0; index < items.length; index += 1) {
    const item = items[index];
    if (!item.description.trim()) {
      return `Заполните наименование позиции №${index + 1}.`;
    }
    if (!Number.isFinite(item.quantity) || item.quantity <= 0) {
      return `Количество в позиции №${index + 1} должно быть больше 0.`;
    }
    if (!Number.isFinite(item.price) || item.price < 0) {
      return `Цена в позиции №${index + 1} должна быть неотрицательной.`;
    }
  }

  return null;
};

export const ContractWizard: React.FC<WizardProps> = ({
  onCancel,
  onFinish,
  counterparties,
  invoices,
  initialInvoiceId,
  templates,
  settings,
  onContractCreated,
}) => {
  const [step, setStep] = useState(1);
  const [stepError, setStepError] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isInnLookupLoading, setIsInnLookupLoading] = useState(false);
  const [innLookupMessage, setInnLookupMessage] = useState<string | null>(null);
  const [createdContract, setCreatedContract] = useState<Contract | null>(null);
  const [createdInvoice, setCreatedInvoice] = useState<Invoice | null>(null);
  const [createdCounterparty, setCreatedCounterparty] = useState<Counterparty | null>(null);
  const [useExistingCounterparty, setUseExistingCounterparty] = useState(false);
  const [liveTemplatePreview, setLiveTemplatePreview] = useState<{ html: string; css: string; templateId: string } | null>(null);
  const [isLiveTemplatePreviewLoading, setIsLiveTemplatePreviewLoading] = useState(false);
  const [liveTemplatePreviewError, setLiveTemplatePreviewError] = useState<string | null>(null);
  const liveTemplatePreviewRequestIdRef = useRef(0);

  const [formData, setFormData] = useState<WizardFormData>({
    type: ContractType.SUPPLY,
    templateId: '',
    counterpartyId: '',
    paymentTerms: '10',
    includeDelivery: true,
    deliveryDate: '',
    number: `Д-${new Date().getFullYear()}-${String(Math.floor(Math.random() * 1000)).padStart(3, '0')}`,
    hasPrepayment: true,
    prepaymentPercent: '100',
    paymentMode: 'full_prepayment',
    customPaymentTerms: '',
    penaltyPercentPerDay: '0.1',
    signingCity: '',
    deliveryCity: '',
    deliveryTermDays: '35',
    deliveryTermBasis: 'с даты поступления полной оплаты',
    deliveryCostPayer: 'seller',
    deliveryMethod: 'ТК/курьер по согласованию Сторон',
    purchasePurpose: 'business',
    supplierTaxBasis: 'УСН, без НДС',
    confidentialityPenaltyAmount: '30000',
    supplierSignerPosition: '',
    supplierSignerName: '',
    supplierSignerBasis: '',
    buyerSignerPosition: '',
    buyerSignerName: '',
    buyerSignerBasis: '',
  });

  const [counterpartyDraft, setCounterpartyDraft] = useState<CounterpartyDraft>(createInitialCounterpartyDraft);
  const [invoiceDraft, setInvoiceDraft] = useState<InvoiceDraft>(createInitialInvoiceDraft);
  const [privateBuyerRfDraft, setPrivateBuyerRfDraft] = useState<PrivateBuyerRfDraft>(createInitialPrivateBuyerRfDraft);

  const supplierProfiles = useMemo(() => resolveSupplierProfiles(settings), [settings]);
  const selectedSupplierProfileId = useMemo(() => {
    if (supplierProfiles.length === 0) {
      return '';
    }

    if (supplierProfiles.some((profile) => profile.id === invoiceDraft.supplierProfileId)) {
      return invoiceDraft.supplierProfileId;
    }

    return settings?.activeCompanyProfileId || supplierProfiles[0].id;
  }, [invoiceDraft.supplierProfileId, settings?.activeCompanyProfileId, supplierProfiles]);
  const supplierBankAccounts = useMemo(
    () => resolveSupplierBankAccounts(settings, selectedSupplierProfileId),
    [selectedSupplierProfileId, settings],
  );
  const selectedSupplierProfile = useMemo(
    () =>
      supplierProfiles.find((profile) => profile.id === selectedSupplierProfileId) ||
      supplierProfiles.find((profile) => profile.id === settings?.activeCompanyProfileId) ||
      supplierProfiles[0] ||
      null,
    [selectedSupplierProfileId, settings?.activeCompanyProfileId, supplierProfiles],
  );
  const legalTemplateSupplierProfiles = useMemo(
    () => supplierProfiles.filter((profile) => isLegalEntityOrIpType(profile.legalType)),
    [supplierProfiles],
  );
  const isSelectedGoodsSaleSellerPerson = useMemo(
    () => selectedSupplierProfile?.legalType === 'person',
    [selectedSupplierProfile],
  );
  const selectedSupplierBankAccount = useMemo(() => {
    if (supplierBankAccounts.length === 0) {
      return undefined;
    }

    const selectedIndex = Number(invoiceDraft.supplierBankAccountKey);
    if (Number.isFinite(selectedIndex) && selectedIndex >= 0 && selectedIndex < supplierBankAccounts.length) {
      return supplierBankAccounts[selectedIndex];
    }

    return supplierBankAccounts[0];
  }, [invoiceDraft.supplierBankAccountKey, supplierBankAccounts]);

  const selectedExistingCounterparty = useMemo(
    () => counterparties.find((counterparty) => counterparty.id === formData.counterpartyId),
    [counterparties, formData.counterpartyId],
  );
  useEffect(() => {
    if (!useExistingCounterparty || !selectedExistingCounterparty) {
      return;
    }

    // Keep draft fields in sync with selected counterparty.
    setCounterpartyDraft(mapCounterpartyToDraft(selectedExistingCounterparty));
  }, [selectedExistingCounterparty, useExistingCounterparty]);
  const selectedBuyerType = useMemo<CounterpartyLegalType | undefined>(() => {
    if (useExistingCounterparty && selectedExistingCounterparty) {
      return selectedExistingCounterparty.legalType;
    }
    return counterpartyDraft.legalType;
  }, [counterpartyDraft.legalType, selectedExistingCounterparty, useExistingCounterparty]);
  const initialInvoice = useMemo(
    () => (initialInvoiceId ? invoices.find((invoice) => invoice.id === initialInvoiceId) || null : null),
    [initialInvoiceId, invoices],
  );
  const isInitialInvoiceLinked = Boolean(initialInvoiceId && createdInvoice?.id === initialInvoiceId);

  useEffect(() => {
    if (!initialInvoice) {
      return;
    }

    setCreatedInvoice(initialInvoice);
    setUseExistingCounterparty(true);
    setInvoiceDraft((prev) => ({
      ...prev,
      date: ruToIsoDate(initialInvoice.date) || prev.date,
      paymentDueDate: initialInvoice.paymentDueDate ? ruToIsoDate(initialInvoice.paymentDueDate) : '',
      commissionPercent: String(initialInvoice.commissionPercent ?? 0),
      currency: initialInvoice.currency || prev.currency,
      vatRate: initialInvoice.vatRate || prev.vatRate,
      vatMode: initialInvoice.vatMode || prev.vatMode,
      supplierProfileId: initialInvoice.supplierProfileId || prev.supplierProfileId,
      items:
        initialInvoice.items?.length > 0
          ? initialInvoice.items.map((item) => ({
              id: `wizard-item-${item.id}`,
              description: item.description || '',
              quantity: String(item.quantity ?? ''),
              unit: item.unit || 'шт',
              price: String(item.price ?? ''),
            }))
          : prev.items,
    }));

    if (initialInvoice.counterpartyId) {
      const linkedCounterparty = counterparties.find((counterparty) => counterparty.id === initialInvoice.counterpartyId);
      if (linkedCounterparty) {
        setCreatedCounterparty(linkedCounterparty);
        setFormData((prev) => ({ ...prev, counterpartyId: linkedCounterparty.id }));
      }
    }
  }, [counterparties, initialInvoice]);

  const activeTemplates = useMemo(() => templates.filter((template) => template.isActive), [templates]);
  const templateOptions = useMemo(
    () =>
      activeTemplates.filter((template) =>
        isTemplateCompatibleForParties(template, selectedSupplierProfile?.legalType, selectedBuyerType),
      ),
    [activeTemplates, selectedBuyerType, selectedSupplierProfile?.legalType],
  );
  const selectedTemplate = useMemo(
    () => templates.find((template) => template.id === formData.templateId) || null,
    [formData.templateId, templates],
  );
  const isPrivatePersonSaleContract = useMemo(() => isPrivatePersonGoodsSaleTemplate(selectedTemplate), [selectedTemplate]);
  const isSupplyLegalEntitiesContract = useMemo(() => isSupplyLegalEntitiesTemplate(selectedTemplate), [selectedTemplate]);
  const paymentConfig = useMemo(() => {
    const rawPercent = Number(formData.prepaymentPercent || 0);
    const normalizedPercent = Number.isFinite(rawPercent) ? Math.min(100, Math.max(0, rawPercent)) : 0;
    if (isSupplyLegalEntitiesContract) {
      if (formData.paymentMode === 'custom') {
        return {
          hasPrepayment: false,
          prepaymentPercent: 0,
          customPaymentTerms: formData.customPaymentTerms.trim(),
        };
      }
      if (formData.paymentMode === 'partial_prepayment') {
        return {
          hasPrepayment: true,
          prepaymentPercent: normalizedPercent,
          customPaymentTerms: '',
        };
      }
      return {
        hasPrepayment: true,
        prepaymentPercent: 100,
        customPaymentTerms: '',
      };
    }
    return {
      hasPrepayment: formData.hasPrepayment,
      prepaymentPercent: normalizedPercent,
      customPaymentTerms: '',
    };
  }, [
    formData.customPaymentTerms,
    formData.hasPrepayment,
    formData.paymentMode,
    formData.prepaymentPercent,
    isSupplyLegalEntitiesContract,
  ]);
  const normalizedPrivateBuyer = useMemo(() => normalizePrivateBuyerRfDraft(privateBuyerRfDraft), [privateBuyerRfDraft]);
  const isPersonNoInvoiceMode = useMemo(
    () => isPrivatePersonSaleContract && counterpartyDraft.legalType === 'person',
    [counterpartyDraft.legalType, isPrivatePersonSaleContract],
  );

  useEffect(() => {
    if (templateOptions.length === 0) {
      if (formData.templateId) {
        setFormData((prev) => ({ ...prev, templateId: '' }));
      }
      return;
    }

    const hasTemplate = templateOptions.some((template) => template.id === formData.templateId);
    if (!hasTemplate) {
      setFormData((prev) => ({ ...prev, templateId: templateOptions[0].id }));
    }
  }, [formData.templateId, templateOptions]);

  useEffect(() => {
    // Rebuild contract snapshot on next export if user changed template in the wizard.
    setCreatedContract(null);
  }, [formData.templateId]);

  useEffect(() => {
    if (supplierProfiles.length === 0) {
      return;
    }

    const hasValidSelection = supplierProfiles.some((profile) => profile.id === invoiceDraft.supplierProfileId);
    if (!hasValidSelection) {
      setInvoiceDraft((prev) => ({
        ...prev,
        supplierProfileId: settings?.activeCompanyProfileId || supplierProfiles[0].id,
        supplierBankAccountKey: '0',
      }));
    }
  }, [invoiceDraft.supplierProfileId, settings?.activeCompanyProfileId, supplierProfiles]);

  useEffect(() => {
    if (supplierBankAccounts.length === 0) {
      return;
    }

    const selectedIndex = Number(invoiceDraft.supplierBankAccountKey);
    const hasValidSelection = Number.isFinite(selectedIndex) && selectedIndex >= 0 && selectedIndex < supplierBankAccounts.length;
    if (!hasValidSelection) {
      setInvoiceDraft((prev) => ({ ...prev, supplierBankAccountKey: '0' }));
    }
  }, [invoiceDraft.supplierBankAccountKey, supplierBankAccounts]);

  useEffect(() => {
    if (!isSupplyLegalEntitiesContract) {
      return;
    }
    if (!selectedSupplierProfile || selectedSupplierProfile.legalType !== 'person') {
      return;
    }
    const fallbackProfile = legalTemplateSupplierProfiles[0];
    if (!fallbackProfile || fallbackProfile.id === selectedSupplierProfileId) {
      return;
    }
    setInvoiceDraft((prev) => ({
      ...prev,
      supplierProfileId: fallbackProfile.id,
      supplierBankAccountKey: '0',
    }));
  }, [
    isSupplyLegalEntitiesContract,
    legalTemplateSupplierProfiles,
    selectedSupplierProfile,
    selectedSupplierProfileId,
  ]);

  useEffect(() => {
    if (isPersonNoInvoiceMode && step === 2) {
      setStep(3);
      setStepError(null);
    }
  }, [isPersonNoInvoiceMode, step]);

  const invoiceItems = useMemo(() => normalizeDraftInvoiceItems(invoiceDraft.items), [invoiceDraft.items]);

  const invoiceCommissionPercent = useMemo(() => {
    const parsed = Number(invoiceDraft.commissionPercent || 0);
    if (!Number.isFinite(parsed) || parsed < 0) {
      return 0;
    }
    return parsed;
  }, [invoiceDraft.commissionPercent]);
  const effectiveInvoiceCommissionPercent = isPersonNoInvoiceMode ? 0 : invoiceCommissionPercent;

  const previewCounterparty = useMemo(() => {
    if (useExistingCounterparty && selectedExistingCounterparty) {
      return selectedExistingCounterparty;
    }

    if (isPersonNoInvoiceMode) {
      const buyerName = normalizedPrivateBuyer.fullName.trim();
      const registrationAddress = normalizedPrivateBuyer.registrationAddress.trim();
      const residenceAddress = normalizedPrivateBuyer.residenceAddress.trim();
      const primaryAddress = registrationAddress || residenceAddress;
      if (!buyerName && !primaryAddress) {
        return undefined;
      }

      return {
        id: 'wizard-draft-counterparty',
        legalType: 'person' as CounterpartyLegalType,
        name: buyerName,
        inn: '',
        address: primaryAddress,
        contactPerson: counterpartyDraft.contactPerson.trim() || buyerName,
        email: normalizedPrivateBuyer.email,
        phone: normalizedPrivateBuyer.phone,
        passportSeries: normalizedPrivateBuyer.passportSeries,
        passportNumber: normalizedPrivateBuyer.passportNumber,
        passportIssuedBy: normalizedPrivateBuyer.passportIssuedBy,
        passportIssuedDate: normalizedPrivateBuyer.passportIssuedDate,
        passportDepartmentCode: normalizedPrivateBuyer.passportDepartmentCode,
        registrationAddress,
        residenceAddress,
      } as Counterparty;
    }

    if (!counterpartyDraft.name.trim() && !counterpartyDraft.inn.trim()) {
      return undefined;
    }

    return draftCounterpartyToEntity(counterpartyDraft);
  }, [counterpartyDraft, isPersonNoInvoiceMode, normalizedPrivateBuyer, selectedExistingCounterparty, useExistingCounterparty]);
  const defaultSupplierSigner = useMemo(() => {
    const supplierType = selectedSupplierProfile?.legalType;
    if (supplierType === 'ip') {
      return {
        position: 'индивидуальный предприниматель',
        name: stripIpPrefix(selectedSupplierProfile?.companyName),
        basis: 'свидетельства о государственной регистрации в качестве ИП',
      };
    }
    return {
      position: 'директор',
      name: String(selectedSupplierProfile?.directorName || selectedSupplierProfile?.directorGenitive || '').trim(),
      basis: 'Устава',
    };
  }, [selectedSupplierProfile]);
  const defaultBuyerSigner = useMemo(() => {
    const buyerType = previewCounterparty?.legalType;
    return {
      position: buyerType === 'ip' ? 'индивидуальный предприниматель' : 'директор',
      name: String(previewCounterparty?.directorName || previewCounterparty?.contactPerson || previewCounterparty?.name || '').trim(),
      basis: buyerType === 'ip' ? 'свидетельства о государственной регистрации в качестве ИП' : 'Устава',
    };
  }, [previewCounterparty]);

  useEffect(() => {
    if (!isSupplyLegalEntitiesContract) {
      return;
    }
    setFormData((prev) => ({
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
    isSupplyLegalEntitiesContract,
  ]);

  const draftInvoiceAmount = useMemo(
    () => invoiceItems.reduce((sum, item) => sum + Number(item.quantity || 0) * Number(item.price || 0), 0),
    [invoiceItems],
  );
  const previewPersistedInvoice = isPersonNoInvoiceMode ? null : createdInvoice;

  const previewInvoice = useMemo<Invoice>(
    () => ({
      id: previewPersistedInvoice?.id || 'wizard-draft-invoice',
      number: previewPersistedInvoice?.number || 'Авто',
      date: previewPersistedInvoice?.date || isoToRuDate(invoiceDraft.date) || todayIsoDate(),
      paymentDueDate:
        previewPersistedInvoice?.paymentDueDate || (invoiceDraft.paymentDueDate ? isoToRuDate(invoiceDraft.paymentDueDate) : undefined),
      amount: previewPersistedInvoice?.amount ?? draftInvoiceAmount,
      currency: invoiceDraft.currency || 'RUB',
      items: previewPersistedInvoice?.items || invoiceItems,
      status: previewPersistedInvoice?.status || 'Не оплачен',
      counterpartyId: previewPersistedInvoice?.counterpartyId || formData.counterpartyId || undefined,
      commissionPercent: isPersonNoInvoiceMode ? 0 : previewPersistedInvoice?.commissionPercent ?? invoiceCommissionPercent,
      vatRate: isPersonNoInvoiceMode ? 'none' : previewPersistedInvoice?.vatRate || invoiceDraft.vatRate,
      vatMode: isPersonNoInvoiceMode ? 'included' : previewPersistedInvoice?.vatMode || invoiceDraft.vatMode,
      supplierProfileId: previewPersistedInvoice?.supplierProfileId || selectedSupplierProfileId || undefined,
      supplierBankAccount: previewPersistedInvoice?.supplierBankAccount || selectedSupplierBankAccount,
    }),
    [
      draftInvoiceAmount,
      formData.counterpartyId,
      invoiceCommissionPercent,
      invoiceDraft.currency,
      invoiceDraft.date,
      invoiceDraft.paymentDueDate,
      invoiceDraft.vatMode,
      invoiceDraft.vatRate,
      invoiceItems,
      isPersonNoInvoiceMode,
      previewPersistedInvoice,
      selectedSupplierProfileId,
      selectedSupplierBankAccount,
    ],
  );

  const pricingConfig = useMemo(
    () =>
      normalizePricingConfig({
        vatRate: previewInvoice.vatRate,
        vatMode: previewInvoice.vatMode,
        markupMode: 'per_item',
        markupCalcMode: 'simple',
        markupPercent: effectiveInvoiceCommissionPercent,
      }),
    [effectiveInvoiceCommissionPercent, previewInvoice.vatMode, previewInvoice.vatRate],
  );

  const pricingPreview = useMemo(() => buildInvoicePricing(previewInvoice, pricingConfig), [previewInvoice, pricingConfig]);
  const goodsSaleTemplateMissingFields = useMemo(
    () =>
      isPrivatePersonSaleContract
        ? getGoodsSaleTemplateMissingFields({
            selectedSupplierProfile,
            buyer: normalizedPrivateBuyer,
            formData,
            vatRate: previewInvoice.vatRate,
          })
        : [],
    [formData, isPrivatePersonSaleContract, normalizedPrivateBuyer, previewInvoice.vatRate, selectedSupplierProfile],
  );

  const vatSummaryLabel =
    pricingConfig.vatRate === 'none'
      ? 'НДС'
      : pricingConfig.vatRate === '0'
        ? 'НДС 0%'
        : pricingConfig.vatMode === 'included'
          ? `В т.ч. НДС ${pricingConfig.vatRate}%`
          : `НДС ${pricingConfig.vatRate}% сверху`;
  const wizardContractSnapshotHtml = createdContract?.htmlSnapshot?.trim();
  const wizardContractSnapshotCss = createdContract?.snapshotCss?.trim();
  const wizardContractPreviewHtml = liveTemplatePreview?.html?.trim() || wizardContractSnapshotHtml || '';
  const wizardContractPreviewCss = liveTemplatePreview?.css?.trim() || wizardContractSnapshotCss || '';
  const shouldRenderWizardContractSnapshot = Boolean(wizardContractPreviewHtml);

  const invoiceDocument = useMemo(
    () =>
      buildInvoiceDocument({
        invoice: previewInvoice,
        counterparty: previewCounterparty,
        settings,
        logoSrc: INVOICE_LOGO_URL,
      }),
    [previewCounterparty, previewInvoice, settings],
  );

  useEffect(() => {
    if (!selectedTemplate || !formData.templateId) {
      setLiveTemplatePreview(null);
      setLiveTemplatePreviewError(null);
      setIsLiveTemplatePreviewLoading(false);
      return;
    }

    const requestId = ++liveTemplatePreviewRequestIdRef.current;
    const timerId = window.setTimeout(async () => {
      setIsLiveTemplatePreviewLoading(true);
      setLiveTemplatePreviewError(null);

      try {
        const preview = await api.previewContractTemplate({
          type: formData.type,
          templateId: formData.templateId || undefined,
          number: formData.number || undefined,
          amount: pricingPreview.total,
          paymentTerms: Number(formData.paymentTerms || 10),
          includeDelivery: formData.includeDelivery,
          deliveryDate: formData.includeDelivery && formData.deliveryDate ? isoToRuDate(formData.deliveryDate) : null,
          vatRate: previewInvoice.vatRate,
          vatMode: previewInvoice.vatMode,
          markupPercent: isPersonNoInvoiceMode ? 0 : invoiceCommissionPercent,
          markupMode: 'per_item',
          markupCalcMode: 'simple',
          contractData: {
            hasPrepayment: paymentConfig.hasPrepayment,
            prepaymentPercent: paymentConfig.prepaymentPercent,
            customPaymentTerms: paymentConfig.customPaymentTerms || undefined,
            penaltyPercentPerDay: Number(formData.penaltyPercentPerDay || 0),
            contractScenario: isPrivatePersonSaleContract
              ? 'private_person_goods_sale'
              : isSupplyLegalEntitiesContract
                ? 'supply_legal_entities'
                : 'default',
            supplierSignerPosition: isSupplyLegalEntitiesContract ? formData.supplierSignerPosition.trim() || undefined : undefined,
            supplierSignerName: isSupplyLegalEntitiesContract ? formData.supplierSignerName.trim() || undefined : undefined,
            supplierSignerBasis: isSupplyLegalEntitiesContract ? formData.supplierSignerBasis.trim() || undefined : undefined,
            buyerSignerPosition: isSupplyLegalEntitiesContract ? formData.buyerSignerPosition.trim() || undefined : undefined,
            buyerSignerName: isSupplyLegalEntitiesContract ? formData.buyerSignerName.trim() || undefined : undefined,
            buyerSignerBasis: isSupplyLegalEntitiesContract ? formData.buyerSignerBasis.trim() || undefined : undefined,
            privateBuyerRf: isPrivatePersonSaleContract ? normalizedPrivateBuyer : undefined,
            contractItems: invoiceItems.map((item) => ({
              id: item.id,
              description: item.description,
              quantity: item.quantity,
              price: item.price,
              unit: item.unit,
            })),
            signingCity: formData.signingCity.trim() || undefined,
            deliveryCity: formData.deliveryCity.trim() || undefined,
            deliveryTermDays:
              Number.isFinite(Number(formData.deliveryTermDays)) && Number(formData.deliveryTermDays) > 0
                ? Number(formData.deliveryTermDays)
                : undefined,
            deliveryTermBasis: formData.deliveryTermBasis.trim() || undefined,
            deliveryCostPayer: isSupplyLegalEntitiesContract ? 'buyer' : formData.deliveryCostPayer || undefined,
            deliveryMethod: formData.deliveryMethod.trim() || undefined,
            purchasePurpose: formData.purchasePurpose,
            supplierTaxBasis:
              previewInvoice.vatRate === 'none' && selectedSupplierProfile?.legalType !== 'person'
                ? formData.supplierTaxBasis.trim() || undefined
                : undefined,
            confidentialityPenaltyAmount:
              Number.isFinite(Number(formData.confidentialityPenaltyAmount)) && Number(formData.confidentialityPenaltyAmount) >= 0
                ? Number(formData.confidentialityPenaltyAmount)
                : undefined,
          },
          counterparty: previewCounterparty || null,
          invoice: previewInvoice,
        });

        if (liveTemplatePreviewRequestIdRef.current !== requestId) {
          return;
        }

        setLiveTemplatePreview({
          html: preview.html,
          css: preview.css,
          templateId: preview.templateId,
        });
      } catch (error) {
        if (liveTemplatePreviewRequestIdRef.current !== requestId) {
          return;
        }
        setLiveTemplatePreviewError(error instanceof Error ? error.message : 'Не удалось построить live-preview шаблона.');
      } finally {
        if (liveTemplatePreviewRequestIdRef.current === requestId) {
          setIsLiveTemplatePreviewLoading(false);
        }
      }
    }, 250);

    return () => {
      window.clearTimeout(timerId);
    };
  }, [
    formData.confidentialityPenaltyAmount,
    formData.deliveryCity,
    formData.deliveryDate,
    formData.deliveryCostPayer,
    formData.deliveryMethod,
    formData.deliveryTermBasis,
    formData.deliveryTermDays,
    formData.customPaymentTerms,
    formData.hasPrepayment,
    formData.includeDelivery,
    formData.number,
    formData.paymentTerms,
    formData.penaltyPercentPerDay,
    formData.paymentMode,
    formData.prepaymentPercent,
    formData.purchasePurpose,
    formData.buyerSignerBasis,
    formData.buyerSignerName,
    formData.buyerSignerPosition,
    formData.signingCity,
    formData.supplierSignerBasis,
    formData.supplierSignerName,
    formData.supplierSignerPosition,
    formData.supplierTaxBasis,
    formData.templateId,
    formData.type,
    invoiceCommissionPercent,
    isPersonNoInvoiceMode,
    isPrivatePersonSaleContract,
    isSupplyLegalEntitiesContract,
    normalizedPrivateBuyer,
    previewCounterparty,
    previewInvoice,
    pricingPreview.total,
    paymentConfig.customPaymentTerms,
    paymentConfig.hasPrepayment,
    paymentConfig.prepaymentPercent,
    selectedSupplierProfile,
    selectedTemplate,
  ]);

  const visibleWizardSteps = useMemo(
    () => (isPersonNoInvoiceMode ? WIZARD_STEPS.filter((stepItem) => stepItem.num !== 2) : WIZARD_STEPS),
    [isPersonNoInvoiceMode],
  );
  const currentStepIndex = visibleWizardSteps.findIndex((stepItem) => stepItem.num === step);
  const currentStepMeta =
    (currentStepIndex >= 0 ? visibleWizardSteps[currentStepIndex] : undefined) || visibleWizardSteps[0] || WIZARD_STEPS[0];
  const nextStepMeta = currentStepIndex >= 0 ? visibleWizardSteps[currentStepIndex + 1] : undefined;
  const counterpartyLocked = useExistingCounterparty && Boolean(formData.counterpartyId);
  const getNextStepNumber = (currentStepNumber: number) => {
    const currentIndex = visibleWizardSteps.findIndex((stepItem) => stepItem.num === currentStepNumber);
    if (currentIndex < 0) {
      return currentStepNumber;
    }
    return visibleWizardSteps[currentIndex + 1]?.num ?? currentStepNumber;
  };
  const getPrevStepNumber = (currentStepNumber: number) => {
    const currentIndex = visibleWizardSteps.findIndex((stepItem) => stepItem.num === currentStepNumber);
    if (currentIndex < 0) {
      return currentStepNumber;
    }
    return visibleWizardSteps[currentIndex - 1]?.num ?? currentStepNumber;
  };

  const updateCounterpartyDraft = (patch: Partial<CounterpartyDraft>) => {
    setCounterpartyDraft((prev) => ({ ...prev, ...patch }));
    if (counterpartyLocked) {
      setUseExistingCounterparty(false);
      setFormData((prev) => ({ ...prev, counterpartyId: '' }));
    }
  };

  const handleSelectExistingCounterparty = (counterpartyId: string) => {
    if (!counterpartyId) {
      setFormData((prev) => ({ ...prev, counterpartyId: '' }));
      setUseExistingCounterparty(false);
      return;
    }

    const counterparty = counterparties.find((item) => item.id === counterpartyId);
    if (!counterparty) {
      return;
    }

    setFormData((prev) => ({ ...prev, counterpartyId: counterparty.id }));
    setCounterpartyDraft(mapCounterpartyToDraft(counterparty));
    if (counterparty.legalType === 'person') {
      setPrivateBuyerRfDraft((prev) =>
        normalizePrivateBuyerRfDraft({
          ...prev,
          fullName: counterparty.name || prev.fullName,
          passportSeries: counterparty.passportSeries || prev.passportSeries,
          passportNumber: counterparty.passportNumber || prev.passportNumber,
          passportIssuedBy: counterparty.passportIssuedBy || prev.passportIssuedBy,
          passportIssuedDate: counterparty.passportIssuedDate || prev.passportIssuedDate,
          passportDepartmentCode: counterparty.passportDepartmentCode || prev.passportDepartmentCode,
          registrationAddress: counterparty.registrationAddress || counterparty.address || prev.registrationAddress,
          residenceAddress: counterparty.residenceAddress || prev.residenceAddress,
          phone: counterparty.phone || prev.phone,
          email: counterparty.email || prev.email,
        }),
      );
    }
    setUseExistingCounterparty(true);
    setInnLookupMessage('Контрагент выбран из базы.');
  };

  const handleLookupCounterpartyByInn = async () => {
    const inn = toDigits(counterpartyDraft.inn);
    if (inn.length !== 10 && inn.length !== 12) {
      setInnLookupMessage('ИНН должен содержать 10 или 12 цифр.');
      return;
    }

    setIsInnLookupLoading(true);
    setInnLookupMessage(null);

    try {
      const result = await api.lookupCounterpartyByInn(inn);
      if (result.found && result.counterparty) {
        setFormData((prev) => ({ ...prev, counterpartyId: result.counterparty!.id }));
        setCounterpartyDraft(mapCounterpartyToDraft(result.counterparty));
        setUseExistingCounterparty(true);
        setInnLookupMessage('Контрагент найден в базе и подставлен автоматически.');
      } else {
        setFormData((prev) => ({ ...prev, counterpartyId: '' }));
        setUseExistingCounterparty(false);
        setCounterpartyDraft((prev) => ({ ...prev, inn }));
        setInnLookupMessage('Контрагент с таким ИНН не найден в базе. Заполните данные для нового контрагента.');
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось выполнить поиск по ИНН.';
      setInnLookupMessage(message);
    } finally {
      setIsInnLookupLoading(false);
    }
  };

  const validateStep1 = () => {
    if (isPersonNoInvoiceMode) {
      if (!normalizedPrivateBuyer.fullName) {
        return 'Укажите ФИО покупателя-физлица.';
      }
      if (!normalizedPrivateBuyer.passportSeries || !normalizedPrivateBuyer.passportNumber) {
        return 'Укажите серию и номер паспорта покупателя.';
      }
      if (!normalizedPrivateBuyer.registrationAddress && !normalizedPrivateBuyer.residenceAddress) {
        return 'Укажите адрес покупателя.';
      }
      return null;
    }

    if (useExistingCounterparty) {
      if (!formData.counterpartyId || !selectedExistingCounterparty) {
        return 'Выберите существующего контрагента из списка.';
      }
      return null;
    }

    const inn = toDigits(counterpartyDraft.inn);
    const bik = toDigits(counterpartyDraft.bik);
    const checkingAccount = toDigits(counterpartyDraft.checkingAccount);

    if (counterpartyDraft.legalType !== 'person' && inn.length !== 10 && inn.length !== 12) {
      return 'Введите корректный ИНН (10 или 12 цифр).';
    }

    if (!counterpartyDraft.name.trim()) {
      return 'Укажите наименование контрагента.';
    }

    if (!counterpartyDraft.address.trim()) {
      return 'Укажите адрес контрагента.';
    }

    if (isCounterpartyCompanyType(counterpartyDraft.legalType) && !counterpartyDraft.directorName.trim()) {
      return 'Для ООО/АО укажите ФИО руководителя.';
    }

    if (counterpartyDraft.legalType !== 'person') {
      if (!counterpartyDraft.bankName.trim()) {
        return 'Укажите название банка.';
      }

      if (!/^\d{9}$/.test(bik)) {
        return 'БИК должен содержать 9 цифр.';
      }

      if (!/^\d{20}$/.test(checkingAccount)) {
        return 'Расчетный счет должен содержать 20 цифр.';
      }
    }

    return null;
  };

  const validateStep2 = () => {
    if (isPersonNoInvoiceMode) {
      return null;
    }
    if (isInitialInvoiceLinked) {
      return null;
    }

    if (!invoiceDraft.date) {
      return 'Укажите дату счета.';
    }

    if (invoiceDraft.paymentDueDate) {
      const issueDate = new Date(invoiceDraft.date);
      const dueDate = new Date(invoiceDraft.paymentDueDate);
      if (Number.isNaN(issueDate.getTime()) || Number.isNaN(dueDate.getTime())) {
        return 'Некорректная дата счета или дедлайна оплаты.';
      }
      if (dueDate.getTime() < issueDate.getTime()) {
        return 'Дата оплаты не может быть раньше даты счета.';
      }
    }

    return validateLineItems(invoiceItems);
  };

  const validateStep3 = () => {
    if (!formData.templateId) {
      return 'Выберите шаблон договора.';
    }

    if (!formData.number.trim()) {
      return 'Укажите номер договора.';
    }

    const paymentTerms = Number(formData.paymentTerms || 0);
    if (!Number.isFinite(paymentTerms) || paymentTerms <= 0) {
      return 'Срок оплаты должен быть больше 0.';
    }

    if (formData.includeDelivery && !formData.deliveryDate) {
      return 'Укажите срок выполнения работ/поставки.';
    }

    if (paymentConfig.hasPrepayment) {
      const prepayment = paymentConfig.prepaymentPercent;
      if (!Number.isFinite(prepayment) || prepayment <= 0 || prepayment > 100) {
        return 'Процент аванса должен быть в диапазоне от 0.01 до 100.';
      }
    }
    if (isSupplyLegalEntitiesContract && !paymentConfig.hasPrepayment && !paymentConfig.customPaymentTerms) {
      return 'Для режима «Иное условие оплаты» заполните текст условия.';
    }

    const penalty = Number(formData.penaltyPercentPerDay || 0);
    if (!Number.isFinite(penalty) || penalty < 0) {
      return 'Пеня за просрочку должна быть неотрицательной.';
    }

    if (isPersonNoInvoiceMode) {
      const lineItemsError = validateLineItems(invoiceItems);
      if (lineItemsError) {
        return lineItemsError;
      }
    }

    if (isPrivatePersonSaleContract) {
      const sellerProfile = selectedSupplierProfile;
      if (!sellerProfile) {
        return 'Для шаблона купли-продажи выберите профиль продавца в настройках («Мои компании»).';
      }
      if (sellerProfile.legalType !== 'ip' && sellerProfile.legalType !== 'person') {
        return 'Для шаблона купли-продажи выберите профиль продавца типа «ИП» или «Физлицо (РФ)».';
      }
      if (sellerProfile.legalType === 'ip') {
        if (!String(sellerProfile.companyName || '').trim()) {
          return 'Для шаблона купли-продажи (ИП) заполните ФИО предпринимателя в профиле продавца.';
        }
        if (!String(sellerProfile.inn || '').trim()) {
          return 'Для шаблона купли-продажи (ИП) заполните ИНН продавца в профиле.';
        }
        if (!String(sellerProfile.ogrnip || '').trim()) {
          return 'Для шаблона купли-продажи (ИП) заполните ОГРНИП продавца в профиле.';
        }
        if (!String(sellerProfile.legalAddress || '').trim()) {
          return 'Для шаблона купли-продажи (ИП) заполните адрес продавца в профиле.';
        }
      }
      if (sellerProfile.legalType === 'person') {
        if (!String(sellerProfile.companyName || '').trim()) {
          return 'Для шаблона купли-продажи (физлицо) заполните ФИО продавца в профиле.';
        }
        if (!String(sellerProfile.passportSeries || '').trim() || !String(sellerProfile.passportNumber || '').trim()) {
          return 'Для шаблона купли-продажи (физлицо) заполните паспорт продавца в профиле.';
        }
        if (
          !String(sellerProfile.registrationAddress || '').trim() &&
          !String(sellerProfile.residenceAddress || '').trim() &&
          !String(sellerProfile.legalAddress || '').trim()
        ) {
          return 'Для шаблона купли-продажи (физлицо) заполните адрес продавца в профиле.';
        }
        if (!hasSellerPersonAnyPaymentMethod(sellerProfile)) {
          return 'Для шаблона купли-продажи (физлицо) укажите минимум один способ оплаты продавца: карта, СБП или полные банковские реквизиты.';
        }
      }

      const buyer = normalizedPrivateBuyer;
      if (!buyer.fullName) {
        return 'Укажите ФИО покупателя-физлица.';
      }
      if (!buyer.passportSeries || !buyer.passportNumber) {
        return 'Укажите серию и номер паспорта покупателя.';
      }
      if (!buyer.registrationAddress && !buyer.residenceAddress) {
        return 'Укажите адрес покупателя.';
      }
      if (!buyer.phone) {
        return 'Укажите телефон покупателя (используется для уведомлений и связи).';
      }
    }
    if (isSupplyLegalEntitiesContract) {
      const supplierType = selectedSupplierProfile?.legalType;
      const buyerType = previewCounterparty?.legalType || counterpartyDraft.legalType;
      if (!isLegalEntityOrIpType(supplierType) || !isLegalEntityOrIpType(buyerType)) {
        return 'Шаблон "юрлица и ИП" доступен только для сторон типов ООО/АО/ИП. Измените типы сторон и повторите попытку.';
      }
    }

    return null;
  };

  const handleNext = () => {
    let error: string | null = null;
    if (step === 1) {
      error = validateStep1();
    } else if (step === 2) {
      error = validateStep2();
    } else if (step === 3) {
      error = validateStep3();
    }

    if (error) {
      setStepError(error);
      return;
    }

    setStepError(null);
    setStep((prev) => Math.min(getNextStepNumber(prev), 4));
  };

  const handleBack = () => {
    setStepError(null);
    setStep((prev) => Math.max(getPrevStepNumber(prev), 1));
  };

  const addInvoiceItem = () => {
    setInvoiceDraft((prev) => ({ ...prev, items: [...prev.items, createEmptyInvoiceItem()] }));
  };

  const updateInvoiceItem = (itemId: string, patch: Partial<InvoiceItemDraft>) => {
    setInvoiceDraft((prev) => ({
      ...prev,
      items: prev.items.map((item) => (item.id === itemId ? { ...item, ...patch } : item)),
    }));
  };

  const removeInvoiceItem = (itemId: string) => {
    setInvoiceDraft((prev) => {
      const nextItems = prev.items.filter((item) => item.id !== itemId);
      return {
        ...prev,
        items: nextItems.length > 0 ? nextItems : [createEmptyInvoiceItem()],
      };
    });
  };

  const ensureCounterparty = async (): Promise<Counterparty> => {
    if (createdCounterparty) {
      return createdCounterparty;
    }

    if (useExistingCounterparty && formData.counterpartyId) {
      const existing = counterparties.find((counterparty) => counterparty.id === formData.counterpartyId);
      if (existing) {
        setCreatedCounterparty(existing);
        return existing;
      }
    }

    if (isPersonNoInvoiceMode) {
      const buyer = normalizedPrivateBuyer;
      const contactPerson = counterpartyDraft.contactPerson.trim() || buyer.fullName;
      const address = buyer.registrationAddress || buyer.residenceAddress;
      const payload: CreateCounterpartyPayload = {
        legalType: 'person',
        name: buyer.fullName,
        inn: '',
        address,
        contactPerson,
        email: buyer.email,
        phone: buyer.phone,
        passportSeries: buyer.passportSeries,
        passportNumber: buyer.passportNumber,
        passportIssuedBy: buyer.passportIssuedBy,
        passportIssuedDate: buyer.passportIssuedDate,
        passportDepartmentCode: buyer.passportDepartmentCode,
        registrationAddress: buyer.registrationAddress,
        residenceAddress: buyer.residenceAddress,
      };

      const created = await api.createCounterparty(payload);
      setCreatedCounterparty(created);
      setUseExistingCounterparty(true);
      setFormData((prev) => ({ ...prev, counterpartyId: created.id }));
      return created;
    }

    const payload: CreateCounterpartyPayload = {
      legalType: counterpartyDraft.legalType,
      name: counterpartyDraft.name.trim(),
      inn: toDigits(counterpartyDraft.inn),
      address: counterpartyDraft.address.trim(),
      contactPerson: counterpartyDraft.contactPerson.trim(),
      email: counterpartyDraft.email.trim(),
      directorName: counterpartyDraft.directorName.trim(),
      ogrn: counterpartyDraft.ogrn.trim(),
      kpp: counterpartyDraft.kpp.trim(),
      ogrnip: counterpartyDraft.ogrnip.trim(),
      bankAccounts: [
        {
          bankName: counterpartyDraft.bankName.trim(),
          bik: toDigits(counterpartyDraft.bik),
          checkingAccount: toDigits(counterpartyDraft.checkingAccount),
          correspondentAccount: toDigits(counterpartyDraft.correspondentAccount),
        },
      ],
      bankName: counterpartyDraft.bankName.trim(),
      bik: toDigits(counterpartyDraft.bik),
      checkingAccount: toDigits(counterpartyDraft.checkingAccount),
      correspondentAccount: toDigits(counterpartyDraft.correspondentAccount),
    };

    const created = await api.createCounterparty(payload);
    setCreatedCounterparty(created);
    setUseExistingCounterparty(true);
    setFormData((prev) => ({ ...prev, counterpartyId: created.id }));
    return created;
  };

  const ensureInvoice = async (counterpartyId: string): Promise<Invoice | null> => {
    if (isPersonNoInvoiceMode) {
      return null;
    }

    if (createdInvoice) {
      return createdInvoice;
    }

    const payloadItems = invoiceItems.map((item) => ({
      description: item.description.trim(),
      quantity: item.quantity,
      price: item.price,
      unit: item.unit,
    }));

    const created = await api.createInvoice({
      date: isoToRuDate(invoiceDraft.date),
      paymentDueDate: invoiceDraft.paymentDueDate ? isoToRuDate(invoiceDraft.paymentDueDate) : undefined,
      currency: invoiceDraft.currency || 'RUB',
      status: 'Не оплачен',
      commissionPercent: invoiceCommissionPercent,
      vatRate: invoiceDraft.vatRate,
      vatMode: invoiceDraft.vatMode,
      supplierProfileId: selectedSupplierProfileId || undefined,
      supplierBankAccount: selectedSupplierBankAccount,
      items: payloadItems,
      counterpartyId,
    });

    setCreatedInvoice(created);
    return created;
  };

  const ensureContractCreated = async (): Promise<Contract> => {
    if (createdContract) {
      return createdContract;
    }

    const counterparty = await ensureCounterparty();
    const invoice = isPersonNoInvoiceMode ? null : await ensureInvoice(counterparty.id);

    const penaltyPercentPerDay = Number(formData.penaltyPercentPerDay || 0);

    const parsedDeliveryTermDays = Number(formData.deliveryTermDays);
    const parsedConfidentialityPenaltyAmount = Number(formData.confidentialityPenaltyAmount);
    const contractVatRate = invoice?.vatRate || (isPersonNoInvoiceMode ? 'none' : invoiceDraft.vatRate);
    const goodsSaleContractData: GoodsSaleExtendedContractData = {
      signingCity: formData.signingCity.trim() || undefined,
      deliveryCity: formData.deliveryCity.trim() || undefined,
      deliveryTermDays: Number.isFinite(parsedDeliveryTermDays) && parsedDeliveryTermDays > 0 ? parsedDeliveryTermDays : undefined,
      deliveryTermBasis: formData.deliveryTermBasis.trim() || undefined,
        deliveryCostPayer: isSupplyLegalEntitiesContract ? 'buyer' : formData.deliveryCostPayer || undefined,
      deliveryMethod: formData.deliveryMethod.trim() || undefined,
      purchasePurpose: formData.purchasePurpose,
      supplierTaxBasis:
        contractVatRate === 'none' && selectedSupplierProfile?.legalType !== 'person'
          ? formData.supplierTaxBasis.trim() || undefined
          : undefined,
      confidentialityPenaltyAmount:
        Number.isFinite(parsedConfidentialityPenaltyAmount) && parsedConfidentialityPenaltyAmount >= 0
          ? parsedConfidentialityPenaltyAmount
          : undefined,
    };

    const contract = await api.createContract({
      type: formData.type,
      counterpartyId: counterparty.id,
      invoiceId: invoice?.id,
      amount: pricingPreview.total,
      paymentTerms: Number(formData.paymentTerms || 10),
      includeDelivery: formData.includeDelivery,
      deliveryDate: formData.includeDelivery && formData.deliveryDate ? isoToRuDate(formData.deliveryDate) : null,
      number: formData.number,
      vatRate: contractVatRate,
      vatMode: invoice?.vatMode || (isPersonNoInvoiceMode ? 'included' : invoiceDraft.vatMode),
      markupPercent: isPersonNoInvoiceMode ? 0 : invoiceCommissionPercent,
      markupMode: 'per_item',
      markupCalcMode: 'simple',
      templateId: formData.templateId || undefined,
      contractData: {
        hasPrepayment: paymentConfig.hasPrepayment,
        prepaymentPercent: paymentConfig.prepaymentPercent,
        customPaymentTerms: paymentConfig.customPaymentTerms || undefined,
        penaltyPercentPerDay: Number.isFinite(penaltyPercentPerDay) ? penaltyPercentPerDay : 0,
        contractScenario: isPrivatePersonSaleContract
          ? 'private_person_goods_sale'
          : isSupplyLegalEntitiesContract
            ? 'supply_legal_entities'
            : 'default',
        supplierSignerPosition: isSupplyLegalEntitiesContract ? formData.supplierSignerPosition.trim() || undefined : undefined,
        supplierSignerName: isSupplyLegalEntitiesContract ? formData.supplierSignerName.trim() || undefined : undefined,
        supplierSignerBasis: isSupplyLegalEntitiesContract ? formData.supplierSignerBasis.trim() || undefined : undefined,
        buyerSignerPosition: isSupplyLegalEntitiesContract ? formData.buyerSignerPosition.trim() || undefined : undefined,
        buyerSignerName: isSupplyLegalEntitiesContract ? formData.buyerSignerName.trim() || undefined : undefined,
        buyerSignerBasis: isSupplyLegalEntitiesContract ? formData.buyerSignerBasis.trim() || undefined : undefined,
        privateBuyerRf: isPrivatePersonSaleContract ? normalizedPrivateBuyer : undefined,
        contractItems: invoiceItems.map((item) => ({
          id: item.id,
          description: item.description,
          quantity: item.quantity,
          price: item.price,
          unit: item.unit,
        })),
        ...goodsSaleContractData,
      },
    });

    setCreatedContract(contract);
    await onContractCreated();
    return contract;
  };

  const downloadBlob = (blob: Blob, fileName: string) => {
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = fileName;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    window.URL.revokeObjectURL(url);
  };

  const downloadContractFile = async (format: 'pdf' | 'docx') => {
    setIsGenerating(true);
    try {
      const contract = await ensureContractCreated();
      const contentElement = document.getElementById('contract-content');
      const htmlForExport = contract.htmlSnapshot || contentElement?.outerHTML;

      if (!htmlForExport) {
        throw new Error('Не удалось подготовить HTML договора для экспорта.');
      }

      const fileName = buildContractDocumentName(contract);
      const blob = await api.generateContractFile(format, {
        html: htmlForExport,
        css: contract.snapshotCss || CONTRACT_DOCUMENT_CSS,
        fileName,
      });

      downloadBlob(blob, `${fileName}.${format}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : `Ошибка генерации ${format.toUpperCase()}`;
      alert(message);
    } finally {
      setIsGenerating(false);
    }
  };

  const downloadInvoiceFile = async (format: 'pdf' | 'docx') => {
    if (isPersonNoInvoiceMode) {
      alert('В режиме договора между физлицами счет не формируется.');
      return;
    }

    setIsGenerating(true);
    try {
      const counterparty = await ensureCounterparty();
      const invoice = await ensureInvoice(counterparty.id);
      if (!invoice) {
        throw new Error('Счет не сформирован.');
      }
      const invoiceDocumentForExport = buildInvoiceDocument({
        invoice,
        counterparty,
        settings,
        logoSrc: resolveAbsoluteLogoUrl(),
      });

      const fileName = buildInvoiceDocumentName(invoice, counterparty.name);
      const blob = await api.generateContractFile(format, {
        html: invoiceDocumentForExport.html,
        css: invoiceDocumentForExport.css,
        fileName,
      });

      downloadBlob(blob, `${fileName}.${format}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : `Ошибка генерации ${format.toUpperCase()}`;
      alert(message);
    } finally {
      setIsGenerating(false);
    }
  };

  const downloadArchive = async () => {
    setIsGenerating(true);
    try {
      const counterparty = await ensureCounterparty();
      const contract = await ensureContractCreated();
      const invoice = isPersonNoInvoiceMode ? null : await ensureInvoice(counterparty.id);

      const contentElement = document.getElementById('contract-content');
      const contractHtmlForExport = contract.htmlSnapshot || contentElement?.outerHTML;
      if (!contractHtmlForExport) {
        throw new Error('Не удалось подготовить HTML договора для архива.');
      }

      const contractFileName = buildContractDocumentName(contract);
      const files: Array<{ html: string; css: string; fileName: string }> = [];

      if (invoice) {
        const invoiceDocumentForExport = buildInvoiceDocument({
          invoice,
          counterparty,
          settings,
          logoSrc: resolveAbsoluteLogoUrl(),
        });
        const invoiceFileName = buildInvoiceDocumentName(invoice, counterparty.name);
        files.push({
          html: invoiceDocumentForExport.html,
          css: invoiceDocumentForExport.css,
          fileName: invoiceFileName,
        });
      }

      files.push({
        html: contractHtmlForExport,
        css: contract.snapshotCss || CONTRACT_DOCUMENT_CSS,
        fileName: contractFileName,
      });

      const archiveBlob = await api.generateDocumentPackage({
        format: 'pdf',
        fileName: `Сделка_${contract.number || contract.id}`,
        files,
      });

      downloadBlob(archiveBlob, `Сделка_${contract.number || contract.id}.zip`);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось сформировать архив документов.';
      alert(message);
    } finally {
      setIsGenerating(false);
    }
  };

  const sendToEmail = async () => {
    try {
      const counterparty = await ensureCounterparty();
      const invoice = isPersonNoInvoiceMode ? null : await ensureInvoice(counterparty.id);
      const contract = await ensureContractCreated();
      const recipient = String(counterparty.email || '').trim();

      if (!recipient) {
        alert('У контрагента не заполнен email.');
        return;
      }

      const subject = encodeURIComponent(`Пакет документов по сделке ${contract.number || contract.id}`);
      const body = encodeURIComponent(
        `Добрый день!\n\nВо вложении/по ссылке документы по сделке:\n` +
          `${invoice ? `- Счет: ${buildInvoiceDocumentName(invoice, counterparty.name)}\n` : ''}` +
          `- Договор: ${buildContractDocumentName(contract)}\n\nС уважением,\n${settings?.companyName || 'Компания'}`,
      );

      window.location.href = `mailto:${encodeURIComponent(recipient)}?subject=${subject}&body=${body}`;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось подготовить отправку email.';
      alert(message);
    }
  };

  const exportToEdo = async () => {
    try {
      const counterparty = await ensureCounterparty();
      const invoice = isPersonNoInvoiceMode ? null : await ensureInvoice(counterparty.id);
      const contract = await ensureContractCreated();

      const payload = {
        caseId: `case-${contract.id}`,
        exportedAt: new Date().toISOString(),
        counterparty: {
          id: counterparty.id,
          inn: counterparty.inn,
          name: counterparty.name,
          email: counterparty.email,
        },
        invoice: invoice
          ? {
              id: invoice.id,
              number: invoice.number,
              date: invoice.date,
              paymentDueDate: invoice.paymentDueDate,
              amount: invoice.amount,
              currency: invoice.currency,
            }
          : null,
        contract: {
          id: contract.id,
          number: contract.number,
          type: contract.type,
          createdAt: contract.createdAt,
          amount: contract.amount,
        },
      };

      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' });
      downloadBlob(blob, `EDO_${contract.number || contract.id}.json`);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось сформировать выгрузку в ЭДО.';
      alert(message);
    }
  };

  const handleFinishCase = async () => {
    setIsGenerating(true);
    try {
      const contract = await ensureContractCreated();
      onFinish(contract.id);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось завершить сделку.';
      alert(message);
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <div className="h-full flex flex-col">
      <div className="mb-6">
        <button
          onClick={onCancel}
          className="text-sm text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200 mb-4 flex items-center"
        >
          <Icons.ChevronRight className="w-4 h-4 rotate-180 mr-1" /> Вернуться к списку
        </button>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">Новый пакет документов</h1>

        <div className="mt-6 flex items-center w-full max-w-4xl">
          {visibleWizardSteps.map((stepItem, idx) => (
            <React.Fragment key={stepItem.num}>
              <div
                className={`flex items-center gap-2 ${
                  step >= stepItem.num ? 'text-blue-600 dark:text-blue-400' : 'text-slate-400 dark:text-slate-600'
                }`}
              >
                <div
                  className={`w-8 h-8 rounded-full flex items-center justify-center font-bold text-sm border-2 ${
                    step >= stepItem.num
                      ? 'border-blue-600 bg-blue-50 dark:bg-blue-900/30 dark:border-blue-500'
                      : 'border-slate-300 dark:border-slate-700'
                  }`}
                >
                  {step > stepItem.num ? <Icons.Check className="w-5 h-5" /> : stepItem.num}
                </div>
                <span className="text-sm font-medium hidden lg:inline">{stepItem.title}</span>
              </div>
              {idx < visibleWizardSteps.length - 1 && (
                <div
                  className={`flex-1 h-0.5 mx-3 ${
                    step > stepItem.num ? 'bg-blue-600 dark:bg-blue-500' : 'bg-slate-200 dark:bg-slate-700'
                  }`}
                />
              )}
            </React.Fragment>
          ))}
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-2 w-full max-w-4xl">
          <Button variant="ghost" onClick={handleBack} disabled={step === 1 || isGenerating}>
            Назад
          </Button>

          {Boolean(nextStepMeta) && (
            <Button onClick={handleNext} disabled={isGenerating}>
              {nextStepMeta ? `Далее: ${nextStepMeta.title}` : 'Далее'}
            </Button>
          )}

          {step === 4 && (
            <Button onClick={handleFinishCase} disabled={isGenerating}>
              Завершить и открыть договор
            </Button>
          )}
        </div>
      </div>

      <div className="flex-1 flex flex-col lg:flex-row gap-8 min-h-0">
        <div className="w-full lg:w-[34%] flex flex-col gap-6 overflow-y-auto pr-2">
          <Card className="p-6">
            <div className="mb-6">
              <p className="text-xs font-semibold uppercase tracking-wide text-blue-600 dark:text-blue-400">
                Шаг {currentStepMeta.num}
              </p>
              <h2 className="mt-1 text-lg font-semibold text-slate-900 dark:text-slate-100">{currentStepMeta.title}</h2>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{currentStepMeta.description}</p>
            </div>

            {stepError && (
              <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900/60 dark:bg-red-900/20 dark:text-red-200">
                {stepError}
              </div>
            )}

            {step === 1 && (
              <div className="space-y-4">
                {!isPersonNoInvoiceMode && (
                  <div className="grid grid-cols-1 md:grid-cols-[1fr_auto] gap-3 items-end">
                    <Input
                      label="ИНН"
                      value={counterpartyDraft.inn}
                      onChange={(event) => updateCounterpartyDraft({ inn: event.target.value })}
                      placeholder="7701234567"
                    />
                    <Button
                      type="button"
                      variant="outline"
                      icon={<Icons.Search className="w-4 h-4" />}
                      onClick={handleLookupCounterpartyByInn}
                      disabled={isInnLookupLoading}
                    >
                      {isInnLookupLoading ? 'Поиск...' : 'Поиск по ИНН'}
                    </Button>
                  </div>
                )}

                {!isPersonNoInvoiceMode && innLookupMessage && (
                  <div className="rounded-md border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 px-3 py-2 text-xs text-slate-600 dark:text-slate-300">
                    {innLookupMessage}
                  </div>
                )}

                <Select
                  label="Или выбрать контрагента из базы"
                  value={formData.counterpartyId}
                  onChange={(event) => handleSelectExistingCounterparty(event.target.value)}
                  options={[
                    { value: '', label: 'Не выбран' },
                    ...counterparties.map((counterparty) => ({
                      value: counterparty.id,
                      label: `${counterparty.name} (${counterparty.inn})`,
                    })),
                  ]}
                />

                {counterpartyLocked && (
                  <div className="flex justify-end">
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setUseExistingCounterparty(false);
                        setFormData((prev) => ({ ...prev, counterpartyId: '' }));
                      }}
                    >
                      Редактировать как нового
                    </Button>
                  </div>
                )}

                {isPersonNoInvoiceMode ? (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <Select
                      label="Тип контрагента"
                      value={counterpartyDraft.legalType}
                      disabled={counterpartyLocked}
                      onChange={(event) => updateCounterpartyDraft({ legalType: event.target.value as CounterpartyLegalType })}
                      options={[
                        { value: 'ooo', label: 'ООО' },
                        { value: 'ao', label: 'АО' },
                        { value: 'ip', label: 'ИП' },
                        { value: 'person', label: 'Физ. лицо' },
                      ]}
                    />
                    <Input
                      label="Контактное лицо"
                      value={counterpartyDraft.contactPerson}
                      disabled={counterpartyLocked}
                      onChange={(event) => updateCounterpartyDraft({ contactPerson: event.target.value })}
                      placeholder={normalizedPrivateBuyer.fullName || 'ФИО покупателя'}
                    />
                    <div className="md:col-span-2">
                      <Input
                        label="ФИО"
                        value={privateBuyerRfDraft.fullName}
                        disabled={counterpartyLocked}
                        onChange={(event) =>
                          setPrivateBuyerRfDraft((prev) => ({ ...prev, fullName: event.target.value }))
                        }
                        placeholder="Петров Петр Петрович"
                      />
                    </div>
                    <Input
                      label="Телефон"
                      value={privateBuyerRfDraft.phone}
                      disabled={counterpartyLocked}
                      onChange={(event) => setPrivateBuyerRfDraft((prev) => ({ ...prev, phone: event.target.value }))}
                    />
                    <Input
                      type="email"
                      label="Email"
                      value={privateBuyerRfDraft.email}
                      disabled={counterpartyLocked}
                      onChange={(event) => setPrivateBuyerRfDraft((prev) => ({ ...prev, email: event.target.value }))}
                    />
                    <Input
                      label="Серия паспорта"
                      value={privateBuyerRfDraft.passportSeries}
                      disabled={counterpartyLocked}
                      onChange={(event) =>
                        setPrivateBuyerRfDraft((prev) => ({ ...prev, passportSeries: event.target.value }))
                      }
                      placeholder="4511"
                    />
                    <Input
                      label="Номер паспорта"
                      value={privateBuyerRfDraft.passportNumber}
                      disabled={counterpartyLocked}
                      onChange={(event) =>
                        setPrivateBuyerRfDraft((prev) => ({ ...prev, passportNumber: event.target.value }))
                      }
                      placeholder="654321"
                    />
                    <div className="md:col-span-2">
                      <Input
                        label="Кем выдан паспорт"
                        value={privateBuyerRfDraft.passportIssuedBy}
                        disabled={counterpartyLocked}
                        onChange={(event) =>
                          setPrivateBuyerRfDraft((prev) => ({ ...prev, passportIssuedBy: event.target.value }))
                        }
                      />
                    </div>
                    <Input
                      type="date"
                      label="Дата выдачи паспорта"
                      value={privateBuyerRfDraft.passportIssuedDate}
                      disabled={counterpartyLocked}
                      onChange={(event) =>
                        setPrivateBuyerRfDraft((prev) => ({ ...prev, passportIssuedDate: event.target.value }))
                      }
                    />
                    <Input
                      label="Код подразделения"
                      value={privateBuyerRfDraft.passportDepartmentCode}
                      disabled={counterpartyLocked}
                      onChange={(event) =>
                        setPrivateBuyerRfDraft((prev) => ({ ...prev, passportDepartmentCode: event.target.value }))
                      }
                      placeholder="000-000"
                    />
                    <div className="md:col-span-2">
                      <Input
                        label="Адрес регистрации"
                        value={privateBuyerRfDraft.registrationAddress}
                        disabled={counterpartyLocked}
                        onChange={(event) =>
                          setPrivateBuyerRfDraft((prev) => ({ ...prev, registrationAddress: event.target.value }))
                        }
                      />
                    </div>
                    <div className="md:col-span-2">
                      <Input
                        label="Адрес проживания (если отличается)"
                        value={privateBuyerRfDraft.residenceAddress}
                        disabled={counterpartyLocked}
                        onChange={(event) =>
                          setPrivateBuyerRfDraft((prev) => ({ ...prev, residenceAddress: event.target.value }))
                        }
                      />
                    </div>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <Select
                      label="Тип контрагента"
                      value={counterpartyDraft.legalType}
                      disabled={counterpartyLocked}
                      onChange={(event) => updateCounterpartyDraft({ legalType: event.target.value as CounterpartyLegalType })}
                      options={[
                        { value: 'ooo', label: 'ООО' },
                        { value: 'ao', label: 'АО' },
                        { value: 'ip', label: 'ИП' },
                        { value: 'person', label: 'Физ. лицо' },
                      ]}
                    />
                    <Input
                      label={getCounterpartyNameFieldLabel(counterpartyDraft.legalType)}
                      value={counterpartyDraft.name}
                      disabled={counterpartyLocked}
                      onChange={(event) => updateCounterpartyDraft({ name: event.target.value })}
                      placeholder={getCounterpartyNamePlaceholder(counterpartyDraft.legalType)}
                    />
                    {counterpartyDraft.legalType !== 'person' && (
                      <Input
                        label="КПП"
                        value={counterpartyDraft.kpp}
                        disabled={counterpartyLocked || !isCounterpartyCompanyType(counterpartyDraft.legalType)}
                        onChange={(event) => updateCounterpartyDraft({ kpp: event.target.value })}
                      />
                    )}
                    <Input
                      label={isCounterpartyCompanyType(counterpartyDraft.legalType) ? 'Руководитель' : 'Контактное лицо'}
                      value={counterpartyDraft.directorName}
                      disabled={counterpartyLocked}
                      onChange={(event) => updateCounterpartyDraft({ directorName: event.target.value })}
                    />
                    <Input
                      label="Контактное лицо"
                      value={counterpartyDraft.contactPerson}
                      disabled={counterpartyLocked}
                      onChange={(event) => updateCounterpartyDraft({ contactPerson: event.target.value })}
                    />
                    <Input
                      label="Email"
                      value={counterpartyDraft.email}
                      disabled={counterpartyLocked}
                      onChange={(event) => updateCounterpartyDraft({ email: event.target.value })}
                    />
                    <div className="md:col-span-2">
                      <Input
                        label="Адрес"
                        value={counterpartyDraft.address}
                        disabled={counterpartyLocked}
                        onChange={(event) => updateCounterpartyDraft({ address: event.target.value })}
                      />
                    </div>
                    {counterpartyDraft.legalType !== 'person' && (
                      <>
                        <Input
                          label="Банк"
                          value={counterpartyDraft.bankName}
                          disabled={counterpartyLocked}
                          onChange={(event) => updateCounterpartyDraft({ bankName: event.target.value })}
                        />
                        <Input
                          label="БИК"
                          value={counterpartyDraft.bik}
                          disabled={counterpartyLocked}
                          onChange={(event) => updateCounterpartyDraft({ bik: event.target.value })}
                        />
                        <Input
                          label="Расчетный счет"
                          value={counterpartyDraft.checkingAccount}
                          disabled={counterpartyLocked}
                          onChange={(event) => updateCounterpartyDraft({ checkingAccount: event.target.value })}
                        />
                        <Input
                          label="Корреспондентский счет"
                          value={counterpartyDraft.correspondentAccount}
                          disabled={counterpartyLocked}
                          onChange={(event) => updateCounterpartyDraft({ correspondentAccount: event.target.value })}
                        />
                      </>
                    )}
                  </div>
                )}
              </div>
            )}

            {step === 2 && !isPersonNoInvoiceMode && (
              <div className="space-y-4">
                {isInitialInvoiceLinked && createdInvoice && (
                  <div className="rounded-md border border-blue-200 dark:border-blue-900/60 bg-blue-50/70 dark:bg-blue-900/20 px-3 py-2 text-xs text-blue-800 dark:text-blue-200">
                    Для договора используется существующий счет {createdInvoice.number} от {createdInvoice.date}. Данные счета
                    уже подтянуты в мастер.
                  </div>
                )}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <Input
                    type="date"
                    label="Дата счета"
                    value={invoiceDraft.date}
                    onChange={(event) => setInvoiceDraft((prev) => ({ ...prev, date: event.target.value }))}
                  />
                  <Input
                    type="date"
                    label="Оплатить до"
                    value={invoiceDraft.paymentDueDate}
                    onChange={(event) => setInvoiceDraft((prev) => ({ ...prev, paymentDueDate: event.target.value }))}
                  />
                  <Input
                    label="Процент комиссии счета"
                    type="number"
                    min={0}
                    step="0.1"
                    value={invoiceDraft.commissionPercent}
                    onChange={(event) => setInvoiceDraft((prev) => ({ ...prev, commissionPercent: event.target.value }))}
                  />
                  <Input
                    label="Валюта"
                    value={invoiceDraft.currency}
                    onChange={(event) => setInvoiceDraft((prev) => ({ ...prev, currency: event.target.value.toUpperCase() }))}
                    placeholder="RUB"
                  />
                </div>

                <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-4 space-y-4">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Налоги</h3>
                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Настройка НДС для итоговой суммы.</p>
                  </div>

                  <Select
                    label="Профиль компании"
                    value={selectedSupplierProfileId}
                    onChange={(event) =>
                      setInvoiceDraft((prev) => ({
                        ...prev,
                        supplierProfileId: event.target.value,
                        supplierBankAccountKey: '0',
                      }))
                    }
                    options={
                      (isSupplyLegalEntitiesContract ? legalTemplateSupplierProfiles : supplierProfiles).length > 0
                        ? (isSupplyLegalEntitiesContract ? legalTemplateSupplierProfiles : supplierProfiles).map((profile, index) => ({
                            value: profile.id,
                            label: profile.companyName || `Компания ${index + 1}`,
                          }))
                        : [{ value: '', label: 'Нет профилей компании в настройках' }]
                    }
                  />
                  {isSupplyLegalEntitiesContract && legalTemplateSupplierProfiles.length === 0 && (
                    <div className="rounded-md border border-amber-200 dark:border-amber-900/60 bg-amber-50/70 dark:bg-amber-900/20 px-3 py-2 text-xs text-amber-800 dark:text-amber-200">
                      Для шаблона «юрлица и ИП» нужен профиль поставщика типа ООО/АО/ИП. Добавьте такой профиль в настройках.
                    </div>
                  )}

                  <Select
                    label="Счет поставщика"
                    value={invoiceDraft.supplierBankAccountKey}
                    onChange={(event) => setInvoiceDraft((prev) => ({ ...prev, supplierBankAccountKey: event.target.value }))}
                    options={
                      supplierBankAccounts.length > 0
                        ? supplierBankAccounts.map((account, index) => ({
                            value: String(index),
                            label: `${account.bankName || 'Без названия банка'} · р/с ${account.checkingAccount || 'не указан'}`,
                          }))
                        : [{ value: '', label: 'Нет доступных счетов в настройках компании' }]
                    }
                  />

                  <Select
                    label="Ставка НДС"
                    value={invoiceDraft.vatRate}
                    onChange={(event) => setInvoiceDraft((prev) => ({ ...prev, vatRate: event.target.value as VatRate }))}
                    options={[
                      { value: 'none', label: getVatRateLabel('none') },
                      { value: '0', label: getVatRateLabel('0') },
                      { value: '10', label: getVatRateLabel('10') },
                      { value: '20', label: getVatRateLabel('20') },
                    ]}
                  />

                  <div className="space-y-2">
                    <p className="text-sm font-medium text-slate-700 dark:text-slate-300">Метод начисления</p>
                    {VAT_MODE_OPTIONS.map((option) => (
                      <label
                        key={option.value}
                        className="flex items-start gap-3 rounded-md border border-slate-200 dark:border-slate-700 px-3 py-2 cursor-pointer hover:border-blue-400 dark:hover:border-blue-500"
                      >
                        <input
                          type="radio"
                          name="vat-mode"
                          className="mt-1 h-4 w-4 text-blue-600"
                          checked={invoiceDraft.vatMode === option.value}
                          onChange={() => setInvoiceDraft((prev) => ({ ...prev, vatMode: option.value }))}
                        />
                        <span>
                          <span className="block text-sm font-medium text-slate-800 dark:text-slate-100">{option.title}</span>
                          <span className="block text-xs text-slate-500 dark:text-slate-400">{option.description}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                </div>

                <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-3">
                  <div className="text-sm font-medium text-slate-900 dark:text-slate-100 mb-3">Позиции счета</div>
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[900px] text-sm">
                      <thead>
                        <tr className="text-left text-slate-600 dark:text-slate-300 border-b border-slate-200 dark:border-slate-700">
                          <th className="px-2 py-2 font-medium w-14">№</th>
                          <th className="px-2 py-2 font-medium min-w-[300px]">Наименование</th>
                          <th className="px-2 py-2 font-medium w-28">Кол-во</th>
                          <th className="px-2 py-2 font-medium w-28">Ед. изм.</th>
                          <th className="px-2 py-2 font-medium w-40">Цена</th>
                          <th className="px-2 py-2 font-medium w-40">Сумма</th>
                          <th className="px-2 py-2 font-medium w-16"></th>
                        </tr>
                      </thead>
                      <tbody>
                        {invoiceDraft.items.map((item, index) => {
                          const quantity = Number(item.quantity || 0);
                          const price = Number(item.price || 0);
                          const lineTotal = (Number.isFinite(quantity) ? quantity : 0) * (Number.isFinite(price) ? price : 0);

                          return (
                            <tr key={item.id} className="border-b border-slate-100 dark:border-slate-800 align-top">
                              <td className="px-2 py-2 text-slate-500">{index + 1}</td>
                              <td className="px-2 py-2">
                                <Input
                                  value={item.description}
                                  onChange={(event) => updateInvoiceItem(item.id, { description: event.target.value })}
                                  placeholder="Товар или услуга"
                                />
                              </td>
                              <td className="px-2 py-2">
                                <Input
                                  type="number"
                                  min={0}
                                  step="0.001"
                                  value={item.quantity}
                                  onChange={(event) => updateInvoiceItem(item.id, { quantity: event.target.value })}
                                />
                              </td>
                              <td className="px-2 py-2">
                                <Input
                                  value={item.unit}
                                  onChange={(event) => updateInvoiceItem(item.id, { unit: event.target.value })}
                                  placeholder="шт"
                                />
                              </td>
                              <td className="px-2 py-2">
                                <Input
                                  type="number"
                                  min={0}
                                  step="0.01"
                                  value={item.price}
                                  onChange={(event) => updateInvoiceItem(item.id, { price: event.target.value })}
                                />
                              </td>
                              <td className="px-2 py-2">
                                <div className="h-10 rounded-md border border-slate-300 dark:border-slate-700 px-3 flex items-center justify-end text-slate-700 dark:text-slate-200 bg-slate-50 dark:bg-slate-800/60">
                                  {lineTotal.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                                </div>
                              </td>
                              <td className="px-2 py-2">
                                <button
                                  type="button"
                                  onClick={() => removeInvoiceItem(item.id)}
                                  className="inline-flex items-center justify-center h-10 w-10 rounded-md border border-slate-300 text-slate-500 hover:text-red-600 hover:border-red-300 dark:border-slate-700 dark:text-slate-400 dark:hover:text-red-300"
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
                    <Button type="button" variant="outline" size="sm" icon={<Icons.Plus className="w-4 h-4" />} onClick={addInvoiceItem}>
                      Добавить позицию
                    </Button>
                  </div>
                </div>

                <div className="rounded-lg border border-blue-200 bg-blue-50/60 dark:bg-blue-900/10 dark:border-blue-800 p-4 text-sm space-y-2">
                  <div className="flex items-center justify-between text-slate-700 dark:text-slate-300">
                    <span>Базовая сумма</span>
                    <span>{formatCurrency(pricingPreview.baseSubtotal)}</span>
                  </div>
                  <div className="flex items-center justify-between text-slate-700 dark:text-slate-300">
                    <span>Комиссия {invoiceCommissionPercent.toLocaleString('ru-RU')}%</span>
                    <span>{formatCurrency(pricingPreview.markupAmount)}</span>
                  </div>
                  <div className="flex items-center justify-between text-slate-700 dark:text-slate-300">
                    <span>{vatSummaryLabel}</span>
                    <span>{formatCurrency(pricingPreview.vatAmount)}</span>
                  </div>
                  <div className="pt-2 border-t border-blue-200 dark:border-blue-800 flex items-center justify-between font-semibold text-slate-900 dark:text-slate-100">
                    <span>Итого к оплате</span>
                    <span>{formatCurrency(pricingPreview.total)}</span>
                  </div>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Номер счета будет присвоен автоматически при генерации пакета документов.
                  </p>
                </div>
              </div>
            )}

            {step === 3 && (
              <div className="space-y-4">
                <Select
                  label="Шаблон документа"
                  value={formData.templateId}
                  onChange={(event) => {
                    const nextTemplateId = event.target.value;
                    const nextTemplate = templates.find((template) => template.id === nextTemplateId);
                    setFormData((prev) => ({
                      ...prev,
                      templateId: nextTemplateId,
                      type: nextTemplate?.type || prev.type,
                    }));
                  }}
                  options={[
                    { value: '', label: templateOptions.length > 0 ? 'Выберите шаблон...' : 'Нет активных шаблонов' },
                    ...templateOptions.map((template) => ({
                      value: template.id,
                      label: `${template.name} (v${template.version})`,
                    })),
                  ]}
                />

                {isPrivatePersonSaleContract && (
                  <div className="rounded-lg border border-indigo-200 bg-indigo-50/70 dark:bg-indigo-900/20 dark:border-indigo-900/60 p-4 space-y-4">
                    <div>
                      <h3 className="text-sm font-semibold text-indigo-900 dark:text-indigo-200">
                        Доп. условия для шаблона купли-продажи
                      </h3>
                      <p className="mt-1 text-xs text-indigo-700 dark:text-indigo-300">
                        Эти поля используются для автоподстановки в расширенный шаблон (доставка, НДС, штраф, города).
                      </p>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      <Input
                        label="Город подписания договора"
                        value={formData.signingCity}
                        onChange={(event) => setFormData((prev) => ({ ...prev, signingCity: event.target.value }))}
                        placeholder="Челябинск"
                      />
                      <Input
                        label="Город доставки"
                        value={formData.deliveryCity}
                        onChange={(event) => setFormData((prev) => ({ ...prev, deliveryCity: event.target.value }))}
                        placeholder="Челябинск"
                      />
                      <Input
                        label="Срок поставки (календарных дней)"
                        type="number"
                        min={1}
                        value={formData.deliveryTermDays}
                        onChange={(event) => setFormData((prev) => ({ ...prev, deliveryTermDays: event.target.value }))}
                      />
                      <Select
                        label="Кто оплачивает доставку"
                        value={formData.deliveryCostPayer}
                        onChange={(event) =>
                          setFormData((prev) => ({ ...prev, deliveryCostPayer: event.target.value as WizardFormData['deliveryCostPayer'] }))
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
                          value={formData.deliveryTermBasis}
                          onChange={(event) => setFormData((prev) => ({ ...prev, deliveryTermBasis: event.target.value }))}
                          placeholder="с даты поступления полной оплаты"
                        />
                      </div>
                      <div className="md:col-span-2">
                        <Input
                          label="Способ доставки"
                          value={formData.deliveryMethod}
                          onChange={(event) => setFormData((prev) => ({ ...prev, deliveryMethod: event.target.value }))}
                          placeholder="ТК/курьер по согласованию Сторон"
                        />
                      </div>
                      <Select
                        label="Цель покупки"
                        value={formData.purchasePurpose}
                        onChange={(event) =>
                          setFormData((prev) => ({ ...prev, purchasePurpose: event.target.value as WizardFormData['purchasePurpose'] }))
                        }
                        options={[
                          { value: 'personal', label: 'Для личных нужд' },
                          { value: 'business', label: 'Для предпринимательской деятельности' },
                        ]}
                      />
                      {previewInvoice.vatRate === 'none' && (
                        isSelectedGoodsSaleSellerPerson ? (
                          <div className="md:col-span-2 rounded-md border border-indigo-200 dark:border-indigo-900/60 bg-indigo-50/70 dark:bg-indigo-900/20 px-3 py-2 text-xs text-indigo-800 dark:text-indigo-200">
                            Для продавца-физлица в договоре будет указано: «НДС не начисляется».
                          </div>
                        ) : (
                          <div className="md:col-span-2">
                            <Input
                              label="Основание/режим без НДС"
                              value={formData.supplierTaxBasis}
                              onChange={(event) => setFormData((prev) => ({ ...prev, supplierTaxBasis: event.target.value }))}
                              placeholder="УСН, без НДС"
                            />
                          </div>
                        )
                      )}
                      <Input
                        label="Штраф за нарушение конфиденциальности, ₽"
                        type="number"
                        min={0}
                        step="1"
                        value={formData.confidentialityPenaltyAmount}
                        onChange={(event) =>
                          setFormData((prev) => ({ ...prev, confidentialityPenaltyAmount: event.target.value }))
                        }
                      />
                    </div>

                    {goodsSaleTemplateMissingFields.length > 0 && (
                      <div className="rounded-md border border-amber-200 dark:border-amber-900/60 bg-amber-50/70 dark:bg-amber-900/20 px-3 py-3">
                        <p className="text-sm font-medium text-amber-900 dark:text-amber-200">
                          Для полного заполнения договора не хватает данных:
                        </p>
                        <ul className="mt-2 list-disc pl-5 text-xs text-amber-800 dark:text-amber-300 space-y-1">
                          {goodsSaleTemplateMissingFields.map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
                {isSupplyLegalEntitiesContract && (
                  <div className="rounded-lg border border-emerald-200 bg-emerald-50/70 dark:bg-emerald-900/20 dark:border-emerald-900/60 p-4 space-y-4">
                    <div>
                      <h3 className="text-sm font-semibold text-emerald-900 dark:text-emerald-200">
                        Подписанты для шаблона «юрлица и ИП»
                      </h3>
                      <p className="mt-1 text-xs text-emerald-700 dark:text-emerald-300">
                        Поля заполняются автоматически из профилей и контрагента, при необходимости можно отредактировать вручную.
                      </p>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      <Select
                        label="Режим оплаты"
                        value={formData.paymentMode}
                        onChange={(event) =>
                          setFormData((prev) => ({ ...prev, paymentMode: event.target.value as WizardFormData['paymentMode'] }))
                        }
                        options={[
                          { value: 'full_prepayment', label: '100% предоплата' },
                          { value: 'partial_prepayment', label: 'Частичная предоплата + доплата' },
                          { value: 'custom', label: 'Иное условие оплаты' },
                        ]}
                      />
                      {formData.paymentMode === 'partial_prepayment' && (
                        <Input
                          label="Размер предоплаты, %"
                          type="number"
                          min={0.01}
                          max={99.99}
                          step="0.01"
                          value={formData.prepaymentPercent}
                          onChange={(event) => setFormData((prev) => ({ ...prev, prepaymentPercent: event.target.value }))}
                        />
                      )}
                      {formData.paymentMode === 'custom' && (
                        <div className="md:col-span-2">
                          <Input
                            label="Иное условие оплаты"
                            value={formData.customPaymentTerms}
                            onChange={(event) => setFormData((prev) => ({ ...prev, customPaymentTerms: event.target.value }))}
                            placeholder="Оплата по согласованному графику"
                          />
                        </div>
                      )}
                      <Input
                        label="Поставщик: должность подписанта"
                        value={formData.supplierSignerPosition}
                        onChange={(event) => setFormData((prev) => ({ ...prev, supplierSignerPosition: event.target.value }))}
                        placeholder={defaultSupplierSigner.position || 'директор'}
                      />
                      <Input
                        label="Поставщик: ФИО подписанта"
                        value={formData.supplierSignerName}
                        onChange={(event) => setFormData((prev) => ({ ...prev, supplierSignerName: event.target.value }))}
                        placeholder={defaultSupplierSigner.name || 'Иванов Иван Иванович'}
                      />
                      <div className="md:col-span-2">
                        <Input
                          label="Поставщик: основание полномочий"
                          value={formData.supplierSignerBasis}
                          onChange={(event) => setFormData((prev) => ({ ...prev, supplierSignerBasis: event.target.value }))}
                          placeholder={defaultSupplierSigner.basis || 'Устава'}
                        />
                      </div>
                      <Input
                        label="Покупатель: должность подписанта"
                        value={formData.buyerSignerPosition}
                        onChange={(event) => setFormData((prev) => ({ ...prev, buyerSignerPosition: event.target.value }))}
                        placeholder={defaultBuyerSigner.position || 'директор'}
                      />
                      <Input
                        label="Покупатель: ФИО подписанта"
                        value={formData.buyerSignerName}
                        onChange={(event) => setFormData((prev) => ({ ...prev, buyerSignerName: event.target.value }))}
                        placeholder={defaultBuyerSigner.name || 'Петров Петр Петрович'}
                      />
                      <div className="md:col-span-2">
                        <Input
                          label="Покупатель: основание полномочий"
                          value={formData.buyerSignerBasis}
                          onChange={(event) => setFormData((prev) => ({ ...prev, buyerSignerBasis: event.target.value }))}
                          placeholder={defaultBuyerSigner.basis || 'Устава'}
                        />
                      </div>
                    </div>
                  </div>
                )}

                {isPersonNoInvoiceMode && (
                  <>
                    <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-3">
                      <div className="text-sm font-medium text-slate-900 dark:text-slate-100 mb-3">Позиции договора</div>
                      <div className="overflow-x-auto">
                        <table className="w-full min-w-[900px] text-sm">
                          <thead>
                            <tr className="text-left text-slate-600 dark:text-slate-300 border-b border-slate-200 dark:border-slate-700">
                              <th className="px-2 py-2 font-medium w-14">№</th>
                              <th className="px-2 py-2 font-medium min-w-[300px]">Наименование</th>
                              <th className="px-2 py-2 font-medium w-28">Кол-во</th>
                              <th className="px-2 py-2 font-medium w-28">Ед. изм.</th>
                              <th className="px-2 py-2 font-medium w-40">Цена</th>
                              <th className="px-2 py-2 font-medium w-40">Сумма</th>
                              <th className="px-2 py-2 font-medium w-16"></th>
                            </tr>
                          </thead>
                          <tbody>
                            {invoiceDraft.items.map((item, index) => {
                              const quantity = Number(item.quantity || 0);
                              const price = Number(item.price || 0);
                              const lineTotal =
                                (Number.isFinite(quantity) ? quantity : 0) * (Number.isFinite(price) ? price : 0);

                              return (
                                <tr key={item.id} className="border-b border-slate-100 dark:border-slate-800 align-top">
                                  <td className="px-2 py-2 text-slate-500">{index + 1}</td>
                                  <td className="px-2 py-2">
                                    <Input
                                      value={item.description}
                                      onChange={(event) => updateInvoiceItem(item.id, { description: event.target.value })}
                                      placeholder="Товар"
                                    />
                                  </td>
                                  <td className="px-2 py-2">
                                    <Input
                                      type="number"
                                      min={0}
                                      step="0.001"
                                      value={item.quantity}
                                      onChange={(event) => updateInvoiceItem(item.id, { quantity: event.target.value })}
                                    />
                                  </td>
                                  <td className="px-2 py-2">
                                    <Input
                                      value={item.unit}
                                      onChange={(event) => updateInvoiceItem(item.id, { unit: event.target.value })}
                                      placeholder="шт"
                                    />
                                  </td>
                                  <td className="px-2 py-2">
                                    <Input
                                      type="number"
                                      min={0}
                                      step="0.01"
                                      value={item.price}
                                      onChange={(event) => updateInvoiceItem(item.id, { price: event.target.value })}
                                    />
                                  </td>
                                  <td className="px-2 py-2">
                                    <div className="h-10 rounded-md border border-slate-300 dark:border-slate-700 px-3 flex items-center justify-end text-slate-700 dark:text-slate-200 bg-slate-50 dark:bg-slate-800/60">
                                      {lineTotal.toLocaleString('ru-RU', {
                                        minimumFractionDigits: 2,
                                        maximumFractionDigits: 2,
                                      })}
                                    </div>
                                  </td>
                                  <td className="px-2 py-2">
                                    <button
                                      type="button"
                                      onClick={() => removeInvoiceItem(item.id)}
                                      className="inline-flex items-center justify-center h-10 w-10 rounded-md border border-slate-300 text-slate-500 hover:text-red-600 hover:border-red-300 dark:border-slate-700 dark:text-slate-400 dark:hover:text-red-300"
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

                    <div className="rounded-lg border border-blue-200 bg-blue-50/60 dark:bg-blue-900/10 dark:border-blue-800 p-4 text-sm space-y-2">
                      <div className="flex items-center justify-between text-slate-700 dark:text-slate-300">
                        <span>Сумма по позициям</span>
                        <span>{formatCurrency(pricingPreview.baseSubtotal)}</span>
                      </div>
                      <div className="pt-2 border-t border-blue-200 dark:border-blue-800 flex items-center justify-between font-semibold text-slate-900 dark:text-slate-100">
                        <span>Итого по договору</span>
                        <span>{formatCurrency(pricingPreview.total)}</span>
                      </div>
                    </div>
                  </>
                )}

                {isPrivatePersonSaleContract && !isPersonNoInvoiceMode && (
                  <div className="rounded-lg border border-amber-200 bg-amber-50/70 dark:bg-amber-900/20 dark:border-amber-900/60 p-4 space-y-4">
                    <div>
                      <h3 className="text-sm font-semibold text-amber-900 dark:text-amber-200">
                        Данные для договора между физлицами
                      </h3>
                      <p className="mt-1 text-xs text-amber-700 dark:text-amber-300">
                        Продавец берется из настроек: «Мои компании» → профиль с типом «Физлицо (РФ)». Ниже заполните данные покупателя.
                      </p>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      <div className="md:col-span-2">
                        <Input
                          label="ФИО покупателя"
                          value={privateBuyerRfDraft.fullName}
                          onChange={(event) =>
                            setPrivateBuyerRfDraft((prev) => ({ ...prev, fullName: event.target.value }))
                          }
                          placeholder="Петров Петр Петрович"
                        />
                      </div>
                      <Input
                        label="Серия паспорта"
                        value={privateBuyerRfDraft.passportSeries}
                        onChange={(event) =>
                          setPrivateBuyerRfDraft((prev) => ({ ...prev, passportSeries: event.target.value }))
                        }
                        placeholder="4511"
                      />
                      <Input
                        label="Номер паспорта"
                        value={privateBuyerRfDraft.passportNumber}
                        onChange={(event) =>
                          setPrivateBuyerRfDraft((prev) => ({ ...prev, passportNumber: event.target.value }))
                        }
                        placeholder="654321"
                      />
                      <div className="md:col-span-2">
                        <Input
                          label="Кем выдан паспорт"
                          value={privateBuyerRfDraft.passportIssuedBy}
                          onChange={(event) =>
                            setPrivateBuyerRfDraft((prev) => ({ ...prev, passportIssuedBy: event.target.value }))
                          }
                        />
                      </div>
                      <Input
                        type="date"
                        label="Дата выдачи паспорта"
                        value={privateBuyerRfDraft.passportIssuedDate}
                        onChange={(event) =>
                          setPrivateBuyerRfDraft((prev) => ({ ...prev, passportIssuedDate: event.target.value }))
                        }
                      />
                      <Input
                        label="Код подразделения"
                        value={privateBuyerRfDraft.passportDepartmentCode}
                        onChange={(event) =>
                          setPrivateBuyerRfDraft((prev) => ({ ...prev, passportDepartmentCode: event.target.value }))
                        }
                        placeholder="000-000"
                      />
                      <div className="md:col-span-2">
                        <Input
                          label="Адрес регистрации"
                          value={privateBuyerRfDraft.registrationAddress}
                          onChange={(event) =>
                            setPrivateBuyerRfDraft((prev) => ({ ...prev, registrationAddress: event.target.value }))
                          }
                        />
                      </div>
                      <div className="md:col-span-2">
                        <Input
                          label="Адрес проживания (если отличается)"
                          value={privateBuyerRfDraft.residenceAddress}
                          onChange={(event) =>
                            setPrivateBuyerRfDraft((prev) => ({ ...prev, residenceAddress: event.target.value }))
                          }
                        />
                      </div>
                      <Input
                        label="Телефон"
                        value={privateBuyerRfDraft.phone}
                        onChange={(event) =>
                          setPrivateBuyerRfDraft((prev) => ({ ...prev, phone: event.target.value }))
                        }
                      />
                      <Input
                        type="email"
                        label="Email"
                        value={privateBuyerRfDraft.email}
                        onChange={(event) =>
                          setPrivateBuyerRfDraft((prev) => ({ ...prev, email: event.target.value }))
                        }
                      />
                    </div>
                  </div>
                )}

                <Input
                  label="Срок оплаты (дней)"
                  type="number"
                  min={1}
                  value={formData.paymentTerms}
                  onChange={(event) => setFormData((prev) => ({ ...prev, paymentTerms: event.target.value }))}
                />

                <label className="inline-flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
                  <input
                    type="checkbox"
                    checked={formData.includeDelivery}
                    onChange={(event) => setFormData((prev) => ({ ...prev, includeDelivery: event.target.checked }))}
                    className="h-4 w-4 text-blue-600"
                  />
                  Учитывать срок выполнения работ / поставки
                </label>

                {formData.includeDelivery && (
                  <Input
                    label="Срок выполнения (дата)"
                    type="date"
                    value={formData.deliveryDate}
                    onChange={(event) => setFormData((prev) => ({ ...prev, deliveryDate: event.target.value }))}
                  />
                )}

                {!isSupplyLegalEntitiesContract && (
                  <label className="inline-flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
                    <input
                      type="checkbox"
                      checked={formData.hasPrepayment}
                      onChange={(event) => setFormData((prev) => ({ ...prev, hasPrepayment: event.target.checked }))}
                      className="h-4 w-4 text-blue-600"
                    />
                    Использовать условие об авансе
                  </label>
                )}

                {!isSupplyLegalEntitiesContract && formData.hasPrepayment && (
                  <Input
                    label="Размер аванса, %"
                    type="number"
                    min={0.01}
                    max={100}
                    step="0.01"
                    value={formData.prepaymentPercent}
                    onChange={(event) => setFormData((prev) => ({ ...prev, prepaymentPercent: event.target.value }))}
                  />
                )}

                <Input
                  label="Пеня за просрочку, % в день"
                  type="number"
                  min={0}
                  step="0.01"
                  value={formData.penaltyPercentPerDay}
                  onChange={(event) => setFormData((prev) => ({ ...prev, penaltyPercentPerDay: event.target.value }))}
                />

                <Input
                  label="Номер договора"
                  value={formData.number}
                  disabled
                  className="bg-slate-100 dark:bg-slate-800 cursor-not-allowed"
                />
              </div>
            )}

            {step === 4 && (
              <div className="space-y-4">
                <div className="rounded-lg border border-green-200 bg-green-50/70 dark:bg-green-900/20 dark:border-green-900/60 p-4 text-sm text-green-900 dark:text-green-200">
                  {isPersonNoInvoiceMode
                    ? 'Документы готовы к генерации. Будет сформирован только договор купли-продажи (без счета).'
                    : 'Пакет документов готов к генерации. Счет и договор будут связаны в единую сделку.'}
                </div>

                {isPrivatePersonSaleContract && goodsSaleTemplateMissingFields.length > 0 && (
                  <div className="rounded-lg border border-amber-200 bg-amber-50/70 dark:bg-amber-900/20 dark:border-amber-900/60 p-4">
                    <p className="text-sm font-medium text-amber-900 dark:text-amber-200">
                      В шаблоне останутся заглушки/пустые поля, если не заполнить:
                    </p>
                    <ul className="mt-2 list-disc pl-5 text-xs text-amber-800 dark:text-amber-300 space-y-1">
                      {goodsSaleTemplateMissingFields.map((item) => (
                        <li key={`step4-missing-${item}`}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}

                <div className="grid grid-cols-1 gap-2">
                  {!isPersonNoInvoiceMode && (
                    <Button onClick={() => downloadInvoiceFile('pdf')} disabled={isGenerating} icon={<Icons.FileText className="w-4 h-4" />}>
                      {isGenerating ? 'Генерация...' : 'Скачать счет (PDF)'}
                    </Button>
                  )}
                  {!isPersonNoInvoiceMode && (
                    <Button variant="outline" onClick={() => downloadInvoiceFile('docx')} disabled={isGenerating} icon={<Icons.Download className="w-4 h-4" />}>
                      {isGenerating ? 'Генерация...' : 'Скачать счет (Word)'}
                    </Button>
                  )}
                  <Button onClick={() => downloadContractFile('pdf')} disabled={isGenerating} icon={<Icons.FileText className="w-4 h-4" />}>
                    {isGenerating ? 'Генерация...' : 'Скачать договор (PDF)'}
                  </Button>
                  <Button variant="outline" onClick={() => downloadContractFile('docx')} disabled={isGenerating} icon={<Icons.Download className="w-4 h-4" />}>
                    {isGenerating ? 'Генерация...' : 'Скачать договор (Word)'}
                  </Button>
                </div>

                <div className="border-t border-slate-200 dark:border-slate-700 pt-3 grid grid-cols-1 gap-2">
                  <Button variant="secondary" onClick={downloadArchive} disabled={isGenerating}>
                    {isGenerating ? 'Формирование архива...' : 'Скачать архивом'}
                  </Button>
                  <Button variant="outline" onClick={sendToEmail} disabled={isGenerating}>
                    Отправить контрагенту на email
                  </Button>
                  <Button variant="outline" onClick={exportToEdo} disabled={isGenerating}>
                    Выгрузить в ЭДО
                  </Button>
                </div>

                {createdContract && (
                  <div className="rounded-md border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 px-3 py-2 text-xs text-slate-600 dark:text-slate-300">
                    Сделка сохранена: договор {createdContract.number}, ID {createdContract.id}
                  </div>
                )}
              </div>
            )}
          </Card>

        </div>

        <div className="w-full lg:w-[66%] bg-slate-200 dark:bg-slate-900 rounded-xl border border-slate-300 dark:border-slate-800 overflow-y-auto p-4 md:p-8 shadow-inner">
          {selectedTemplate && (
            <div className="mb-4 rounded-md border border-slate-300 dark:border-slate-700 bg-white/80 dark:bg-slate-950/60 px-3 py-2 text-xs text-slate-600 dark:text-slate-300">
              Шаблон договора: <span className="font-medium">{selectedTemplate.name}</span> (v{selectedTemplate.version}).{' '}
              {isLiveTemplatePreviewLoading ? 'Обновляем live-preview…' : 'Экспорт и сохранение используют выбранный шаблон.'}
            </div>
          )}
          {selectedTemplate && liveTemplatePreviewError && (
            <div className="mb-4 rounded-md border border-amber-200 dark:border-amber-900/60 bg-amber-50/70 dark:bg-amber-900/20 px-3 py-2 text-xs text-amber-800 dark:text-amber-200">
              Live-preview шаблона недоступен: {liveTemplatePreviewError}. Показан типовой макет.
            </div>
          )}
          {step === 4 ? (
            <div className={`grid grid-cols-1 ${isPersonNoInvoiceMode ? '' : 'xl:grid-cols-2'} gap-8 items-start`}>
              {!isPersonNoInvoiceMode && (
                <section className="min-w-0">
                  <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3">Счет (слева)</h3>
                  <div className="overflow-auto rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 p-4">
                    <div className="transform scale-[0.55] sm:scale-[0.75] xl:scale-[0.82] 2xl:scale-100 origin-top transition-transform">
                      <style>{invoiceDocument.css}</style>
                      <div className="preview-root" dangerouslySetInnerHTML={{ __html: invoiceDocument.html }} />
                    </div>
                  </div>
                </section>
              )}

              <section className="min-w-0">
                <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3">Договор (справа)</h3>
                <div className="overflow-auto rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 p-4">
                  <div className="transform scale-[0.55] sm:scale-[0.75] xl:scale-[0.82] 2xl:scale-100 origin-top transition-transform">
                    {shouldRenderWizardContractSnapshot ? (
                      <>
                        {wizardContractPreviewCss && <style>{wizardContractPreviewCss}</style>}
                        <div className="preview-root" dangerouslySetInnerHTML={{ __html: wizardContractPreviewHtml || '' }} />
                      </>
                    ) : (
                      <ContractDocumentPreview
                        number={formData.number}
                        counterparty={previewCounterparty}
                        invoice={previewInvoice}
                        pricingConfig={pricingConfig}
                        settings={settings}
                        paymentTermsDays={Number(formData.paymentTerms || 10)}
                        hasPrepayment={paymentConfig.hasPrepayment}
                        prepaymentPercent={paymentConfig.prepaymentPercent}
                        penaltyPercentPerDay={Number(formData.penaltyPercentPerDay || 0)}
                        includeDelivery={formData.includeDelivery}
                        deliveryDate={formData.deliveryDate ? isoToRuDate(formData.deliveryDate) : null}
                      />
                    )}
                  </div>
                </div>
              </section>
            </div>
          ) : step === 2 && !isPersonNoInvoiceMode ? (
            <div>
              <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3">Предпросмотр счета</h3>
              <div className="overflow-auto rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 p-4">
                <div className="transform scale-[0.55] sm:scale-[0.75] xl:scale-100 origin-top transition-transform">
                  <style>{invoiceDocument.css}</style>
                  <div className="preview-root" dangerouslySetInnerHTML={{ __html: invoiceDocument.html }} />
                </div>
              </div>
            </div>
          ) : (
            <div className="flex items-start justify-center">
              <div className="transform scale-[0.6] sm:scale-[0.8] xl:scale-100 origin-top transition-transform">
                {shouldRenderWizardContractSnapshot ? (
                  <>
                    {wizardContractPreviewCss && <style>{wizardContractPreviewCss}</style>}
                    <div className="preview-root" dangerouslySetInnerHTML={{ __html: wizardContractPreviewHtml || '' }} />
                  </>
                ) : (
                  <ContractDocumentPreview
                    number={formData.number}
                    counterparty={previewCounterparty}
                    invoice={previewInvoice}
                    pricingConfig={pricingConfig}
                    settings={settings}
                    paymentTermsDays={Number(formData.paymentTerms || 10)}
                    hasPrepayment={paymentConfig.hasPrepayment}
                    prepaymentPercent={paymentConfig.prepaymentPercent}
                    penaltyPercentPerDay={Number(formData.penaltyPercentPerDay || 0)}
                    includeDelivery={formData.includeDelivery}
                    deliveryDate={formData.deliveryDate ? isoToRuDate(formData.deliveryDate) : null}
                  />
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
