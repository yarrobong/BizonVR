import React from 'react';
import { Badge, Button, Card } from '../components/ui';
import { Icons } from '../constants';
import { AppSettings, Counterparty, Invoice } from '../types';
import { api } from '../services/api';
import { buildInvoiceDocumentName } from '../utils/documentNaming';
import { buildInvoiceDocument, INVOICE_LOGO_URL } from '../utils/invoiceDocument';

interface InvoiceDetailsProps {
  invoice: Invoice;
  counterparty?: Counterparty;
  settings: AppSettings | null;
  onBack: () => void;
}

const getInvoiceBadgeType = (status: Invoice['status']): 'success' | 'warning' =>
  status === 'Оплачен' ? 'success' : 'warning';

const formatMoney = (amount: number, currency: string) =>
  amount.toLocaleString('ru-RU', { style: 'currency', currency, maximumFractionDigits: 2 });

const resolveAbsoluteLogoUrl = () => {
  if (typeof window === 'undefined') {
    return INVOICE_LOGO_URL;
  }

  if (/^https?:\/\//i.test(INVOICE_LOGO_URL) || INVOICE_LOGO_URL.startsWith('data:')) {
    return INVOICE_LOGO_URL;
  }

  return new URL(INVOICE_LOGO_URL, window.location.origin).toString();
};

export const InvoiceDetails: React.FC<InvoiceDetailsProps> = ({ invoice, counterparty, settings, onBack }) => {
  const [downloadingFormat, setDownloadingFormat] = React.useState<'pdf' | 'docx' | null>(null);

  const invoiceDocument = React.useMemo(
    () =>
      buildInvoiceDocument({
        invoice,
        counterparty,
        settings,
        logoSrc: INVOICE_LOGO_URL,
      }),
    [invoice, counterparty, settings],
  );

  const fileName = React.useMemo(
    () => buildInvoiceDocumentName(invoice, counterparty?.name),
    [invoice, counterparty?.name],
  );

  const downloadInvoiceFile = async (format: 'pdf' | 'docx') => {
    setDownloadingFormat(format);
    try {
      const exportDocument = buildInvoiceDocument({
        invoice,
        counterparty,
        settings,
        logoSrc: resolveAbsoluteLogoUrl(),
      });

      const blob = await api.generateContractFile(format, {
        html: exportDocument.html,
        css: exportDocument.css,
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
      console.error(error);
      const message = error instanceof Error ? error.message : `Ошибка скачивания ${format.toUpperCase()}`;
      alert(message);
    } finally {
      setDownloadingFormat(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div className="space-y-2">
          <button
            onClick={onBack}
            className="text-sm text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200 inline-flex items-center"
          >
            <Icons.ChevronRight className="w-4 h-4 rotate-180 mr-1" />
            Назад к счетам
          </button>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">Счет {invoice.number}</h1>
        </div>
        <Badge type={getInvoiceBadgeType(invoice.status)}>{invoice.status}</Badge>
      </div>

      <Card className="p-5">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-5">
          <div>
            <div className="text-xs text-slate-500 dark:text-slate-400">Контрагент</div>
            <div className="text-sm font-medium text-slate-900 dark:text-slate-100">{counterparty?.name || 'Не выбран'}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 dark:text-slate-400">Дата счета</div>
            <div className="text-sm font-medium text-slate-900 dark:text-slate-100">{invoice.date}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 dark:text-slate-400">Оплатить до</div>
            <div className="text-sm font-medium text-slate-900 dark:text-slate-100">{invoice.paymentDueDate || 'Не указан'}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 dark:text-slate-400">Сумма</div>
            <div className="text-sm font-medium text-slate-900 dark:text-slate-100">
              {formatMoney(invoice.amount, invoice.currency)}
            </div>
          </div>
          <div>
            <div className="text-xs text-slate-500 dark:text-slate-400">Позиции</div>
            <div className="text-sm font-medium text-slate-900 dark:text-slate-100">{invoice.items.length}</div>
          </div>
        </div>
      </Card>

      <div className="bg-slate-200 dark:bg-slate-900 rounded-xl border border-slate-300 dark:border-slate-800 overflow-y-auto p-4 md:p-8 flex items-start justify-center shadow-inner">
        <div className="transform scale-[0.58] sm:scale-[0.78] xl:scale-100 origin-top transition-transform">
          <style>{invoiceDocument.css}</style>
          <div className="preview-root" dangerouslySetInnerHTML={{ __html: invoiceDocument.html }} />
        </div>
      </div>

      <div className="flex flex-wrap justify-end gap-2">
        <Button
          variant="outline"
          onClick={() => downloadInvoiceFile('docx')}
          icon={<Icons.Download className="w-4 h-4" />}
          disabled={Boolean(downloadingFormat)}
        >
          {downloadingFormat === 'docx' ? 'Генерация...' : 'Скачать Word'}
        </Button>
        <Button
          variant="outline"
          onClick={() => downloadInvoiceFile('pdf')}
          icon={<Icons.FileText className="w-4 h-4" />}
          disabled={Boolean(downloadingFormat)}
        >
          {downloadingFormat === 'pdf' ? 'Генерация...' : 'Скачать PDF'}
        </Button>
        <Button variant="outline" onClick={onBack} icon={<Icons.ChevronRight className="w-4 h-4 rotate-180" />}>
          Вернуться к списку
        </Button>
      </div>
    </div>
  );
};
