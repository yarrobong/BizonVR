import {
  AppSettings,
  BankAccount,
  Contract,
  ContractType,
  Counterparty,
  CounterpartyLegalType,
  DashboardStats,
  Invoice,
  InvoiceItem,
  TaxCompensationCalculationMode,
  TaxCompensationMode,
  Template,
  TemplateVariable,
  VatMode,
  VatRate,
} from '../../../types';

export type FileFormat = 'pdf' | 'docx';

export interface BootstrapResponse {
  contracts: Contract[];
  counterparties: Counterparty[];
  invoices: Invoice[];
  templates: Template[];
  templateVariables?: TemplateVariable[];
  settings: AppSettings;
  stats: DashboardStats;
}

export interface CreateContractPayload {
  type: ContractType;
  counterpartyId: string;
  invoiceId?: string;
  amount?: number;
  paymentTerms?: number;
  includeDelivery?: boolean;
  deliveryDate?: string | null;
  number?: string;
  vatRate?: VatRate;
  vatMode?: VatMode;
  markupPercent?: number;
  markupMode?: TaxCompensationMode;
  markupCalcMode?: TaxCompensationCalculationMode;
  templateId?: string;
  contractData?: Record<string, unknown>;
}

export interface UpdateContractPayload {
  type?: ContractType;
  counterpartyId?: string;
  invoiceId?: string | null;
  amount?: number | null;
  paymentTerms?: number;
  includeDelivery?: boolean;
  deliveryDate?: string | null;
  number?: string;
  status?: Contract['status'];
  title?: string;
  vatRate?: VatRate;
  vatMode?: VatMode;
  markupPercent?: number;
  markupMode?: TaxCompensationMode;
  markupCalcMode?: TaxCompensationCalculationMode;
  templateId?: string;
  contractData?: Record<string, unknown>;
}

export interface ContractTemplatePreviewPayload {
  type: ContractType;
  templateId?: string;
  number?: string;
  amount?: number;
  paymentTerms?: number;
  includeDelivery?: boolean;
  deliveryDate?: string | null;
  vatRate?: VatRate;
  vatMode?: VatMode;
  markupPercent?: number;
  markupMode?: TaxCompensationMode;
  markupCalcMode?: TaxCompensationCalculationMode;
  contractData?: Record<string, unknown>;
  counterparty?: Partial<Counterparty> | null;
  invoice?: Partial<Invoice> | null;
}

export interface ContractTemplatePreviewResponse {
  html: string;
  css: string;
  templateId: string;
  templateName: string;
  templateVersion?: string;
}

export interface CreateCounterpartyPayload {
  legalType: CounterpartyLegalType;
  name: string;
  inn: string;
  address: string;
  contactPerson: string;
  email: string;
  phone?: string;
  directorName?: string;
  ogrn?: string;
  kpp?: string;
  ogrnip?: string;
  passportSeries?: string;
  passportNumber?: string;
  passportIssuedBy?: string;
  passportIssuedDate?: string;
  passportDepartmentCode?: string;
  registrationAddress?: string;
  residenceAddress?: string;
  bankName?: string;
  checkingAccount?: string;
  correspondentAccount?: string;
  bik?: string;
  bankAccounts?: BankAccount[];
}

export type UpdateCounterpartyPayload = Partial<CreateCounterpartyPayload>;

export interface CreateInvoicePayload {
  number?: string;
  date?: string;
  paymentDueDate?: string;
  amount?: number;
  currency?: string;
  status?: Invoice['status'];
  commissionPercent?: number;
  vatRate?: VatRate;
  vatMode?: VatMode;
  supplierProfileId?: string;
  supplierBankAccount?: BankAccount;
  items?: Array<Omit<InvoiceItem, 'id'>>;
  counterpartyId?: string;
}

export interface UpdateInvoicePayload {
  number?: string;
  date?: string;
  paymentDueDate?: string | null;
  amount?: number;
  currency?: string;
  status?: Invoice['status'];
  commissionPercent?: number;
  vatRate?: VatRate;
  vatMode?: VatMode;
  supplierProfileId?: string | null;
  supplierBankAccount?: BankAccount | null;
  items?: Array<Partial<InvoiceItem>>;
  counterpartyId?: string | null;
}

export interface CreateTemplatePayload {
  name: string;
  type: ContractType;
  content?: string;
  css?: string;
  isActive?: boolean;
  variables?: TemplateVariable[];
}

export interface UpdateTemplatePayload {
  name?: string;
  type?: ContractType;
  content?: string;
  css?: string;
  isActive?: boolean;
  variables?: TemplateVariable[];
}

export interface CounterpartyLookupResponse {
  found: boolean;
  source: 'db' | 'none';
  counterparty?: Counterparty;
}
