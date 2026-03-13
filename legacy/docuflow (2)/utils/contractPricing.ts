import { Invoice, TaxCompensationCalculationMode, TaxCompensationMode, VatMode, VatRate } from '../types';

export interface PricingConfig {
  vatRate: VatRate;
  vatMode: VatMode;
  markupPercent: number;
  markupMode: TaxCompensationMode;
  markupCalcMode: TaxCompensationCalculationMode;
}

export interface PricedInvoiceItem {
  id: string;
  description: string;
  quantity: number;
  unit: string;
  unitPrice: number;
  lineTotal: number;
  isAdjustment?: boolean;
}

export interface InvoicePricingResult {
  config: PricingConfig;
  items: PricedInvoiceItem[];
  baseSubtotal: number;
  markupAmount: number;
  subtotalExcludingVat: number;
  vatAmount: number;
  vatRatePercent: number;
  total: number;
  hasSeparateMarkupLine: boolean;
}

const VAT_RATES: VatRate[] = ['none', '0', '10', '20'];
const VAT_MODES: VatMode[] = ['included', 'on_top'];
const MARKUP_MODES: TaxCompensationMode[] = ['per_item', 'separate_line', 'proportional_total'];
const MARKUP_CALC_MODES: TaxCompensationCalculationMode[] = ['simple', 'gross_up'];
const CURRENCY_SCALE = 100;

export const DEFAULT_PRICING_CONFIG: PricingConfig = {
  vatRate: 'none',
  vatMode: 'included',
  markupPercent: 6,
  markupMode: 'per_item',
  markupCalcMode: 'simple',
};

const VAT_RATE_LABELS: Record<VatRate, string> = {
  none: 'Без НДС',
  '0': '0%',
  '10': '10%',
  '20': '20%',
};

const VAT_MODE_LABELS: Record<VatMode, string> = {
  included: 'В том числе',
  on_top: 'Сверху',
};

const MARKUP_MODE_LABELS: Record<TaxCompensationMode, string> = {
  per_item: 'Скрытая в позициях',
  separate_line: 'Отдельной строкой',
  proportional_total: 'На всю сумму',
};

const MARKUP_CALC_MODE_LABELS: Record<TaxCompensationCalculationMode, string> = {
  simple: 'Простая наценка',
  gross_up: 'Умный расчет',
};

const isVatRate = (value: unknown): value is VatRate =>
  typeof value === 'string' && VAT_RATES.includes(value as VatRate);

const isVatMode = (value: unknown): value is VatMode =>
  typeof value === 'string' && VAT_MODES.includes(value as VatMode);

const isMarkupMode = (value: unknown): value is TaxCompensationMode =>
  typeof value === 'string' && MARKUP_MODES.includes(value as TaxCompensationMode);

const isMarkupCalcMode = (value: unknown): value is TaxCompensationCalculationMode =>
  typeof value === 'string' && MARKUP_CALC_MODES.includes(value as TaxCompensationCalculationMode);

const roundMoney = (value: number): number =>
  Math.round((value + Number.EPSILON) * CURRENCY_SCALE) / CURRENCY_SCALE;

const clampNumber = (value: number, min: number, max: number): number => Math.min(max, Math.max(min, value));

const toNonNegativeNumber = (value: unknown, fallback = 0): number => {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }

  return parsed < 0 ? 0 : parsed;
};

const getMarkupMultiplier = (config: PricingConfig): number => {
  const markupFactor = config.markupPercent / 100;
  if (markupFactor <= 0) {
    return 1;
  }

  if (config.markupCalcMode === 'gross_up') {
    const divisor = 1 - markupFactor;
    if (divisor > 0) {
      return 1 / divisor;
    }
  }

  return 1 + markupFactor;
};

const getTargetSubtotalWithMarkup = (baseSubtotal: number, config: PricingConfig): number => {
  if (baseSubtotal <= 0 || config.markupPercent <= 0) {
    return roundMoney(baseSubtotal);
  }

  return roundMoney(baseSubtotal * getMarkupMultiplier(config));
};

const distributeAmountProportionally = (weights: number[], amount: number): number[] => {
  if (weights.length === 0 || amount <= 0) {
    return weights.map(() => 0);
  }

  const totalWeight = weights.reduce((sum, value) => sum + value, 0);
  if (totalWeight <= 0) {
    return weights.map(() => 0);
  }

  const rawParts = weights.map((weight) => (weight / totalWeight) * amount);
  const flooredParts = rawParts.map((value) => Math.floor(value * CURRENCY_SCALE) / CURRENCY_SCALE);
  const floorSum = flooredParts.reduce((sum, value) => sum + value, 0);
  let remainderInCents = Math.round((amount - floorSum) * CURRENCY_SCALE);

  const fractions = rawParts
    .map((value, index) => ({ index, fraction: value - flooredParts[index] }))
    .sort((a, b) => b.fraction - a.fraction);

  for (let i = 0; i < remainderInCents; i += 1) {
    const target = fractions[i % fractions.length];
    flooredParts[target.index] = roundMoney(flooredParts[target.index] + 1 / CURRENCY_SCALE);
  }

  return flooredParts.map(roundMoney);
};

export const normalizePricingConfig = (config?: Partial<PricingConfig>): PricingConfig => {
  const rawMarkupPercent = Number(config?.markupPercent);
  const markupPercent = Number.isFinite(rawMarkupPercent)
    ? clampNumber(rawMarkupPercent, 0, 1000)
    : DEFAULT_PRICING_CONFIG.markupPercent;

  return {
    vatRate: isVatRate(config?.vatRate) ? config.vatRate : DEFAULT_PRICING_CONFIG.vatRate,
    vatMode: isVatMode(config?.vatMode) ? config.vatMode : DEFAULT_PRICING_CONFIG.vatMode,
    markupMode: isMarkupMode(config?.markupMode) ? config.markupMode : DEFAULT_PRICING_CONFIG.markupMode,
    markupCalcMode: isMarkupCalcMode(config?.markupCalcMode)
      ? config.markupCalcMode
      : DEFAULT_PRICING_CONFIG.markupCalcMode,
    markupPercent,
  };
};

export const vatRateToPercent = (vatRate: VatRate): number => {
  if (vatRate === 'none') {
    return 0;
  }

  const parsed = Number(vatRate);
  return Number.isFinite(parsed) ? parsed : 0;
};

export const getVatRateLabel = (vatRate: VatRate): string => VAT_RATE_LABELS[vatRate];
export const getVatModeLabel = (vatMode: VatMode): string => VAT_MODE_LABELS[vatMode];
export const getMarkupModeLabel = (mode: TaxCompensationMode): string => MARKUP_MODE_LABELS[mode];
export const getMarkupCalcModeLabel = (mode: TaxCompensationCalculationMode): string => MARKUP_CALC_MODE_LABELS[mode];

export const buildInvoicePricing = (
  invoice: Invoice | undefined,
  inputConfig?: Partial<PricingConfig>
): InvoicePricingResult => {
  const config = normalizePricingConfig(inputConfig);
  const rawItems = Array.isArray(invoice?.items) ? invoice.items : [];
  const baseItems = rawItems.map((item, index) => {
    const quantity = toNonNegativeNumber(item?.quantity, 0);
    const unitPrice = toNonNegativeNumber(item?.price, 0);
    const lineTotal = roundMoney(quantity * unitPrice);

    return {
      id: String(item?.id || `line-${index + 1}`),
      description: typeof item?.description === 'string' ? item.description : '',
      quantity,
      unit: typeof item?.unit === 'string' ? item.unit : '',
      unitPrice,
      lineTotal,
    };
  });

  const baseSubtotal = roundMoney(baseItems.reduce((sum, item) => sum + item.lineTotal, 0));
  const markupMultiplier = getMarkupMultiplier(config);
  const targetSubtotalWithMarkup = getTargetSubtotalWithMarkup(baseSubtotal, config);
  let markupAmount = 0;
  let pricedItems: PricedInvoiceItem[] = baseItems.map((item) => ({
    id: item.id,
    description: item.description,
    quantity: item.quantity,
    unit: item.unit,
    unitPrice: roundMoney(item.unitPrice),
    lineTotal: item.lineTotal,
  }));

  if (config.markupMode === 'per_item') {
    pricedItems = baseItems.map((item) => {
      const adjustedUnitPrice = roundMoney(item.unitPrice * markupMultiplier);
      const lineTotal = roundMoney(adjustedUnitPrice * item.quantity);
      return {
        id: item.id,
        description: item.description,
        quantity: item.quantity,
        unit: item.unit,
        unitPrice: adjustedUnitPrice,
        lineTotal,
      };
    });

    const subtotal = roundMoney(pricedItems.reduce((sum, item) => sum + item.lineTotal, 0));
    markupAmount = roundMoney(subtotal - baseSubtotal);
  } else if (config.markupMode === 'separate_line') {
    markupAmount = roundMoney(targetSubtotalWithMarkup - baseSubtotal);
    if (markupAmount > 0) {
      pricedItems = [
        ...pricedItems,
        {
          id: 'markup-line',
          description: 'Компенсация налога',
          quantity: 1,
          unit: 'усл.',
          unitPrice: markupAmount,
          lineTotal: markupAmount,
          isAdjustment: true,
        },
      ];
    }
  } else if (config.markupMode === 'proportional_total') {
    const targetSubtotal = targetSubtotalWithMarkup;
    markupAmount = roundMoney(targetSubtotal - baseSubtotal);

    if (markupAmount > 0 && baseSubtotal > 0) {
      const baseLineTotals = baseItems.map((item) => item.lineTotal);
      const distributedMarkup = distributeAmountProportionally(baseLineTotals, markupAmount);

      pricedItems = baseItems.map((item, index) => {
        const lineTotal = roundMoney(item.lineTotal + distributedMarkup[index]);
        const unitPrice =
          item.quantity > 0 ? roundMoney(lineTotal / item.quantity) : roundMoney(item.unitPrice * markupMultiplier);

        return {
          id: item.id,
          description: item.description,
          quantity: item.quantity,
          unit: item.unit,
          unitPrice,
          lineTotal,
        };
      });

      const distributedSubtotal = roundMoney(pricedItems.reduce((sum, item) => sum + item.lineTotal, 0));
      const roundingDelta = roundMoney(targetSubtotal - distributedSubtotal);

      if (roundingDelta !== 0 && pricedItems.length > 0) {
        const lastIndex = pricedItems.length - 1;
        const updatedLineTotal = roundMoney(pricedItems[lastIndex].lineTotal + roundingDelta);
        const quantity = pricedItems[lastIndex].quantity;
        pricedItems[lastIndex] = {
          ...pricedItems[lastIndex],
          lineTotal: updatedLineTotal,
          unitPrice: quantity > 0 ? roundMoney(updatedLineTotal / quantity) : updatedLineTotal,
        };
      }
    }

    const subtotal = roundMoney(pricedItems.reduce((sum, item) => sum + item.lineTotal, 0));
    markupAmount = roundMoney(subtotal - baseSubtotal);
  }

  const subtotalExcludingVat = roundMoney(pricedItems.reduce((sum, item) => sum + item.lineTotal, 0));
  const vatRatePercent = vatRateToPercent(config.vatRate);
  let vatAmount = 0;
  let total = subtotalExcludingVat;

  if (vatRatePercent > 0) {
    if (config.vatMode === 'on_top') {
      vatAmount = roundMoney(subtotalExcludingVat * (vatRatePercent / 100));
      total = roundMoney(subtotalExcludingVat + vatAmount);
    } else {
      vatAmount = roundMoney(subtotalExcludingVat * (vatRatePercent / (100 + vatRatePercent)));
    }
  }

  return {
    config,
    items: pricedItems,
    baseSubtotal,
    markupAmount,
    subtotalExcludingVat,
    vatAmount,
    vatRatePercent,
    total,
    hasSeparateMarkupLine: config.markupMode === 'separate_line' && markupAmount > 0,
  };
};
