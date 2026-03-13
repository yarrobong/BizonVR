import React from 'react';
import { AppSettings, View } from '../types';
import { Icons } from '../constants';

interface LayoutProps {
  children: React.ReactNode;
  currentView: View;
  onNavigate: (view: View) => void;
  isDarkMode: boolean;
  toggleTheme: () => void;
  settings?: AppSettings | null;
  onSelectCompanyProfile?: (profileId: string) => void | Promise<void>;
  isProfileSwitching?: boolean;
}

export const Layout: React.FC<LayoutProps> = ({
  children,
  currentView,
  onNavigate,
  isDarkMode,
  toggleTheme,
  settings,
  onSelectCompanyProfile,
  isProfileSwitching = false,
}) => {
  const [isProfileMenuOpen, setIsProfileMenuOpen] = React.useState(false);
  const embeddedMode =
    import.meta.env.VITE_EMBEDDED_MODE === 'true' ||
    (typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('embedded') === '1');
  const navItems: Array<{
    id: View;
    label: string;
    mobileLabel: string;
    icon: React.ComponentType<React.SVGProps<SVGSVGElement>>;
  }> = [
    { id: 'dashboard', label: 'Дашборд', mobileLabel: 'Главная', icon: Icons.Dashboard },
    { id: 'contracts', label: 'Документы', mobileLabel: 'Документы', icon: Icons.FileText },
    { id: 'create-contract', label: 'Создать новый', mobileLabel: 'Создать', icon: Icons.Plus },
    { id: 'templates', label: 'Шаблоны', mobileLabel: 'Шаблоны', icon: Icons.FileText },
    { id: 'settings', label: 'Настройки', mobileLabel: 'Настройки', icon: Icons.Settings },
  ];

  const activeView =
    currentView === 'contract-details' || currentView === 'invoice-details' || currentView === 'invoices'
      ? 'contracts'
      : currentView;

  const handleNav = (view: View) => {
    onNavigate(view);
  };

  const companyProfiles =
    Array.isArray(settings?.companyProfiles) && settings.companyProfiles.length > 0 ? settings.companyProfiles : [];
  const activeProfile =
    companyProfiles.find((profile) => profile.id === settings?.activeCompanyProfileId) || companyProfiles[0];
  const activeProfileId = activeProfile?.id || '';
  const profileDisplayName = activeProfile?.companyName || 'Профиль компании';
  const profileDisplayRole = activeProfile?.legalType === 'ip' ? 'ИП' : activeProfile ? 'ООО' : 'Компания';
  const profileInitials = profileDisplayName
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join('') || 'DF';

  if (embeddedMode) {
    return (
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 transition-colors duration-200">
        <main className="min-h-screen overflow-y-auto p-4 md:p-8">
          <div className="max-w-7xl mx-auto">{children}</div>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex flex-col md:flex-row transition-colors duration-200">
      {/* Mobile Header */}
      <header className="bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 h-16 flex items-center justify-between px-4 md:hidden sticky top-0 z-30 transition-colors duration-200">
        <div className="flex items-center gap-2 font-bold text-xl text-slate-800 dark:text-slate-100">
          <span className="text-blue-600">Docu</span>Flow
        </div>
        <button
          onClick={toggleTheme}
          className="p-2 text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-md"
        >
          {isDarkMode ? <Icons.Sun className="w-5 h-5" /> : <Icons.Moon className="w-5 h-5" />}
        </button>
      </header>

      {/* Sidebar Navigation */}
      <aside className="hidden md:flex md:w-64 md:h-screen md:sticky md:top-0 md:flex-col bg-slate-900 dark:bg-slate-950 text-white border-r border-slate-800">
        <div className="h-16 flex items-center px-6 border-b border-slate-800 font-bold text-xl">
           <span className="text-blue-400 mr-1">Docu</span>Flow
        </div>
        
        <nav className="flex-1 p-4 space-y-1 overflow-y-auto">
          {navItems.map((item) => {
            const isActive = activeView === item.id;
            return (
              <button
                key={item.id}
                onClick={() => handleNav(item.id)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors
                  ${isActive 
                    ? 'bg-blue-600 text-white' 
                    : 'text-slate-400 hover:bg-slate-800 hover:text-white'}
                `}
              >
              <item.icon className="w-5 h-5" />
              {item.label}
            </button>
          );
        })}
      </nav>

        <div className="p-4 border-t border-slate-800 space-y-4">
           {/* Desktop Theme Toggle */}
           <button 
             onClick={toggleTheme}
             className="hidden md:flex w-full items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium text-slate-400 hover:bg-slate-800 hover:text-white transition-colors"
           >
             {isDarkMode ? <Icons.Sun className="w-5 h-5" /> : <Icons.Moon className="w-5 h-5" />}
             {isDarkMode ? 'Светлая тема' : 'Темная тема'}
           </button>

          <div className="px-2 relative">
            {isProfileMenuOpen && companyProfiles.length > 0 && (
              <div className="absolute left-2 right-2 bottom-full mb-2 rounded-lg border border-slate-700 bg-slate-900 p-1 space-y-1 shadow-xl z-10">
                {companyProfiles.map((profile, index) => {
                  const isActiveProfile = profile.id === activeProfileId;
                  return (
                    <button
                      key={profile.id}
                      type="button"
                      disabled={isProfileSwitching || isActiveProfile}
                      onClick={() => {
                        onSelectCompanyProfile?.(profile.id);
                        setIsProfileMenuOpen(false);
                      }}
                      className={`w-full text-left px-2 py-1.5 rounded text-xs transition-colors ${
                        isActiveProfile
                          ? 'bg-blue-600 text-white'
                          : 'text-slate-200 hover:bg-slate-800'
                      }`}
                    >
                      {profile.companyName || `Компания ${index + 1}`}
                    </button>
                  );
                })}
              </div>
            )}

            <button
              type="button"
              onClick={() => setIsProfileMenuOpen((prev) => !prev)}
              className="w-full flex items-center justify-between gap-3 p-2 rounded-lg hover:bg-slate-800 transition-colors text-left"
            >
              <div className="flex items-center gap-3 min-w-0">
                <div className="w-8 h-8 rounded-full bg-blue-500 flex items-center justify-center font-bold text-xs text-white">
                  {profileInitials}
                </div>
                <div className="text-sm min-w-0">
                  <div className="font-medium text-white truncate max-w-[150px]" title={profileDisplayName}>
                    {profileDisplayName}
                  </div>
                  <div className="text-slate-500 text-xs">{profileDisplayRole}</div>
                </div>
              </div>
              <Icons.ChevronRight
                className={`w-4 h-4 text-slate-500 transition-transform ${isProfileMenuOpen ? 'rotate-90' : ''}`}
              />
            </button>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 overflow-y-auto h-[calc(100vh-64px)] md:h-screen p-4 md:p-8 pb-24 md:pb-8">
        <div className="max-w-7xl mx-auto">
          {children}
        </div>
      </main>

      {/* Mobile Bottom Navigation */}
      <nav
        className="fixed inset-x-0 bottom-0 z-30 border-t border-slate-200 dark:border-slate-800 bg-white/95 dark:bg-slate-900/95 backdrop-blur md:hidden"
        style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
      >
        <div className="grid grid-cols-5 h-16">
          {navItems.map((item) => {
            const isActive = activeView === item.id;
            const isCreateAction = item.id === 'create-contract';
            return (
              <button
                key={item.id}
                onClick={() => handleNav(item.id)}
                className={`flex flex-col items-center justify-center gap-1 text-[10px] font-medium transition-colors
                  ${isActive ? 'text-blue-600 dark:text-blue-400' : 'text-slate-500 dark:text-slate-400'}
                `}
              >
                <span
                  className={`flex items-center justify-center rounded-full ${
                    isCreateAction ? 'w-8 h-8 -mt-3' : 'w-5 h-5'
                  } ${isCreateAction && !isActive ? 'bg-slate-200 dark:bg-slate-700' : ''} ${
                    isCreateAction && isActive ? 'bg-blue-600 text-white dark:text-white' : ''
                  }`}
                >
                  <item.icon className={isCreateAction ? 'w-4 h-4' : 'w-4 h-4'} />
                </span>
                <span className="leading-none">{item.mobileLabel}</span>
              </button>
            );
          })}
        </div>
      </nav>
    </div>
  );
};
