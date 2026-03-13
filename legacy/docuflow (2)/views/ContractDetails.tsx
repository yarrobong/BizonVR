import React from 'react';
import { Badge, Button, Card } from '../components/ui';
import { Icons } from '../constants';
import { AppSettings, Contract, Invoice } from '../types';
import { ContractDocumentPreview, CONTRACT_DOCUMENT_CSS } from '../components/ContractDocumentPreview';
import { api } from '../services/api';
import {
  getVatModeLabel,
  getVatRateLabel,
  normalizePricingConfig,
} from '../utils/contractPricing';
import { buildContractDocumentName } from '../utils/documentNaming';

interface ContractDetailsProps {
  contract: Contract;
  invoice?: Invoice;
  settings: AppSettings | null;
  onBack: () => void;
}

const statusBadgeType = (status: Contract['status']): 'success' | 'warning' | 'neutral' => {
  if (status === 'Подписан') {
    return 'success';
  }

  if (status === 'На согласовании') {
    return 'warning';
  }

  return 'neutral';
};

export const ContractDetails: React.FC<ContractDetailsProps> = ({ contract, invoice, settings, onBack }) => {
  const snapshotHtml = contract.htmlSnapshot?.trim();
  const snapshotCss = contract.snapshotCss?.trim();
  const shouldRenderSnapshot = Boolean(snapshotHtml);
  const [downloadingFormat, setDownloadingFormat] = React.useState<'pdf' | 'docx' | null>(null);
  const pricingConfig = normalizePricingConfig({
    vatRate: invoice?.vatRate ?? contract.vatRate,
    vatMode: invoice?.vatMode ?? contract.vatMode,
    markupPercent: invoice?.commissionPercent ?? contract.markupPercent,
    markupMode: contract.markupMode,
    markupCalcMode: contract.markupCalcMode,
  });

  const downloadContractFile = async (format: 'pdf' | 'docx') => {
    setDownloadingFormat(format);

    try {
      const previewElement = document.getElementById('contract-details-content');
      const htmlForExport = (shouldRenderSnapshot ? snapshotHtml : null) || previewElement?.outerHTML;

      if (!htmlForExport) {
        throw new Error('Не удалось подготовить документ для скачивания.');
      }

      const blob = await api.generateContractFile(format, {
        html: htmlForExport,
        css: snapshotCss || CONTRACT_DOCUMENT_CSS,
        fileName: buildContractDocumentName(contract),
      });

      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `${buildContractDocumentName(contract)}.${format}`;
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
            Назад к договорам
          </button>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">Договор {contract.number}</h1>
        </div>
        <Badge type={statusBadgeType(contract.status)}>{contract.status}</Badge>
      </div>

      <Card className="p-5">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div>
            <div className="text-xs text-slate-500 dark:text-slate-400">Контрагент</div>
            <div className="text-sm font-medium text-slate-900 dark:text-slate-100">{contract.counterparty.name}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 dark:text-slate-400">Тип</div>
            <div className="text-sm font-medium text-slate-900 dark:text-slate-100">{contract.type}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 dark:text-slate-400">Дата создания</div>
            <div className="text-sm font-medium text-slate-900 dark:text-slate-100">{contract.createdAt}</div>
          </div>
          {typeof contract.amount === 'number' && (
            <div>
              <div className="text-xs text-slate-500 dark:text-slate-400">Сумма</div>
              <div className="text-sm font-medium text-slate-900 dark:text-slate-100">
                {contract.amount.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ₽
              </div>
            </div>
          )}
          {contract.invoiceId && (
            <div>
              <div className="text-xs text-slate-500 dark:text-slate-400">Счет</div>
              <div className="text-sm font-medium text-slate-900 dark:text-slate-100">{invoice?.number || contract.invoiceId}</div>
            </div>
          )}
          {contract.templateName && (
            <div>
              <div className="text-xs text-slate-500 dark:text-slate-400">Шаблон</div>
              <div className="text-sm font-medium text-slate-900 dark:text-slate-100">
                {contract.templateName}
                {contract.templateVersion ? ` (v${contract.templateVersion})` : ''}
              </div>
            </div>
          )}
          <div>
            <div className="text-xs text-slate-500 dark:text-slate-400">НДС</div>
            <div className="text-sm font-medium text-slate-900 dark:text-slate-100">
              {getVatRateLabel(pricingConfig.vatRate)} / {getVatModeLabel(pricingConfig.vatMode)}
            </div>
          </div>
        </div>
      </Card>

      <div className="bg-slate-200 dark:bg-slate-900 rounded-xl border border-slate-300 dark:border-slate-800 overflow-y-auto p-4 md:p-8 flex items-start justify-center shadow-inner">
        <div className="transform scale-[0.6] sm:scale-[0.8] xl:scale-100 origin-top transition-transform">
          {shouldRenderSnapshot ? (
            <>
              {snapshotCss && <style>{snapshotCss}</style>}
              <div className="preview-root" dangerouslySetInnerHTML={{ __html: snapshotHtml }} />
            </>
          ) : (
            <ContractDocumentPreview
              contentId="contract-details-content"
              number={contract.number}
              counterparty={contract.counterparty}
              invoice={invoice}
              supplierProfileId={contract.supplierProfileId}
              pricingConfig={pricingConfig}
              settings={settings}
            />
          )}
        </div>
      </div>

      <div className="flex flex-wrap justify-end gap-2">
        <Button
          variant="outline"
          onClick={() => downloadContractFile('docx')}
          icon={<Icons.Download className="w-4 h-4" />}
          disabled={Boolean(downloadingFormat)}
        >
          {downloadingFormat === 'docx' ? 'Генерация...' : 'Скачать Word'}
        </Button>
        <Button
          variant="outline"
          onClick={() => downloadContractFile('pdf')}
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
