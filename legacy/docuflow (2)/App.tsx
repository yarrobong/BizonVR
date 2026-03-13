import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Layout } from './components/Layout';
import { Dashboard } from './views/Dashboard';
import { ContractWizard } from './views/ContractWizard';
import { ContractDetails } from './views/ContractDetails';
import { InvoiceDetails } from './views/InvoiceDetails';
import { Templates } from './views/Templates';
import { DocumentsByCounterparty, type DocumentFilter } from './views/DocumentsByCounterparty';
import { Settings } from './views/Settings';
import { AppSettings, Contract, Counterparty, DashboardStats, Invoice, Template, TemplateVariable, View } from './types';
import { Card } from './components/ui';
import {
  api,
  BootstrapResponse,
  CreateCounterpartyPayload,
  CreateInvoicePayload,
  CreateTemplatePayload,
  UpdateContractPayload,
  UpdateCounterpartyPayload,
  UpdateInvoicePayload,
  UpdateTemplatePayload,
} from './services/api';

type InvoiceBackFilter = DocumentFilter;

interface AppRouteState {
  view: View;
  documentsFilter: DocumentFilter;
  selectedContractId: string | null;
  selectedInvoiceId: string | null;
  invoiceBackFilter: InvoiceBackFilter;
}

const DEFAULT_ROUTE_STATE: AppRouteState = {
  view: 'dashboard',
  documentsFilter: 'all',
  selectedContractId: null,
  selectedInvoiceId: null,
  invoiceBackFilter: 'all',
};

const APP_BASENAME = (import.meta.env.VITE_APP_BASENAME || '/').replace(/\/+$/, '') || '/';

const normalizePathname = (pathname: string) => {
  const normalized = pathname.replace(/\/+$/, '');
  return normalized.length > 0 ? normalized : '/';
};

const stripBasename = (pathname: string) => {
  const normalizedPath = normalizePathname(pathname);
  if (APP_BASENAME === '/') {
    return normalizedPath;
  }
  if (
    normalizedPath === APP_BASENAME ||
    normalizedPath.startsWith(`${APP_BASENAME}/`)
  ) {
    const stripped = normalizedPath.slice(APP_BASENAME.length);
    return stripped || '/';
  }
  return normalizedPath;
};

const withBasename = (pathname: string) => {
  const normalizedPath = normalizePathname(pathname);
  if (APP_BASENAME === '/') {
    return normalizedPath;
  }
  if (normalizedPath === '/') {
    return APP_BASENAME;
  }
  return `${APP_BASENAME}${normalizedPath}`;
};

const decodePathSegment = (segment: string) => {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
};

const parseDocumentFilter = (value?: string | null): DocumentFilter => {
  const normalized = String(value || '').trim().toLowerCase();
  if (normalized === 'contracts') {
    return 'contracts';
  }
  if (normalized === 'invoices') {
    return 'invoices';
  }
  if (normalized === 'counterparties') {
    return 'counterparties';
  }
  return 'all';
};

const buildDocumentsPath = (filter: DocumentFilter): string => {
  if (filter === 'contracts') {
    return '/documents/contracts';
  }
  if (filter === 'invoices') {
    return '/documents/invoices';
  }
  if (filter === 'counterparties') {
    return '/documents/counterparties';
  }
  return '/documents/all';
};

const buildPathFromRoute = (route: AppRouteState): string => {
  if (route.view === 'dashboard') {
    return '/dashboard';
  }
  if (route.view === 'contracts' || route.view === 'invoices') {
    return buildDocumentsPath(route.documentsFilter);
  }
  if (route.view === 'create-contract') {
    const params = new URLSearchParams();
    if (route.selectedInvoiceId) {
      params.set('invoice', route.selectedInvoiceId);
    }
    const query = params.toString();
    return query ? `/documents/new?${query}` : '/documents/new';
  }
  if (route.view === 'templates') {
    return '/templates';
  }
  if (route.view === 'settings') {
    return '/settings';
  }
  if (route.view === 'contract-details') {
    if (!route.selectedContractId) {
      return buildDocumentsPath(route.documentsFilter);
    }
    return `/contracts/${encodeURIComponent(route.selectedContractId)}`;
  }
  if (route.view === 'invoice-details') {
    if (!route.selectedInvoiceId) {
      return buildDocumentsPath(route.documentsFilter);
    }
    const backFilter = parseDocumentFilter(route.invoiceBackFilter);
    return `/invoices/${encodeURIComponent(route.selectedInvoiceId)}?from=${encodeURIComponent(backFilter)}`;
  }
  return '/dashboard';
};

const getCurrentPathWithSearch = () =>
  typeof window === 'undefined'
    ? '/dashboard'
    : `${stripBasename(window.location.pathname)}${window.location.search}`;

const parseRouteFromLocation = (pathname: string, search: string): AppRouteState => {
  const normalizedPath = normalizePathname(pathname);
  const segments = normalizedPath.split('/').filter(Boolean).map(decodePathSegment);
  const params = new URLSearchParams(search);

  if (segments.length === 0) {
    return { ...DEFAULT_ROUTE_STATE };
  }

  if (segments[0] === 'dashboard' || segments[0] === 'dashbozrd') {
    return { ...DEFAULT_ROUTE_STATE, view: 'dashboard' };
  }

  if (segments[0] === 'documents') {
    const section = String(segments[1] || 'all').toLowerCase();
    if (section === 'new' || section === 'create') {
      return {
        ...DEFAULT_ROUTE_STATE,
        view: 'create-contract',
        selectedInvoiceId: params.get('invoice'),
      };
    }

    const filter = parseDocumentFilter(section);
    return {
      ...DEFAULT_ROUTE_STATE,
      view: filter === 'invoices' ? 'invoices' : 'contracts',
      documentsFilter: filter,
      invoiceBackFilter: filter,
    };
  }

  if (segments[0] === 'invoices' && segments[1]) {
    const backFilter = parseDocumentFilter(params.get('from'));
    return {
      ...DEFAULT_ROUTE_STATE,
      view: 'invoice-details',
      selectedInvoiceId: segments[1],
      documentsFilter: backFilter,
      invoiceBackFilter: backFilter,
    };
  }

  if (segments[0] === 'contracts' && segments[1]) {
    return {
      ...DEFAULT_ROUTE_STATE,
      view: 'contract-details',
      selectedContractId: segments[1],
    };
  }

  if (segments[0] === 'templates') {
    return { ...DEFAULT_ROUTE_STATE, view: 'templates' };
  }

  if (segments[0] === 'settings') {
    return { ...DEFAULT_ROUTE_STATE, view: 'settings' };
  }

  return { ...DEFAULT_ROUTE_STATE };
};

const getInitialRouteState = (): AppRouteState => {
  if (typeof window === 'undefined') {
    return { ...DEFAULT_ROUTE_STATE };
  }
  return parseRouteFromLocation(stripBasename(window.location.pathname), window.location.search);
};

const App: React.FC = () => {
  const initialRouteState = getInitialRouteState();
  const [currentView, setCurrentView] = useState<View>(initialRouteState.view);
  const [documentsFilter, setDocumentsFilter] = useState<DocumentFilter>(initialRouteState.documentsFilter);
  const [selectedContractId, setSelectedContractId] = useState<string | null>(initialRouteState.selectedContractId);
  const [selectedInvoiceId, setSelectedInvoiceId] = useState<string | null>(initialRouteState.selectedInvoiceId);
  const [invoiceDetailsBackFilter, setInvoiceDetailsBackFilter] = useState<InvoiceBackFilter>(initialRouteState.invoiceBackFilter);
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [counterparties, setCounterparties] = useState<Counterparty[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [templateVariables, setTemplateVariables] = useState<TemplateVariable[]>([]);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [dashboardStats, setDashboardStats] = useState<DashboardStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isDarkMode, setIsDarkMode] = useState(() => {
    if (typeof window !== 'undefined') {
      return window.matchMedia('(prefers-color-scheme: dark)').matches;
    }
    return false;
  });
  const [isProfileSwitching, setIsProfileSwitching] = useState(false);

  const activeCompanyProfileId = useMemo(() => {
    if (!settings) {
      return '';
    }
    return settings.activeCompanyProfileId || settings.companyProfiles?.[0]?.id || '';
  }, [settings]);

  const scopedInvoices = useMemo(() => {
    if (!activeCompanyProfileId) {
      return invoices;
    }
    return invoices.filter((invoice) => invoice.supplierProfileId === activeCompanyProfileId);
  }, [activeCompanyProfileId, invoices]);

  const invoicesById = useMemo(() => new Map(invoices.map((invoice) => [invoice.id, invoice] as const)), [invoices]);

  const scopedContracts = useMemo(() => {
    if (!activeCompanyProfileId) {
      return contracts;
    }

    return contracts.filter((contract) => {
      if (contract.supplierProfileId) {
        return contract.supplierProfileId === activeCompanyProfileId;
      }
      if (contract.invoiceId) {
        const linkedInvoice = invoicesById.get(contract.invoiceId);
        return linkedInvoice?.supplierProfileId === activeCompanyProfileId;
      }
      return false;
    });
  }, [activeCompanyProfileId, contracts, invoicesById]);

  const scopedDashboardStats = useMemo<DashboardStats>(() => {
    const totalContracts = scopedContracts.length;
    const pendingContracts = scopedContracts.filter((contract) => contract.status === 'На согласовании').length;
    const paidInvoicesAmount = scopedInvoices
      .filter((invoice) => invoice.status === 'Оплачен')
      .reduce((sum, invoice) => sum + Number(invoice.amount || 0), 0);

    return { totalContracts, pendingContracts, paidInvoicesAmount };
  }, [scopedContracts, scopedInvoices]);

  useEffect(() => {
    if (isDarkMode) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [isDarkMode]);

  const applyBootstrapData = (payload: BootstrapResponse) => {
    setContracts(payload.contracts);
    setCounterparties(payload.counterparties);
    setInvoices(payload.invoices);
    setTemplates(payload.templates);
    setTemplateVariables(payload.templateVariables || []);
    setSettings(payload.settings);
    setDashboardStats(payload.stats);
  };

  const loadData = useCallback(async () => {
    setLoadError(null);
    try {
      const payload = await api.getBootstrap();
      applyBootstrapData(payload);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось загрузить данные приложения';
      setLoadError(message);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const applyRouteState = useCallback((route: AppRouteState) => {
    setCurrentView(route.view);
    setDocumentsFilter(route.documentsFilter);
    setSelectedContractId(route.selectedContractId);
    setSelectedInvoiceId(route.selectedInvoiceId);
    setInvoiceDetailsBackFilter(route.invoiceBackFilter);
  }, []);

  const navigateToRoute = useCallback(
    (route: AppRouteState, options?: { replace?: boolean }) => {
      applyRouteState(route);

      if (typeof window === 'undefined') {
        return;
      }

      const targetPath = buildPathFromRoute(route);
      const currentPath = getCurrentPathWithSearch();
      if (targetPath === currentPath) {
        return;
      }

      if (options?.replace) {
        window.history.replaceState(null, '', withBasename(targetPath));
      } else {
        window.history.pushState(null, '', withBasename(targetPath));
      }
    },
    [applyRouteState],
  );

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }

    const routeFromLocation = parseRouteFromLocation(
      stripBasename(window.location.pathname),
      window.location.search,
    );
    applyRouteState(routeFromLocation);

    const canonicalPath = buildPathFromRoute(routeFromLocation);
    if (canonicalPath !== getCurrentPathWithSearch()) {
      window.history.replaceState(null, '', withBasename(canonicalPath));
    }

    const handlePopState = () => {
      const nextRoute = parseRouteFromLocation(
        stripBasename(window.location.pathname),
        window.location.search,
      );
      applyRouteState(nextRoute);
    };

    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, [applyRouteState]);

  const navigateToDocuments = useCallback(
    (filter: DocumentFilter, options?: { replace?: boolean }) => {
      const normalizedFilter = parseDocumentFilter(filter);
      navigateToRoute(
        {
          view: normalizedFilter === 'invoices' ? 'invoices' : 'contracts',
          documentsFilter: normalizedFilter,
          selectedContractId: null,
          selectedInvoiceId: null,
          invoiceBackFilter: normalizedFilter,
        },
        options,
      );
    },
    [navigateToRoute],
  );

  const handleNavigate = useCallback(
    (view: View) => {
      if (view === 'contracts') {
        navigateToDocuments('all');
        return;
      }

      if (view === 'invoices') {
        navigateToDocuments('invoices');
        return;
      }

      if (view === 'dashboard') {
        navigateToRoute({
          view: 'dashboard',
          documentsFilter,
          selectedContractId: null,
          selectedInvoiceId: null,
          invoiceBackFilter: documentsFilter,
        });
        return;
      }

      if (view === 'create-contract') {
        navigateToRoute({
          view: 'create-contract',
          documentsFilter,
          selectedContractId: null,
          selectedInvoiceId: null,
          invoiceBackFilter: documentsFilter,
        });
        return;
      }

      if (view === 'templates') {
        navigateToRoute({
          view: 'templates',
          documentsFilter,
          selectedContractId: null,
          selectedInvoiceId: null,
          invoiceBackFilter: documentsFilter,
        });
        return;
      }

      if (view === 'settings') {
        navigateToRoute({
          view: 'settings',
          documentsFilter,
          selectedContractId: null,
          selectedInvoiceId: null,
          invoiceBackFilter: documentsFilter,
        });
      }
    },
    [documentsFilter, navigateToDocuments, navigateToRoute],
  );

  const saveSettings = async (payload: Partial<AppSettings>) => {
    const updated = await api.updateSettings(payload);
    setSettings(updated);
  };

  const switchActiveCompanyProfile = async (profileId: string) => {
    if (!profileId || !settings) {
      return;
    }

    if (settings.activeCompanyProfileId === profileId) {
      return;
    }

    setIsProfileSwitching(true);
    try {
      const updated = await api.updateSettings({ activeCompanyProfileId: profileId });
      setSettings(updated);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось переключить профиль компании.';
      if (typeof window !== 'undefined') {
        window.alert(message);
      }
    } finally {
      setIsProfileSwitching(false);
    }
  };

  const createCounterparty = async (payload: CreateCounterpartyPayload) => {
    const created = await api.createCounterparty(payload);
    await loadData();
    return created;
  };

  const createInvoice = async (payload: CreateInvoicePayload) => {
    const created = await api.createInvoice(payload);
    await loadData();
    return created;
  };
  const openCreateContractFromInvoice = useCallback(
    (invoiceId: string) => {
      navigateToRoute({
        view: 'create-contract',
        documentsFilter: 'invoices',
        selectedContractId: null,
        selectedInvoiceId: invoiceId,
        invoiceBackFilter: 'invoices',
      });
    },
    [navigateToRoute],
  );

  const updateCounterparty = async (counterpartyId: string, payload: UpdateCounterpartyPayload) => {
    const updated = await api.updateCounterparty(counterpartyId, payload);
    await loadData();
    return updated;
  };

  const updateInvoice = async (invoiceId: string, payload: UpdateInvoicePayload) => {
    const updated = await api.updateInvoice(invoiceId, payload);
    await loadData();
    return updated;
  };

  const updateContract = async (contractId: string, payload: UpdateContractPayload) => {
    const updated = await api.updateContract(contractId, payload);
    await loadData();
    return updated;
  };

  const createTemplate = async (payload: CreateTemplatePayload) => {
    const created = await api.createTemplate(payload);
    await loadData();
    return created;
  };

  const updateTemplate = async (templateId: string, payload: UpdateTemplatePayload) => {
    const updated = await api.updateTemplate(templateId, payload);
    await loadData();
    return updated;
  };

  const deleteCounterparty = async (counterpartyId: string) => {
    await api.deleteCounterparty(counterpartyId);
    await loadData();
  };

  const deleteInvoice = async (invoiceId: string) => {
    await api.deleteInvoice(invoiceId);
    await loadData();
  };

  const deleteContract = async (contractId: string) => {
    await api.deleteContract(contractId);
    await loadData();
  };

  const deleteTemplate = async (templateId: string) => {
    await api.deleteTemplate(templateId);
    await loadData();
  };

  const toggleTheme = () => setIsDarkMode(!isDarkMode);
  const openContractDetails = (contractId: string) => {
    navigateToRoute({
      view: 'contract-details',
      documentsFilter,
      selectedContractId: contractId,
      selectedInvoiceId: null,
      invoiceBackFilter: documentsFilter,
    });
  };
  const openInvoiceDetails = (invoiceId: string) => {
    const backFilter = currentView === 'invoices' ? ('invoices' as DocumentFilter) : documentsFilter;
    navigateToRoute({
      view: 'invoice-details',
      documentsFilter,
      selectedContractId: null,
      selectedInvoiceId: invoiceId,
      invoiceBackFilter: backFilter,
    });
  };

  const handleDocumentsFilterChange = useCallback(
    (filter: DocumentFilter) => {
      navigateToDocuments(filter);
    },
    [navigateToDocuments],
  );

  const renderView = () => {
    if (isLoading) {
      return <Card className="p-6">Загрузка данных...</Card>;
    }

    if (loadError) {
      return (
        <Card className="p-6 space-y-3">
          <p className="text-red-600 dark:text-red-400">Ошибка загрузки: {loadError}</p>
          <button
            onClick={loadData}
            className="bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700 text-sm font-medium"
          >
            Повторить
          </button>
        </Card>
      );
    }

    switch (currentView) {
      case 'dashboard':
        return (
          <Dashboard
            onNavigate={handleNavigate}
            onOpenContract={openContractDetails}
            contracts={scopedContracts}
            stats={scopedDashboardStats}
          />
        );
      case 'create-contract':
        return (
          <ContractWizard
            onCancel={() => navigateToDocuments('all')}
            onFinish={(createdContractId) => {
              if (createdContractId) {
                openContractDetails(createdContractId);
                return;
              }
              navigateToDocuments('all');
            }}
            counterparties={counterparties}
            invoices={scopedInvoices}
            initialInvoiceId={selectedInvoiceId}
            templates={templates}
            settings={settings}
            onContractCreated={loadData}
          />
        );
      case 'contracts':
        return (
          <DocumentsByCounterparty
            onNavigate={handleNavigate}
            onOpenContract={openContractDetails}
            onOpenInvoice={openInvoiceDetails}
            contracts={scopedContracts}
            invoices={scopedInvoices}
            counterparties={counterparties}
            settings={settings}
            defaultFilter={documentsFilter}
            onFilterChange={handleDocumentsFilterChange}
            onCreateCounterparty={createCounterparty}
            onCreateInvoice={createInvoice}
            onStartContractFromInvoice={openCreateContractFromInvoice}
            onUpdateCounterparty={updateCounterparty}
            onUpdateInvoice={updateInvoice}
            onUpdateContract={updateContract}
            onDeleteCounterparty={deleteCounterparty}
            onDeleteInvoice={deleteInvoice}
            onDeleteContract={deleteContract}
          />
        );
      case 'contract-details': {
        const selectedContract = scopedContracts.find((contract) => contract.id === selectedContractId);

        if (!selectedContract) {
          return (
            <Card className="p-6 space-y-3">
              <p className="text-slate-700 dark:text-slate-300">Договор не найден или еще не загружен.</p>
              <button
                onClick={() => navigateToDocuments(documentsFilter)}
                className="bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700 text-sm font-medium"
              >
                К списку договоров
              </button>
            </Card>
          );
        }

        const invoice = selectedContract.invoiceId
          ? scopedInvoices.find((item) => item.id === selectedContract.invoiceId) ||
            invoices.find((item) => item.id === selectedContract.invoiceId)
          : undefined;

        return (
          <ContractDetails
            contract={selectedContract}
            invoice={invoice}
            settings={settings}
            onBack={() => navigateToDocuments(documentsFilter)}
          />
        );
      }
      case 'invoice-details': {
        const selectedInvoice = scopedInvoices.find((invoice) => invoice.id === selectedInvoiceId);

        if (!selectedInvoice) {
          return (
            <Card className="p-6 space-y-3">
              <p className="text-slate-700 dark:text-slate-300">Счет не найден или еще не загружен.</p>
              <button
                onClick={() => navigateToDocuments(invoiceDetailsBackFilter)}
                className="bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700 text-sm font-medium"
              >
                К списку счетов
              </button>
            </Card>
          );
        }

        const counterparty = selectedInvoice.counterpartyId
          ? counterparties.find((item) => item.id === selectedInvoice.counterpartyId)
          : undefined;

        return (
          <InvoiceDetails
            invoice={selectedInvoice}
            counterparty={counterparty}
            settings={settings}
            onBack={() => navigateToDocuments(invoiceDetailsBackFilter)}
          />
        );
      }
      case 'templates':
        return (
          <Templates
            templates={templates}
            templateVariables={templateVariables}
            onCreateTemplate={createTemplate}
            onUpdateTemplate={updateTemplate}
            onDeleteTemplate={deleteTemplate}
          />
        );
      case 'invoices':
        return (
          <DocumentsByCounterparty
            onNavigate={handleNavigate}
            onOpenContract={openContractDetails}
            onOpenInvoice={openInvoiceDetails}
            contracts={scopedContracts}
            invoices={scopedInvoices}
            counterparties={counterparties}
            settings={settings}
            defaultFilter="invoices"
            onFilterChange={handleDocumentsFilterChange}
            onCreateCounterparty={createCounterparty}
            onCreateInvoice={createInvoice}
            onStartContractFromInvoice={openCreateContractFromInvoice}
            onUpdateCounterparty={updateCounterparty}
            onUpdateInvoice={updateInvoice}
            onUpdateContract={updateContract}
            onDeleteCounterparty={deleteCounterparty}
            onDeleteInvoice={deleteInvoice}
            onDeleteContract={deleteContract}
          />
        );
      case 'settings':
        return <Settings settings={settings} onSave={saveSettings} />;
      default:
        return (
          <Dashboard
            onNavigate={handleNavigate}
            onOpenContract={openContractDetails}
            contracts={scopedContracts}
            stats={scopedDashboardStats}
          />
        );
    }
  };

  return (
    <Layout
      currentView={currentView}
      onNavigate={handleNavigate}
      isDarkMode={isDarkMode}
      toggleTheme={toggleTheme}
      settings={settings}
      onSelectCompanyProfile={switchActiveCompanyProfile}
      isProfileSwitching={isProfileSwitching}
    >
      {renderView()}
    </Layout>
  );
};

export default App;
