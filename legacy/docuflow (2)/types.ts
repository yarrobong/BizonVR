// Enums
export enum ContractStatus {
  DRAFT = 'Черновик',
  PENDING_APPROVAL = 'На согласовании',
  SIGNED = 'Подписан',
  EXPIRED = 'Истек',
}

export enum ContractType {
  SUPPLY = 'Договор поставки',
  SERVICE = 'Договор оказания услуг',
  NDA = 'Соглашение о конфиденциальности (NDA)',
  RENTAL = 'Договор аренды',
}

export type VatRate = 'none' | '0' | '10' | '20';
export type VatMode = 'included' | 'on_top';
export type TaxCompensationMode = 'per_item' | 'separate_line' | 'proportional_total';
export type TaxCompensationCalculationMode = 'simple' | 'gross_up';
export type CounterpartyLegalType = 'ooo' | 'ao' | 'ip' | 'person';
export type SupplierLegalType = 'ooo' | 'ip' | 'person';

export interface BankAccount {
  bankName: string;
  checkingAccount: string;
  correspondentAccount: string;
  bik: string;
  cardNumber?: string;
  sbpPhone?: string;
}

export interface SupplierCompanyProfile {
  id: string;
  legalType: SupplierLegalType;
  companyName: string;
  inn: string;
  kpp: string;
  ogrn: string;
  ogrnip: string;
  directorGenitive: string;
  legalAddress: string;
  email: string;
  phone: string;
  bankName: string;
  bik: string;
  correspondentAccount: string;
  checkingAccount: string;
  cardNumber?: string;
  sbpPhone?: string;
  bankAccounts?: BankAccount[];
  passportSeries?: string;
  passportNumber?: string;
  passportIssuedBy?: string;
  passportIssuedDate?: string;
  passportDepartmentCode?: string;
  registrationAddress?: string;
  residenceAddress?: string;
}

export interface PrivatePersonRfProfile {
  fullName: string;
  passportSeries: string;
  passportNumber: string;
  passportIssuedBy: string;
  passportIssuedDate: string;
  passportDepartmentCode: string;
  registrationAddress: string;
  residenceAddress: string;
  phone: string;
  email: string;
  bankName: string;
  cardNumber: string;
  sbpPhone: string;
  bik: string;
  checkingAccount: string;
  correspondentAccount: string;
}

// Interfaces
export interface User {
  id: string;
  name: string;
  role: 'Администратор' | 'Менеджер' | 'Бухгалтер';
  avatar?: string;
}

export interface Counterparty {
  id: string;
  name: string;
  inn: string;
  address: string;
  contactPerson: string;
  email: string;
  phone?: string;
  legalType?: CounterpartyLegalType;
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

export interface InvoiceItem {
  id: string;
  description: string;
  quantity: number;
  price: number;
  unit: string;
}

export interface Invoice {
  id: string;
  number: string;
  date: string;
  paymentDueDate?: string;
  amount: number;
  currency: string;
  items: InvoiceItem[];
  status: 'Оплачен' | 'Не оплачен';
  counterpartyId?: string;
  commissionPercent?: number;
  vatRate?: VatRate;
  vatMode?: VatMode;
  supplierProfileId?: string;
  supplierBankAccount?: BankAccount;
}

export interface Contract {
  id: string;
  number: string;
  title: string;
  type: ContractType;
  counterparty: Counterparty;
  status: ContractStatus;
  createdAt: string;
  amount?: number;
  fileUrl?: string; // Mock URL
  supplierProfileId?: string;
  invoiceId?: string;
  paymentTerms?: number;
  includeDelivery?: boolean;
  deliveryDate?: string | null;
  vatRate?: VatRate;
  vatMode?: VatMode;
  markupPercent?: number;
  markupMode?: TaxCompensationMode;
  markupCalcMode?: TaxCompensationCalculationMode;
  templateId?: string;
  templateName?: string;
  templateVersion?: string;
  contractData?: Record<string, unknown>;
  htmlSnapshot?: string;
  snapshotCss?: string;
}

export interface TemplateVariable {
  key: string;
  description: string;
  sourceTable: string;
}

export interface Template {
  id: string;
  name: string;
  type: ContractType;
  version: string;
  updatedAt: string;
  isActive: boolean;
  content: string;
  css: string;
  variables: TemplateVariable[];
}

// Navigation
export type View =
  | 'dashboard'
  | 'contracts'
  | 'create-contract'
  | 'contract-details'
  | 'invoice-details'
  | 'templates'
  | 'invoices'
  | 'settings';

export interface DashboardStats {
  totalContracts: number;
  pendingContracts: number;
  paidInvoicesAmount: number;
}

export interface AppSettings {
  legalType: SupplierLegalType;
  companyName: string;
  inn: string;
  kpp: string;
  ogrn: string;
  ogrnip: string;
  directorGenitive: string;
  legalAddress: string;
  email: string;
  phone: string;
  bankName: string;
  bik: string;
  correspondentAccount: string;
  checkingAccount: string;
  cardNumber?: string;
  sbpPhone?: string;
  bankAccounts?: BankAccount[];
  companyProfiles?: SupplierCompanyProfile[];
  activeCompanyProfileId?: string;
  privateSellerRf?: PrivatePersonRfProfile;
  defaultCurrency: 'RUB' | 'USD' | 'EUR';
  autoNumbering: boolean;
}
