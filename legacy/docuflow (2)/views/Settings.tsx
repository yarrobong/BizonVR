import React, { useEffect, useMemo, useState } from 'react';
import { Card, Button, Input, Select } from '../components/ui';
import { Icons } from '../constants';
import { AppSettings, BankAccount, PrivatePersonRfProfile, SupplierCompanyProfile, SupplierLegalType } from '../types';

const EMPTY_BANK_ACCOUNT: BankAccount = {
  bankName: '',
  checkingAccount: '',
  correspondentAccount: '',
  bik: '',
  cardNumber: '',
  sbpPhone: '',
};

const isNonEmptyString = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0;
const toTrimmedString = (value: unknown) => (isNonEmptyString(value) ? value.trim() : '');
const toSupplierLegalType = (value: unknown): SupplierLegalType => {
  const normalized = String(value ?? '').trim().toLowerCase();
  if (normalized === 'ip') {
    return 'ip';
  }
  if (normalized === 'person') {
    return 'person';
  }
  return 'ooo';
};
const createCompanyProfileId = () => `company-${Date.now()}-${Math.floor(Math.random() * 1000)}`;

const normalizeBankAccount = (value?: Partial<BankAccount> | null): BankAccount => ({
  bankName: String(value?.bankName ?? '').trim(),
  checkingAccount: String(value?.checkingAccount ?? '').trim(),
  correspondentAccount: String(value?.correspondentAccount ?? '').trim(),
  bik: String(value?.bik ?? '').trim(),
  cardNumber: String(value?.cardNumber ?? '').trim(),
  sbpPhone: String(value?.sbpPhone ?? '').trim(),
});

const hasBankAccountValues = (value: BankAccount) =>
  Boolean(
    value.bankName ||
      value.checkingAccount ||
      value.correspondentAccount ||
      value.bik ||
      value.cardNumber ||
      value.sbpPhone,
  );

const normalizeBankAccounts = (
  bankAccounts?: Array<Partial<BankAccount>> | null,
  fallback?: Partial<BankAccount> | null,
): BankAccount[] => {
  if (Array.isArray(bankAccounts)) {
    const normalized = bankAccounts.map((account) => normalizeBankAccount(account)).filter(hasBankAccountValues);
    if (normalized.length > 0) {
      return normalized;
    }
  }

  const normalizedFallback = normalizeBankAccount(fallback);
  if (hasBankAccountValues(normalizedFallback)) {
    return [normalizedFallback];
  }

  return [];
};

const getPrimaryBankAccount = (bankAccounts: BankAccount[]): BankAccount => bankAccounts[0] || EMPTY_BANK_ACCOUNT;

const digitsOnly = (value: string) => String(value ?? '').replace(/\D/g, '');

const maskPassportSeries = (value: string) => digitsOnly(value).slice(0, 4);
const maskPassportNumber = (value: string) => digitsOnly(value).slice(0, 6);
const maskPassportDepartmentCode = (value: string) => {
  const digits = digitsOnly(value).slice(0, 6);
  if (digits.length <= 3) {
    return digits;
  }
  return `${digits.slice(0, 3)}-${digits.slice(3)}`;
};

const maskRuPhone = (value: string) => {
  let digits = digitsOnly(value);
  if (digits.startsWith('8')) {
    digits = `7${digits.slice(1)}`;
  }
  if (!digits.startsWith('7')) {
    digits = `7${digits}`;
  }
  digits = digits.slice(0, 11);

  const country = '+7';
  const code = digits.slice(1, 4);
  const p1 = digits.slice(4, 7);
  const p2 = digits.slice(7, 9);
  const p3 = digits.slice(9, 11);

  if (!code) return country;
  if (!p1) return `${country} (${code}`;
  if (!p2) return `${country} (${code}) ${p1}`;
  if (!p3) return `${country} (${code}) ${p1}-${p2}`;
  return `${country} (${code}) ${p1}-${p2}-${p3}`;
};

const maskCardNumber = (value: string) => {
  const digits = digitsOnly(value).slice(0, 16);
  return digits.replace(/(\d{4})(?=\d)/g, '$1 ');
};

const normalizePrivatePersonRf = (value?: Partial<PrivatePersonRfProfile> | null): PrivatePersonRfProfile => ({
  // Preserve spaces while typing; backend normalizes on save.
  fullName: String(value?.fullName ?? ''),
  passportSeries: String(value?.passportSeries ?? '').trim(),
  passportNumber: String(value?.passportNumber ?? '').trim(),
  passportIssuedBy: String(value?.passportIssuedBy ?? '').trim(),
  passportIssuedDate: String(value?.passportIssuedDate ?? '').trim(),
  passportDepartmentCode: String(value?.passportDepartmentCode ?? '').trim(),
  registrationAddress: String(value?.registrationAddress ?? '').trim(),
  residenceAddress: String(value?.residenceAddress ?? '').trim(),
  phone: String(value?.phone ?? '').trim(),
  email: String(value?.email ?? '').trim(),
  bankName: String(value?.bankName ?? '').trim(),
  cardNumber: String(value?.cardNumber ?? '').trim(),
  sbpPhone: String(value?.sbpPhone ?? '').trim(),
  bik: String(value?.bik ?? '').trim(),
  checkingAccount: String(value?.checkingAccount ?? '').trim(),
  correspondentAccount: String(value?.correspondentAccount ?? '').trim(),
});

const hasPrivateSellerRfValues = (value?: Partial<PrivatePersonRfProfile> | null) => {
  const normalized = normalizePrivatePersonRf(value);
  return Boolean(
    normalized.fullName ||
      normalized.passportSeries ||
      normalized.passportNumber ||
      normalized.passportIssuedBy ||
      normalized.passportIssuedDate ||
      normalized.passportDepartmentCode ||
      normalized.registrationAddress ||
      normalized.residenceAddress ||
      normalized.phone ||
      normalized.email ||
      normalized.bankName ||
      normalized.cardNumber ||
      normalized.sbpPhone ||
      normalized.bik ||
      normalized.checkingAccount ||
      normalized.correspondentAccount,
  );
};

const privateSellerToPersonCompanyProfile = (
  value?: Partial<PrivatePersonRfProfile> | null,
  fallbackId: string = 'person-rf',
): SupplierCompanyProfile =>
  normalizeCompanyProfile(
    {
      id: fallbackId,
      legalType: 'person',
      companyName: String(value?.fullName ?? ''),
      legalAddress: String(value?.registrationAddress ?? ''),
      phone: String(value?.phone ?? ''),
      email: String(value?.email ?? ''),
      bankAccounts: [
        {
          bankName: String(value?.bankName ?? ''),
          cardNumber: String(value?.cardNumber ?? ''),
          sbpPhone: String(value?.sbpPhone ?? ''),
          bik: String(value?.bik ?? ''),
          checkingAccount: String(value?.checkingAccount ?? ''),
          correspondentAccount: String(value?.correspondentAccount ?? ''),
        },
      ],
      passportSeries: String(value?.passportSeries ?? ''),
      passportNumber: String(value?.passportNumber ?? ''),
      passportIssuedBy: String(value?.passportIssuedBy ?? ''),
      passportIssuedDate: String(value?.passportIssuedDate ?? ''),
      passportDepartmentCode: String(value?.passportDepartmentCode ?? ''),
      registrationAddress: String(value?.registrationAddress ?? ''),
      residenceAddress: String(value?.residenceAddress ?? ''),
    },
    fallbackId,
  );

const personCompanyProfileToPrivateSeller = (profile?: Partial<SupplierCompanyProfile> | null): PrivatePersonRfProfile => {
  const normalizedProfile = normalizeCompanyProfile(profile || { legalType: 'person' }, isNonEmptyString(profile?.id) ? profile.id : 'person-rf');
  const primaryAccount = getPrimaryBankAccount(normalizedProfile.bankAccounts || []);
  return normalizePrivatePersonRf({
    fullName: normalizedProfile.companyName,
    passportSeries: normalizedProfile.passportSeries,
    passportNumber: normalizedProfile.passportNumber,
    passportIssuedBy: normalizedProfile.passportIssuedBy,
    passportIssuedDate: normalizedProfile.passportIssuedDate,
    passportDepartmentCode: normalizedProfile.passportDepartmentCode,
    registrationAddress: normalizedProfile.registrationAddress || normalizedProfile.legalAddress,
    residenceAddress: normalizedProfile.residenceAddress,
    phone: normalizedProfile.phone,
    email: normalizedProfile.email,
    bankName: primaryAccount.bankName || normalizedProfile.bankName,
    cardNumber: primaryAccount.cardNumber || normalizedProfile.cardNumber,
    sbpPhone: primaryAccount.sbpPhone || normalizedProfile.sbpPhone || normalizedProfile.phone,
    bik: primaryAccount.bik || normalizedProfile.bik,
    checkingAccount: primaryAccount.checkingAccount || normalizedProfile.checkingAccount,
    correspondentAccount: primaryAccount.correspondentAccount || normalizedProfile.correspondentAccount,
  });
};

const normalizeCompanyProfile = (
  value?: Partial<SupplierCompanyProfile> | null,
  fallbackId: string = createCompanyProfileId(),
): SupplierCompanyProfile => {
  const legalType = toSupplierLegalType(value?.legalType);
  const bankAccounts = normalizeBankAccounts(value?.bankAccounts, value);
  const primaryBankAccount = getPrimaryBankAccount(bankAccounts);

  return {
    id: isNonEmptyString(value?.id) ? value.id.trim() : fallbackId,
    legalType,
    companyName: legalType === 'person' ? String(value?.companyName ?? '') : toTrimmedString(value?.companyName),
    inn: toTrimmedString(value?.inn),
    kpp: legalType === 'ooo' ? toTrimmedString(value?.kpp) : '',
    ogrn: legalType === 'ooo' ? toTrimmedString(value?.ogrn) : '',
    ogrnip: legalType === 'ip' ? toTrimmedString(value?.ogrnip) : '',
    directorGenitive: legalType === 'person' ? '' : toTrimmedString(value?.directorGenitive),
    legalAddress:
      legalType === 'person'
        ? toTrimmedString(value?.registrationAddress ?? value?.legalAddress)
        : toTrimmedString(value?.legalAddress),
    email: toTrimmedString(value?.email),
    phone: toTrimmedString(value?.phone),
    bankName: primaryBankAccount.bankName,
    bik: primaryBankAccount.bik,
    correspondentAccount: primaryBankAccount.correspondentAccount,
    checkingAccount: primaryBankAccount.checkingAccount,
    cardNumber: toTrimmedString(primaryBankAccount.cardNumber),
    sbpPhone: toTrimmedString(primaryBankAccount.sbpPhone) || (legalType === 'person' ? toTrimmedString(value?.phone) : ''),
    bankAccounts,
    passportSeries: legalType === 'person' ? toTrimmedString(value?.passportSeries) : '',
    passportNumber: legalType === 'person' ? toTrimmedString(value?.passportNumber) : '',
    passportIssuedBy: legalType === 'person' ? toTrimmedString(value?.passportIssuedBy) : '',
    passportIssuedDate: legalType === 'person' ? toTrimmedString(value?.passportIssuedDate) : '',
    passportDepartmentCode: legalType === 'person' ? toTrimmedString(value?.passportDepartmentCode) : '',
    registrationAddress:
      legalType === 'person'
        ? toTrimmedString(value?.registrationAddress ?? value?.legalAddress)
        : '',
    residenceAddress: legalType === 'person' ? toTrimmedString(value?.residenceAddress) : '',
  };
};

const createProfileFromLegacySettings = (settings: Partial<AppSettings>): SupplierCompanyProfile =>
  normalizeCompanyProfile(
    {
      id: isNonEmptyString(settings.activeCompanyProfileId) ? settings.activeCompanyProfileId : 'company-1',
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
    'company-1'
  );

const cloneCompanyProfile = (profile: SupplierCompanyProfile): SupplierCompanyProfile => ({
  ...profile,
  bankAccounts: Array.isArray(profile.bankAccounts)
    ? profile.bankAccounts.map((account) => ({ ...account }))
    : [],
});

const normalizeCompanyProfiles = (settings: AppSettings): SupplierCompanyProfile[] => {
  const profiles = Array.isArray(settings.companyProfiles) && settings.companyProfiles.length > 0
    ? settings.companyProfiles.map((profile, index) =>
      normalizeCompanyProfile(profile, isNonEmptyString(profile?.id) ? profile.id : `company-${index + 1}`),
    )
    : [createProfileFromLegacySettings(settings)];

  const hasPersonProfile = profiles.some((profile) => profile.legalType === 'person');
  if (!hasPersonProfile && hasPrivateSellerRfValues(settings.privateSellerRf)) {
    profiles.push(
      privateSellerToPersonCompanyProfile(
        settings.privateSellerRf,
        isNonEmptyString(settings.activeCompanyProfileId) ? `${settings.activeCompanyProfileId}-person` : 'person-rf',
      ),
    );
  }

  return profiles;
};

const syncSettingsWithProfiles = (
  settings: AppSettings,
  profilesInput: SupplierCompanyProfile[],
  requestedActiveId?: string,
): AppSettings => {
  const normalizedProfiles =
    profilesInput.length > 0
      ? profilesInput.map((profile, index) =>
          normalizeCompanyProfile(profile, isNonEmptyString(profile?.id) ? profile.id : `company-${index + 1}`),
        )
      : [createProfileFromLegacySettings(settings)];

  const activeProfile =
    normalizedProfiles.find((profile) => profile.id === requestedActiveId) || normalizedProfiles[0];
  const personProfile = normalizedProfiles.find((profile) => profile.legalType === 'person');

  return {
    ...settings,
    companyProfiles: normalizedProfiles,
    activeCompanyProfileId: activeProfile.id,
    privateSellerRf: personProfile
      ? personCompanyProfileToPrivateSeller(personProfile)
      : normalizePrivatePersonRf(settings.privateSellerRf),
    legalType: activeProfile.legalType,
    companyName: activeProfile.companyName,
    inn: activeProfile.inn,
    kpp: activeProfile.kpp,
    ogrn: activeProfile.ogrn,
    ogrnip: activeProfile.ogrnip,
    directorGenitive: activeProfile.directorGenitive,
    legalAddress: activeProfile.legalAddress,
    email: activeProfile.email,
    phone: activeProfile.phone,
    bankName: activeProfile.bankName,
    bik: activeProfile.bik,
    correspondentAccount: activeProfile.correspondentAccount,
    checkingAccount: activeProfile.checkingAccount,
    bankAccounts: activeProfile.bankAccounts,
  };
};

const normalizeSettings = (value: AppSettings | null): AppSettings | null => {
  if (!value) {
    return value;
  }

  const profiles = normalizeCompanyProfiles(value);
  return {
    ...syncSettingsWithProfiles(value, profiles, value.activeCompanyProfileId),
  };
};

const createEmptyCompanyProfile = (): SupplierCompanyProfile =>
  normalizeCompanyProfile(
    {
      id: createCompanyProfileId(),
      legalType: 'ooo',
      companyName: '',
      inn: '',
      kpp: '',
      ogrn: '',
      ogrnip: '',
      directorGenitive: '',
      legalAddress: '',
      email: '',
      phone: '',
      bankAccounts: [{ ...EMPTY_BANK_ACCOUNT }],
      passportSeries: '',
      passportNumber: '',
      passportIssuedBy: '',
      passportIssuedDate: '',
      passportDepartmentCode: '',
      registrationAddress: '',
      residenceAddress: '',
    },
    createCompanyProfileId()
  );

interface SettingsProps {
  settings: AppSettings | null;
  onSave: (payload: Partial<AppSettings>) => Promise<void>;
}

export const Settings: React.FC<SettingsProps> = ({ settings, onSave }) => {
  const [formData, setFormData] = useState<AppSettings | null>(normalizeSettings(settings));
  const [isSaving, setIsSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    setFormData(normalizeSettings(settings));
  }, [settings]);

  const mutateProfiles = (
    mutator: (profiles: SupplierCompanyProfile[], activeId: string) => { profiles: SupplierCompanyProfile[]; activeId?: string },
  ) => {
    setFormData((prev) => {
      if (!prev) {
        return prev;
      }

      const profiles = normalizeCompanyProfiles(prev).map(cloneCompanyProfile);
      const activeId = profiles.some((profile) => profile.id === prev.activeCompanyProfileId)
        ? String(prev.activeCompanyProfileId)
        : profiles[0].id;
      const result = mutator(profiles, activeId);
      return syncSettingsWithProfiles(prev, result.profiles, result.activeId || activeId);
    });
  };

  const updateGlobalField = <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => {
    setFormData((prev) => (prev ? { ...prev, [key]: value } : prev));
  };

  const updateActiveProfileField = <K extends keyof SupplierCompanyProfile>(key: K, value: SupplierCompanyProfile[K]) => {
    mutateProfiles((profiles, activeId) => {
      const nextProfiles = profiles.map((profile) =>
        profile.id === activeId ? normalizeCompanyProfile({ ...profile, [key]: value }, profile.id) : profile,
      );
      return { profiles: nextProfiles, activeId };
    });
  };

  const updateActiveProfileMaskedField = <K extends keyof SupplierCompanyProfile>(
    key: K,
    value: string,
    mask: (raw: string) => string,
  ) => {
    updateActiveProfileField(key, mask(value) as SupplierCompanyProfile[K]);
  };

  const selectActiveProfile = (profileId: string) => {
    mutateProfiles((profiles) => ({ profiles, activeId: profileId }));
  };

  const addCompanyProfile = () => {
    mutateProfiles((profiles) => {
      const created = createEmptyCompanyProfile();
      return { profiles: [...profiles, created], activeId: created.id };
    });
  };

  const removeActiveCompanyProfile = () => {
    mutateProfiles((profiles, activeId) => {
      if (profiles.length <= 1) {
        return { profiles, activeId };
      }

      const nextProfiles = profiles.filter((profile) => profile.id !== activeId);
      return { profiles: nextProfiles, activeId: nextProfiles[0]?.id };
    });
  };

  const updateActiveBankAccountField = (index: number, key: keyof BankAccount, value: string) => {
    mutateProfiles((profiles, activeId) => {
      const nextProfiles = profiles.map((profile) => {
        if (profile.id !== activeId) {
          return profile;
        }

        const bankAccounts =
          Array.isArray(profile.bankAccounts) && profile.bankAccounts.length > 0
            ? profile.bankAccounts.map((account) => ({ ...account }))
            : [{ ...EMPTY_BANK_ACCOUNT }];

        const currentAccount = bankAccounts[index] || { ...EMPTY_BANK_ACCOUNT };
        bankAccounts[index] = { ...currentAccount, [key]: value };
        return normalizeCompanyProfile({ ...profile, bankAccounts }, profile.id);
      });

      return { profiles: nextProfiles, activeId };
    });
  };

  const addActiveBankAccount = () => {
    mutateProfiles((profiles, activeId) => {
      const nextProfiles = profiles.map((profile) => {
        if (profile.id !== activeId) {
          return profile;
        }

        const bankAccounts = Array.isArray(profile.bankAccounts) ? [...profile.bankAccounts] : [];
        bankAccounts.push({ ...EMPTY_BANK_ACCOUNT });
        return normalizeCompanyProfile({ ...profile, bankAccounts }, profile.id);
      });

      return { profiles: nextProfiles, activeId };
    });
  };

  const removeActiveBankAccount = (index: number) => {
    mutateProfiles((profiles, activeId) => {
      const nextProfiles = profiles.map((profile) => {
        if (profile.id !== activeId) {
          return profile;
        }

        const bankAccounts =
          Array.isArray(profile.bankAccounts) && profile.bankAccounts.length > 0
            ? [...profile.bankAccounts]
            : [{ ...EMPTY_BANK_ACCOUNT }];

        if (bankAccounts.length <= 1) {
          return normalizeCompanyProfile({ ...profile, bankAccounts: [{ ...EMPTY_BANK_ACCOUNT }] }, profile.id);
        }

        const nextBankAccounts = bankAccounts.filter((_, itemIndex) => itemIndex !== index);
        return normalizeCompanyProfile({ ...profile, bankAccounts: nextBankAccounts }, profile.id);
      });

      return { profiles: nextProfiles, activeId };
    });
  };

  const save = async () => {
    if (!formData) {
      return;
    }

    setIsSaving(true);
    setMessage(null);

    try {
      const normalized = normalizeSettings(formData);
      if (!normalized) {
        return;
      }

      await onSave(normalized);
      setFormData(normalized);
      setMessage('Настройки сохранены');
    } catch (error) {
      const nextMessage = error instanceof Error ? error.message : 'Не удалось сохранить настройки';
      setMessage(nextMessage);
    } finally {
      setIsSaving(false);
    }
  };

  const normalizedFormData = useMemo(() => normalizeSettings(formData), [formData]);

  if (!normalizedFormData) {
    return (
      <div className="max-w-4xl mx-auto">
        <Card className="p-6">Загрузка настроек...</Card>
      </div>
    );
  }

  const companyProfiles = normalizeCompanyProfiles(normalizedFormData);
  const activeProfile =
    companyProfiles.find((profile) => profile.id === normalizedFormData.activeCompanyProfileId) || companyProfiles[0];
  const activeBankAccounts =
    Array.isArray(activeProfile.bankAccounts) && activeProfile.bankAccounts.length > 0
      ? activeProfile.bankAccounts
      : [{ ...EMPTY_BANK_ACCOUNT }];
  const isPersonProfile = activeProfile.legalType === 'person';

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">Настройки</h1>
        <p className="text-slate-500 dark:text-slate-400">
          Управление вашими компаниями, ИП, физлицами и настройками системы.
        </p>
      </div>

      <div className="grid gap-6">
        <Card className="p-6">
          <div className="flex items-center gap-3 mb-6 pb-4 border-b border-slate-100 dark:border-slate-800">
            <div className="p-2 bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 rounded-lg">
              <Icons.Users className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Мои компании</h2>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                Добавляйте несколько юрлиц/ИП/физлиц и переключайте активный профиль для документов.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Select
              label="Активная компания"
              value={activeProfile.id}
              onChange={(event) => selectActiveProfile(event.target.value)}
              options={companyProfiles.map((profile, index) => ({
                value: profile.id,
                label: profile.companyName || `Компания ${index + 1}`,
              }))}
            />
            <div className="flex items-end gap-2">
              <Button
                type="button"
                variant="outline"
                icon={<Icons.Plus className="w-4 h-4" />}
                onClick={addCompanyProfile}
              >
                Добавить компанию
              </Button>
              <Button
                type="button"
                variant="ghost"
                icon={<Icons.Trash className="w-4 h-4" />}
                onClick={removeActiveCompanyProfile}
                disabled={companyProfiles.length <= 1}
              >
                Удалить
              </Button>
            </div>

            <Select
              label="Тип компании"
              value={activeProfile.legalType}
              onChange={(event) => updateActiveProfileField('legalType', event.target.value as SupplierLegalType)}
              options={[
                { value: 'ooo', label: 'ООО' },
                { value: 'ip', label: 'ИП' },
                { value: 'person', label: 'Физлицо (РФ)' },
              ]}
            />

            <Input
              label={
                activeProfile.legalType === 'ooo'
                  ? 'Полное наименование'
                  : activeProfile.legalType === 'ip'
                    ? 'ФИО предпринимателя'
                    : 'ФИО'
              }
              value={activeProfile.companyName}
              onChange={(event) => updateActiveProfileField('companyName', event.target.value)}
              placeholder={activeProfile.legalType === 'ooo' ? 'ООО "Моя Компания"' : 'Иванов Иван Иванович'}
            />

            <Input
              label={isPersonProfile ? 'ИНН (при наличии)' : 'ИНН'}
              value={activeProfile.inn}
              onChange={(event) => updateActiveProfileField('inn', event.target.value)}
            />

            {activeProfile.legalType === 'ooo' ? (
              <>
                <Input
                  label="КПП"
                  value={activeProfile.kpp}
                  onChange={(event) => updateActiveProfileField('kpp', event.target.value)}
                />
                <Input
                  label="ОГРН"
                  value={activeProfile.ogrn}
                  onChange={(event) => updateActiveProfileField('ogrn', event.target.value)}
                />
                <Input
                  label="Генеральный директор (в родительном падеже)"
                  placeholder="Иванова Ивана Ивановича"
                  value={activeProfile.directorGenitive}
                  onChange={(event) => updateActiveProfileField('directorGenitive', event.target.value)}
                />
              </>
            ) : activeProfile.legalType === 'ip' ? (
              <>
                <Input
                  label="ОГРНИП"
                  value={activeProfile.ogrnip}
                  onChange={(event) => updateActiveProfileField('ogrnip', event.target.value)}
                />
                <Input
                  label="Предприниматель (в родительном падеже)"
                  placeholder="Иванова Ивана Ивановича"
                  value={activeProfile.directorGenitive}
                  onChange={(event) => updateActiveProfileField('directorGenitive', event.target.value)}
                />
              </>
            ) : (
              <>
                <Input
                  label="Серия паспорта"
                  value={activeProfile.passportSeries || ''}
                  onChange={(event) => updateActiveProfileMaskedField('passportSeries', event.target.value, maskPassportSeries)}
                  placeholder="4510"
                  inputMode="numeric"
                  maxLength={4}
                />
                <Input
                  label="Номер паспорта"
                  value={activeProfile.passportNumber || ''}
                  onChange={(event) => updateActiveProfileMaskedField('passportNumber', event.target.value, maskPassportNumber)}
                  placeholder="123456"
                  inputMode="numeric"
                  maxLength={6}
                />
                <div className="md:col-span-2">
                  <Input
                    label="Кем выдан паспорт"
                    value={activeProfile.passportIssuedBy || ''}
                    onChange={(event) => updateActiveProfileField('passportIssuedBy', event.target.value)}
                  />
                </div>
                <Input
                  label="Дата выдачи паспорта"
                  type="date"
                  value={activeProfile.passportIssuedDate || ''}
                  onChange={(event) => updateActiveProfileField('passportIssuedDate', event.target.value)}
                />
                <Input
                  label="Код подразделения"
                  value={activeProfile.passportDepartmentCode || ''}
                  onChange={(event) =>
                    updateActiveProfileMaskedField('passportDepartmentCode', event.target.value, maskPassportDepartmentCode)
                  }
                  placeholder="000-000"
                  inputMode="numeric"
                  maxLength={7}
                />
              </>
            )}

            <div className="md:col-span-2 mt-2">
              <h3 className="font-medium text-slate-900 dark:text-slate-200 mb-2">
                {isPersonProfile ? 'Адрес и контакты' : 'Юридический адрес и контакты'}
              </h3>
            </div>
            <div className="md:col-span-2">
              <Input
                label={isPersonProfile ? 'Адрес регистрации' : 'Юридический адрес'}
                value={isPersonProfile ? activeProfile.registrationAddress || activeProfile.legalAddress : activeProfile.legalAddress}
                onChange={(event) =>
                  isPersonProfile
                    ? updateActiveProfileField('registrationAddress', event.target.value)
                    : updateActiveProfileField('legalAddress', event.target.value)
                }
              />
            </div>
            {isPersonProfile && (
              <div className="md:col-span-2">
                <Input
                  label="Адрес проживания (если отличается)"
                  value={activeProfile.residenceAddress || ''}
                  onChange={(event) => updateActiveProfileField('residenceAddress', event.target.value)}
                />
              </div>
            )}
            <Input
              label="Email"
              type="email"
              value={activeProfile.email}
              onChange={(event) => updateActiveProfileField('email', event.target.value)}
            />
            <Input
              label="Телефон"
              type="tel"
              value={activeProfile.phone}
              onChange={(event) =>
                isPersonProfile
                  ? updateActiveProfileMaskedField('phone', event.target.value, maskRuPhone)
                  : updateActiveProfileField('phone', event.target.value)
              }
            />

            {isPersonProfile ? (
              <>
                <div className="md:col-span-2 mt-2">
                  <h3 className="font-medium text-slate-900 dark:text-slate-200">Банковские реквизиты</h3>
                </div>
                <div className="md:col-span-2">
                  <Input
                    label="Банк"
                    value={activeBankAccounts[0]?.bankName || ''}
                    onChange={(event) => updateActiveBankAccountField(0, 'bankName', event.target.value)}
                  />
                </div>
                <Input
                  label="Номер карты"
                  value={activeBankAccounts[0]?.cardNumber || ''}
                  onChange={(event) => updateActiveBankAccountField(0, 'cardNumber', maskCardNumber(event.target.value))}
                  inputMode="numeric"
                  maxLength={19}
                  placeholder="1234 5678 9012 3456"
                />
                <Input
                  label="Номер для СБП"
                  value={activeBankAccounts[0]?.sbpPhone || activeProfile.sbpPhone || ''}
                  onChange={(event) => updateActiveBankAccountField(0, 'sbpPhone', maskRuPhone(event.target.value))}
                  inputMode="tel"
                  placeholder="+7 (999) 123-45-67"
                />
              </>
            ) : (
              <>
                <div className="md:col-span-2 mt-2 flex items-center justify-between gap-2">
                  <h3 className="font-medium text-slate-900 dark:text-slate-200">Банковские реквизиты</h3>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    icon={<Icons.Plus className="w-4 h-4" />}
                    onClick={addActiveBankAccount}
                  >
                    Добавить счет
                  </Button>
                </div>

                <div className="md:col-span-2 space-y-3">
                  {activeBankAccounts.map((account, index) => (
                    <div
                      key={`company-${activeProfile.id}-bank-account-${index}`}
                      className="rounded-lg border border-slate-200 dark:border-slate-700 p-3"
                    >
                      <div className="flex items-center justify-between gap-2 mb-3">
                        <p className="text-sm font-medium text-slate-800 dark:text-slate-200">Счет {index + 1}</p>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          icon={<Icons.Trash className="w-4 h-4" />}
                          onClick={() => removeActiveBankAccount(index)}
                          disabled={activeBankAccounts.length <= 1}
                        >
                          Удалить
                        </Button>
                      </div>

                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <div className="md:col-span-2">
                          <Input
                            label="Наименование банка"
                            value={account.bankName}
                            onChange={(event) => updateActiveBankAccountField(index, 'bankName', event.target.value)}
                          />
                        </div>
                        <Input
                          label="БИК"
                          value={account.bik}
                          onChange={(event) => updateActiveBankAccountField(index, 'bik', event.target.value)}
                        />
                        <Input
                          label="Корр. счет"
                          value={account.correspondentAccount}
                          onChange={(event) => updateActiveBankAccountField(index, 'correspondentAccount', event.target.value)}
                        />
                        <div className="md:col-span-2">
                          <Input
                            label="Расчетный счет"
                            value={account.checkingAccount}
                            onChange={(event) => updateActiveBankAccountField(index, 'checkingAccount', event.target.value)}
                          />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>

          <div className="mt-6 flex justify-end">
            <Button icon={<Icons.Save className="w-4 h-4" />} onClick={save} disabled={isSaving}>
              {isSaving ? 'Сохранение...' : 'Сохранить изменения'}
            </Button>
          </div>
          {message && <p className="mt-3 text-sm text-slate-600 dark:text-slate-400">{message}</p>}
        </Card>

        <Card className="p-6">
          <div className="flex items-center gap-3 mb-6 pb-4 border-b border-slate-100 dark:border-slate-800">
            <div className="p-2 bg-amber-100 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400 rounded-lg">
              <Icons.Settings className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Настройки системы</h2>
              <p className="text-sm text-slate-500 dark:text-slate-400">Настройка поведения по умолчанию.</p>
            </div>
          </div>

          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="font-medium text-slate-900 dark:text-slate-200">Валюта по умолчанию</p>
                <p className="text-sm text-slate-500 dark:text-slate-400">Используется для новых договоров и счетов.</p>
              </div>
              <div className="w-32">
                <Select
                  options={[
                    { value: 'RUB', label: 'RUB (₽)' },
                    { value: 'USD', label: 'USD ($)' },
                    { value: 'EUR', label: 'EUR (€)' },
                  ]}
                  value={normalizedFormData.defaultCurrency}
                  onChange={(event) =>
                    updateGlobalField('defaultCurrency', event.target.value as AppSettings['defaultCurrency'])
                  }
                />
              </div>
            </div>

            <hr className="border-slate-100 dark:border-slate-800" />

            <div className="flex items-center justify-between">
              <div>
                <p className="font-medium text-slate-900 dark:text-slate-200">Автонумерация</p>
                <p className="text-sm text-slate-500 dark:text-slate-400">
                  Автоматически генерировать номера договоров (напр. Д-2023-XXX).
                </p>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  className="sr-only peer"
                  checked={normalizedFormData.autoNumbering}
                  onChange={(event) => updateGlobalField('autoNumbering', event.target.checked)}
                />
                <div className="w-11 h-6 bg-slate-200 dark:bg-slate-700 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 dark:peer-focus:ring-blue-800 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
              </label>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
};
