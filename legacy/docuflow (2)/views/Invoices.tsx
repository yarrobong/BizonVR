import React from 'react';
import { Card, Button, Badge } from '../components/ui';
import { Icons } from '../constants';
import { Invoice } from '../types';

interface InvoicesProps {
  invoices: Invoice[];
}

export const Invoices: React.FC<InvoicesProps> = ({ invoices }) => {
  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">Счета</h1>
          <p className="text-slate-500 dark:text-slate-400">Управление счетами на оплату и привязка к договорам.</p>
        </div>
        <Button icon={<Icons.Plus className="w-4 h-4" />}>Создать счет</Button>
      </div>

      <Card className="overflow-hidden">
        <div className="hidden md:block overflow-x-auto">
          <table className="w-full text-left text-sm text-slate-600 dark:text-slate-400">
            <thead className="bg-slate-50 dark:bg-slate-800 text-slate-900 dark:text-slate-200 font-medium">
              <tr>
                <th className="px-6 py-3">Номер счета</th>
                <th className="px-6 py-3">Дата</th>
                <th className="px-6 py-3">Сумма</th>
                <th className="px-6 py-3">Позиции</th>
                <th className="px-6 py-3">Статус</th>
                <th className="px-6 py-3 text-right">Действия</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
              {invoices.map((inv) => (
                <tr key={inv.id} className="hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors">
                  <td className="px-6 py-4 font-mono font-medium text-slate-900 dark:text-slate-100">{inv.number}</td>
                  <td className="px-6 py-4">{inv.date}</td>
                  <td className="px-6 py-4 font-medium text-slate-900 dark:text-slate-100">
                    {inv.amount.toLocaleString('ru-RU', { style: 'currency', currency: inv.currency, maximumFractionDigits: 0 })}
                  </td>
                  <td className="px-6 py-4">{inv.items.length} поз.</td>
                  <td className="px-6 py-4">
                    <Badge type={inv.status === 'Оплачен' ? 'success' : 'warning'}>{inv.status}</Badge>
                  </td>
                  <td className="px-6 py-4 text-right">
                    <div className="flex justify-end gap-2">
                       <button className="text-slate-400 hover:text-blue-600 dark:hover:text-blue-400" title="Скачать">
                         <Icons.Download className="w-4 h-4" />
                       </button>
                       <button className="text-slate-400 hover:text-blue-600 dark:hover:text-blue-400" title="Редактировать">
                         <Icons.Edit className="w-4 h-4" />
                       </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Mobile View */}
        <div className="md:hidden divide-y divide-slate-200 dark:divide-slate-800">
          {invoices.map((inv) => (
            <div key={inv.id} className="p-4">
              <div className="flex justify-between items-start mb-2">
                <div>
                   <div className="font-mono text-sm font-bold text-slate-900 dark:text-slate-100">{inv.number}</div>
                   <div className="text-xs text-slate-500 dark:text-slate-500">{inv.date}</div>
                </div>
                <Badge type={inv.status === 'Оплачен' ? 'success' : 'warning'}>{inv.status}</Badge>
              </div>
              <div className="flex justify-between items-end">
                <div className="text-sm">
                   <span className="block text-slate-500 dark:text-slate-400">{inv.items.length} позиций</span>
                   <span className="font-bold text-slate-900 dark:text-slate-100 text-lg">
                      {inv.amount.toLocaleString('ru-RU', { style: 'currency', currency: inv.currency, maximumFractionDigits: 0 })}
                   </span>
                </div>
                <Button variant="ghost" size="sm" className="text-blue-600 dark:text-blue-400">Подробнее</Button>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
};
