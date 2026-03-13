import React from 'react';
import { Card, Button, Badge } from '../components/ui';
import { Icons } from '../constants';
import { Contract, View, ContractStatus, DashboardStats } from '../types';

interface DashboardProps {
  onNavigate: (view: View) => void;
  onOpenContract: (contractId: string) => void;
  contracts: Contract[];
  stats: DashboardStats | null;
}

export const Dashboard: React.FC<DashboardProps> = ({
  onNavigate,
  onOpenContract,
  contracts,
  stats: dashboardStats,
}) => {
  const pendingContracts =
    dashboardStats?.pendingContracts ??
    contracts.filter((contract) => contract.status === ContractStatus.PENDING_APPROVAL).length;
  const paidInvoicesAmount =
    dashboardStats?.paidInvoicesAmount ??
    contracts.reduce((sum, contract) => sum + Number(contract.amount || 0), 0);

  const cards = [
    { label: 'Всего договоров', value: String(dashboardStats?.totalContracts ?? contracts.length), change: 'акт.', color: 'text-blue-600' },
    { label: 'На согласовании', value: String(pendingContracts), change: 'акт.', color: 'text-amber-600' },
    {
      label: 'Оплачено по счетам',
      value: `${paidInvoicesAmount.toLocaleString('ru-RU')} ₽`,
      change: 'акт.',
      color: 'text-green-600',
    },
  ];

  const recentContracts = contracts.slice(0, 5);

  const getStatusBadge = (status: ContractStatus) => {
    switch (status) {
      case ContractStatus.SIGNED: return <Badge type="success">Подписан</Badge>;
      case ContractStatus.PENDING_APPROVAL: return <Badge type="warning">На согласовании</Badge>;
      case ContractStatus.DRAFT: return <Badge type="neutral">Черновик</Badge>;
      default: return <Badge>Неизвестно</Badge>;
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">Дашборд</h1>
          <p className="text-slate-500 dark:text-slate-400">С возвращением, Алексей. Вот сводка за сегодня.</p>
        </div>
        <div className="flex gap-2">
           <Button variant="outline" onClick={() => onNavigate('invoices')}>Выставить счет</Button>
           <Button icon={<Icons.Plus className="w-4 h-4" />} onClick={() => onNavigate('create-contract')}>Новый договор</Button>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {cards.map((stat, idx) => (
          <Card key={idx} className="p-6">
            <p className="text-sm font-medium text-slate-500 dark:text-slate-400">{stat.label}</p>
            <div className="flex items-baseline gap-2 mt-2">
              <span className="text-3xl font-bold text-slate-900 dark:text-slate-100">{stat.value}</span>
              <span className={`text-sm font-medium ${stat.color}`}>{stat.change}</span>
            </div>
          </Card>
        ))}
      </div>

      {/* Recent Contracts */}
      <Card className="overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-800 flex justify-between items-center">
          <h3 className="font-semibold text-slate-800 dark:text-slate-200">Последние договоры</h3>
          <button 
            onClick={() => onNavigate('contracts')} 
            className="text-sm text-blue-600 hover:text-blue-700 font-medium"
          >
            Все договоры
          </button>
        </div>
        
        {/* Desktop Table */}
        <div className="hidden md:block overflow-x-auto">
          <table className="w-full text-left text-sm text-slate-600 dark:text-slate-400">
            <thead className="bg-slate-50 dark:bg-slate-800 text-slate-900 dark:text-slate-200 font-medium">
              <tr>
                <th className="px-6 py-3">Номер</th>
                <th className="px-6 py-3">Название</th>
                <th className="px-6 py-3">Контрагент</th>
                <th className="px-6 py-3">Статус</th>
                <th className="px-6 py-3">Дата</th>
                <th className="px-6 py-3 text-right">Действия</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
              {recentContracts.map((contract) => (
                <tr key={contract.id} className="hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors">
                  <td className="px-6 py-4 font-mono text-slate-900 dark:text-slate-200">{contract.number}</td>
                  <td className="px-6 py-4">{contract.title}</td>
                  <td className="px-6 py-4">{contract.counterparty.name}</td>
                  <td className="px-6 py-4">{getStatusBadge(contract.status)}</td>
                  <td className="px-6 py-4">{contract.createdAt}</td>
                  <td className="px-6 py-4 text-right">
                    <button
                      onClick={() => onOpenContract(contract.id)}
                      className="text-slate-400 hover:text-blue-600 dark:hover:text-blue-400"
                    >
                      <Icons.FileText className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Mobile List */}
        <div className="md:hidden divide-y divide-slate-200 dark:divide-slate-800">
          {recentContracts.map((contract) => (
            <div key={contract.id} className="p-4 flex flex-col gap-2">
              <div className="flex justify-between items-start">
                <div>
                  <div className="font-mono text-xs text-slate-500 dark:text-slate-500 mb-1">{contract.number}</div>
                  <div className="font-medium text-slate-900 dark:text-slate-200">{contract.title}</div>
                  <div className="text-sm text-slate-600 dark:text-slate-400">{contract.counterparty.name}</div>
                </div>
                {getStatusBadge(contract.status)}
              </div>
              <div className="flex justify-between items-center mt-2 pt-2 border-t border-slate-100 dark:border-slate-800">
                <span className="text-xs text-slate-500 dark:text-slate-500">{contract.createdAt}</span>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-blue-600 dark:text-blue-400"
                  onClick={() => onOpenContract(contract.id)}
                >
                  Открыть
                </Button>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
};
