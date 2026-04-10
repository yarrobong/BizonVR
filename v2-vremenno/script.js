const currency = new Intl.NumberFormat("ru-RU");

const calculator = {
  classicRent: document.getElementById("classicRent"),
  compactRent: document.getElementById("compactRent"),
  leaseTotal: document.getElementById("leaseTotal"),
  classicRentValue: document.getElementById("classicRentValue"),
  compactRentValue: document.getElementById("compactRentValue"),
  leaseTotalValue: document.getElementById("leaseTotalValue"),
  rentSaving: document.getElementById("rentSaving"),
  leaseMonthly: document.getElementById("leaseMonthly"),
  monthlyDelta: document.getElementById("monthlyDelta"),
  postLeaseSaving: document.getElementById("postLeaseSaving")
};

const form = document.getElementById("leadForm");
const formNote = document.getElementById("formNote");

function formatMoney(value) {
  return `${currency.format(Math.round(value)).replace(/\s/g, "\u202F")}\u202F\u20BD`;
}

function formatMonthly(value) {
  const prefix = value >= 0 ? "+" : "?";
  return `${prefix}${formatMoney(Math.abs(value))} / мес`;
}

function formatMoneyRange(min, max) {
  return `${currency.format(Math.round(min))}–${currency.format(Math.round(max))} \u20BD`;
}

function formatCompactValue(text) {
  return text
    .replace(/(\d)\s(?=\d{3}\b)/g, "$1&nbsp;")
    .replace(/\s\u20BD/g, "&nbsp;\u20BD")
    .replace(/\s\/\sмес/g, "&nbsp;/&nbsp;мес");
}

function renderCompactValue(node, text) {
  if (!node) {
    return;
  }

  node.innerHTML = formatCompactValue(text);
}

function parseMoneyRange(text) {
  const matches = text.match(/\d[\d\s]*/g) || [];
  return matches.slice(0, 2).map((item) => Number(item.replace(/\s/g, "")));
}

function updateCalculator() {
  const classicRent = Number(calculator.classicRent.value);
  const compactRent = Number(calculator.compactRent.value);
  const leaseTotal = Number(calculator.leaseTotal.value);
  const leaseMonthly = leaseTotal / 24;
  const rentSaving = classicRent - compactRent;
  const monthlyDelta = rentSaving - leaseMonthly;

  calculator.classicRentValue.textContent = formatMoney(classicRent);
  calculator.compactRentValue.textContent = formatMoney(compactRent);
  calculator.leaseTotalValue.textContent = formatMoney(leaseTotal);
  calculator.rentSaving.textContent = formatMoney(rentSaving);
  calculator.leaseMonthly.textContent = formatMoney(leaseMonthly);
  calculator.monthlyDelta.textContent = formatMonthly(monthlyDelta);
  calculator.postLeaseSaving.textContent = `${formatMoney(rentSaving)} / мес`;
}

function setupCalculator() {
  if (!calculator.classicRent || !calculator.compactRent || !calculator.leaseTotal) {
    return;
  }

  [calculator.classicRent, calculator.compactRent, calculator.leaseTotal].forEach((input) => {
    input.addEventListener("input", updateCalculator);
  });
  updateCalculator();
}

function setupEconomicsScenario() {
  const citySelect = document.getElementById("economicsCity");
  const typeSelect = document.getElementById("economicsType");

  if (!citySelect || !typeSelect) {
    return;
  }

  const data = {
    office: {
      moscow: { label: "Москва / БЦ", classic: 234000, compact: 125000 },
      ekb: { label: "Екатеринбург / БЦ", classic: 138000, compact: 74000 },
      astrakhan: { label: "Астрахань / БЦ", classic: 102000, compact: 54000 },
      nizhnevartovsk: { label: "Нижневартовск / БЦ", classic: 93000, compact: 50000 }
    },
    retail: {
      moscow: { label: "Москва / 1-й этаж", classic: 780000, compact: 416000 },
      ekb: { label: "Екатеринбург / 1-й этаж", classic: 210000, compact: 112000 },
      astrakhan: { label: "Астрахань / 1-й этаж", classic: 114000, compact: 60000 },
      nizhnevartovsk: { label: "Нижневартовск / 1-й этаж", classic: 129000, compact: 69000 }
    },
    mall: {
      moscow: { label: "Москва / ТРЦ", classic: 1400000, compact: 747000 },
      ekb: { label: "Екатеринбург / ТРЦ", classic: 288000, compact: 154000 },
      astrakhan: { label: "Астрахань / ТРЦ", classic: 132000, compact: 71000 },
      nizhnevartovsk: { label: "Нижневартовск / ТРЦ", classic: 114000, compact: 60000 }
    }
  };

  const fields = {
    classicValue: document.getElementById("economicsClassicValue"),
    compactValue: document.getElementById("economicsCompactValue"),
    classicBar: document.getElementById("economicsClassicBar"),
    compactBar: document.getElementById("economicsCompactBar"),
    savingValue: document.getElementById("economicsSavingValue"),
    savingText: document.getElementById("economicsSavingText"),
    compareText: document.getElementById("economicsCompareText"),
    package3EquipmentValue: document.getElementById("package3EquipmentValue"),
    package5EquipmentValue: document.getElementById("package5EquipmentValue"),
    package10EquipmentValue: document.getElementById("package10EquipmentValue"),
    package3SavingValue: document.getElementById("package3SavingValue"),
    package5SavingValue: document.getElementById("package5SavingValue"),
    package10SavingValue: document.getElementById("package10SavingValue"),
    package3SubscriptionValue: document.getElementById("package3SubscriptionValue"),
    package5SubscriptionValue: document.getElementById("package5SubscriptionValue"),
    package10SubscriptionValue: document.getElementById("package10SubscriptionValue"),
    package3EquipmentBar: document.getElementById("package3EquipmentBar"),
    package5EquipmentBar: document.getElementById("package5EquipmentBar"),
    package10EquipmentBar: document.getElementById("package10EquipmentBar"),
    package3SavingBar: document.getElementById("package3SavingBar"),
    package5SavingBar: document.getElementById("package5SavingBar"),
    package10SavingBar: document.getElementById("package10SavingBar"),
    package3SubscriptionBar: document.getElementById("package3SubscriptionBar"),
    package5SubscriptionBar: document.getElementById("package5SubscriptionBar"),
    package10SubscriptionBar: document.getElementById("package10SubscriptionBar")
  };

  function updateEconomics() {
    const scenario = data[typeSelect.value][citySelect.value];
    const saving = scenario.classic - scenario.compact;
    const compactWidth = Math.max((scenario.compact / scenario.classic) * 100, 8);
    const pricePerMeter = scenario.classic / 120;
    const gameSubscription = { min: 50000, max: 69000 };
    const packageData = [
      {
        baselineArea: 60,
        area: 26.5,
        payment: 32607,
        savingField: fields.package3SavingValue,
        paymentField: fields.package3EquipmentValue,
        subscriptionField: fields.package3SubscriptionValue,
        savingBar: fields.package3SavingBar,
        paymentBar: fields.package3EquipmentBar,
        subscriptionBar: fields.package3SubscriptionBar
      },
      {
        baselineArea: 80,
        area: 42,
        payment: 54346,
        savingField: fields.package5SavingValue,
        paymentField: fields.package5EquipmentValue,
        subscriptionField: fields.package5SubscriptionValue,
        savingBar: fields.package5SavingBar,
        paymentBar: fields.package5EquipmentBar,
        subscriptionBar: fields.package5SubscriptionBar
      },
      {
        baselineArea: 120,
        area: 62,
        payment: 108691,
        savingField: fields.package10SavingValue,
        paymentField: fields.package10EquipmentValue,
        subscriptionField: fields.package10SubscriptionValue,
        savingBar: fields.package10SavingBar,
        paymentBar: fields.package10EquipmentBar,
        subscriptionBar: fields.package10SubscriptionBar
      }
    ];
    const packageSavings = packageData.map((item) => (pricePerMeter * item.baselineArea) - (pricePerMeter * item.area));
    const maxGraphValue = Math.max(gameSubscription.max, ...packageSavings, ...packageData.map((item) => item.payment));

    fields.classicValue.textContent = formatMoney(scenario.classic);
    fields.compactValue.textContent = formatMoney(scenario.compact);
    fields.savingValue.textContent = formatMoney(saving);
    fields.savingText.textContent = `В сценарии ${scenario.label} постоянная арендная нагрузка заметно ниже.`;
    fields.compareText.textContent = `Сценарий ${scenario.label}. Ниже — ежемесячный срез по оборудованию, аренде и расходам на игры в классическом формате.`;
    fields.classicBar.style.setProperty("--bar-width", "100%");
    fields.compactBar.style.setProperty("--bar-width", `${compactWidth}%`);

    packageData.forEach((item, index) => {
      const savingValue = packageSavings[index];
      renderCompactValue(item.paymentField, `${formatMoney(item.payment)} / мес`);
      renderCompactValue(item.savingField, `${formatMoney(savingValue)} / мес`);
      renderCompactValue(item.subscriptionField, `${formatMoneyRange(gameSubscription.min, gameSubscription.max)} / мес`);
      item.paymentBar.style.setProperty("--bar-width", `${(item.payment / maxGraphValue) * 100}%`);
      item.savingBar.style.setProperty("--bar-width", `${(savingValue / maxGraphValue) * 100}%`);
      item.subscriptionBar.style.setProperty("--bar-width", `${(gameSubscription.max / maxGraphValue) * 100}%`);
    });
  }

  citySelect.addEventListener("change", updateEconomics);
  typeSelect.addEventListener("change", updateEconomics);
  updateEconomics();
}

function setupReveal() {
  const revealItems = document.querySelectorAll(
    ".section-heading, .panel, .service-step, .audience-card, .value-card, .faq-item"
  );

  revealItems.forEach((item) => {
    item.dataset.reveal = "";
  });

  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) {
        return;
      }

      entry.target.classList.add("is-visible");
      observer.unobserve(entry.target);
    });
  }, { threshold: 0.14 });

  revealItems.forEach((item) => observer.observe(item));
}

function setupSolutionMode() {
  const leaseView = document.getElementById("solutionLeaseView");
  const saleView = document.getElementById("solutionSaleView");
  const leaseButton = document.getElementById("solutionModeLease");
  const saleButton = document.getElementById("solutionModeSale");

  if (!leaseView || !saleView || !leaseButton || !saleButton) {
    return;
  }

  const modes = [
    { name: "Лизинг", view: leaseView },
    { name: "Продажа", view: saleView }
  ];

  let currentMode = 0;

  function renderMode() {
    modes.forEach((mode, index) => {
      mode.view.hidden = index !== currentMode;
      mode.view.classList.toggle("is-active", index === currentMode);
    });

    leaseButton.classList.toggle("is-active", currentMode === 0);
    saleButton.classList.toggle("is-active", currentMode === 1);
    leaseButton.setAttribute("aria-selected", currentMode === 0 ? "true" : "false");
    saleButton.setAttribute("aria-selected", currentMode === 1 ? "true" : "false");
    leaseButton.tabIndex = currentMode === 0 ? 0 : -1;
    saleButton.tabIndex = currentMode === 1 ? 0 : -1;
  }

  leaseButton.addEventListener("click", () => {
    currentMode = 0;
    renderMode();
  });

  saleButton.addEventListener("click", () => {
    currentMode = 1;
    renderMode();
  });

  renderMode();
}

function setupFrictionScenario() {
  const citySelect = document.getElementById("frictionCity");
  const typeSelect = document.getElementById("frictionType");
  const detailsToggle = document.getElementById("frictionDetailsToggle");
  const details = document.getElementById("frictionDetails");

  if (!citySelect || !typeSelect) {
    return;
  }

  const data = {
    office: {
      moscow: {
        label: "Москвы и сценария с БЦ",
        classicRent: "216 000–252 000 \u20BD / мес",
        classicDeposit: "216 000–252 000 \u20BD",
        classicFitout: "720 000–1 800 000 \u20BD",
        classicStart: "1 152 000–2 304 000 \u20BD",
        compactRent: "112 000–130 000 \u20BD / мес",
        compactDeposit: "112 000–130 000 \u20BD",
        compactFitout: "372 000–930 000 \u20BD",
        compactStart: "595 000–1 190 000 \u20BD",
        startupSaving: "557 000–1 114 000 \u20BD",
        monthlySaving: "104 000–122 000 \u20BD / мес"
      },
      ekb: {
        label: "Екатеринбурга и сценария с БЦ",
        classicRent: "120 000–156 000 \u20BD / мес",
        classicDeposit: "120 000–156 000 \u20BD",
        classicFitout: "540 000–960 000 \u20BD",
        classicStart: "780 000–1 272 000 \u20BD",
        compactRent: "62 000–81 000 \u20BD / мес",
        compactDeposit: "62 000–81 000 \u20BD",
        compactFitout: "279 000–496 000 \u20BD",
        compactStart: "403 000–657 000 \u20BD",
        startupSaving: "377 000–615 000 \u20BD",
        monthlySaving: "58 000–75 000 \u20BD / мес"
      },
      astrakhan: {
        label: "Астрахани и сценария с БЦ",
        classicRent: "84 000–120 000 \u20BD / мес",
        classicDeposit: "84 000–120 000 \u20BD",
        classicFitout: "360 000–720 000 \u20BD",
        classicStart: "528 000–960 000 \u20BD",
        compactRent: "43 000–62 000 \u20BD / мес",
        compactDeposit: "43 000–62 000 \u20BD",
        compactFitout: "186 000–372 000 \u20BD",
        compactStart: "273 000–496 000 \u20BD",
        startupSaving: "255 000–464 000 \u20BD",
        monthlySaving: "41 000–58 000 \u20BD / мес"
      },
      nizhnevartovsk: {
        label: "Нижневартовска и сценария с БЦ",
        classicRent: "78 000–108 000 \u20BD / мес",
        classicDeposit: "78 000–108 000 \u20BD",
        classicFitout: "360 000–780 000 \u20BD",
        classicStart: "516 000–996 000 \u20BD",
        compactRent: "40 000–56 000 \u20BD / мес",
        compactDeposit: "40 000–56 000 \u20BD",
        compactFitout: "186 000–403 000 \u20BD",
        compactStart: "267 000–515 000 \u20BD",
        startupSaving: "249 000–481 000 \u20BD",
        monthlySaving: "38 000–52 000 \u20BD / мес"
      }
    },
    retail: {
      moscow: {
        label: "Москвы и сценария с 1-м этажом",
        classicRent: "360 000–1 200 000 \u20BD / мес",
        classicDeposit: "360 000–1 200 000 \u20BD",
        classicFitout: "720 000–1 800 000 \u20BD",
        classicStart: "1 440 000–4 200 000 \u20BD",
        compactRent: "186 000–620 000 \u20BD / мес",
        compactDeposit: "186 000–620 000 \u20BD",
        compactFitout: "372 000–930 000 \u20BD",
        compactStart: "744 000–2 170 000 \u20BD",
        startupSaving: "696 000–2 030 000 \u20BD",
        monthlySaving: "174 000–580 000 \u20BD / мес"
      },
      ekb: {
        label: "Екатеринбурга и сценария с 1-м этажом",
        classicRent: "144 000–276 000 \u20BD / мес",
        classicDeposit: "144 000–276 000 \u20BD",
        classicFitout: "540 000–960 000 \u20BD",
        classicStart: "828 000–1 512 000 \u20BD",
        compactRent: "74 000–143 000 \u20BD / мес",
        compactDeposit: "74 000–143 000 \u20BD",
        compactFitout: "279 000–496 000 \u20BD",
        compactStart: "428 000–781 000 \u20BD",
        startupSaving: "400 000–731 000 \u20BD",
        monthlySaving: "70 000–133 000 \u20BD / мес"
      },
      astrakhan: {
        label: "Астрахани и сценария с 1-м этажом",
        classicRent: "84 000–144 000 \u20BD / мес",
        classicDeposit: "84 000–144 000 \u20BD",
        classicFitout: "360 000–720 000 \u20BD",
        classicStart: "528 000–1 008 000 \u20BD",
        compactRent: "43 000–74 000 \u20BD / мес",
        compactDeposit: "43 000–74 000 \u20BD",
        compactFitout: "186 000–372 000 \u20BD",
        compactStart: "273 000–521 000 \u20BD",
        startupSaving: "255 000–487 000 \u20BD",
        monthlySaving: "41 000–70 000 \u20BD / мес"
      },
      nizhnevartovsk: {
        label: "Нижневартовска и сценария с 1-м этажом",
        classicRent: "84 000–174 000 \u20BD / мес",
        classicDeposit: "84 000–174 000 \u20BD",
        classicFitout: "360 000–780 000 \u20BD",
        classicStart: "528 000–1 128 000 \u20BD",
        compactRent: "43 000–90 000 \u20BD / мес",
        compactDeposit: "43 000–90 000 \u20BD",
        compactFitout: "186 000–403 000 \u20BD",
        compactStart: "273 000–583 000 \u20BD",
        startupSaving: "255 000–545 000 \u20BD",
        monthlySaving: "41 000–84 000 \u20BD / мес"
      }
    },
    mall: {
      moscow: {
        label: "Москвы и сценария с ТРЦ",
        classicRent: "1 000 000–1 800 000 \u20BD / мес",
        classicDeposit: "1 000 000–1 800 000 \u20BD",
        classicFitout: "720 000–1 800 000 \u20BD",
        classicStart: "2 720 000–5 400 000 \u20BD",
        compactRent: "516 000–930 000 \u20BD / мес",
        compactDeposit: "516 000–930 000 \u20BD",
        compactFitout: "372 000–930 000 \u20BD",
        compactStart: "1 404 000–2 790 000 \u20BD",
        startupSaving: "1 316 000–2 610 000 \u20BD",
        monthlySaving: "484 000–870 000 \u20BD / мес"
      },
      ekb: {
        label: "Екатеринбурга и сценария с ТРЦ",
        classicRent: "216 000–360 000 \u20BD / мес",
        classicDeposit: "216 000–360 000 \u20BD",
        classicFitout: "540 000–960 000 \u20BD",
        classicStart: "972 000–1 680 000 \u20BD",
        compactRent: "112 000–186 000 \u20BD / мес",
        compactDeposit: "112 000–186 000 \u20BD",
        compactFitout: "279 000–496 000 \u20BD",
        compactStart: "502 000–868 000 \u20BD",
        startupSaving: "470 000–812 000 \u20BD",
        monthlySaving: "104 000–174 000 \u20BD / мес"
      },
      astrakhan: {
        label: "Астрахани и сценария с ТРЦ",
        classicRent: "96 000–168 000 \u20BD / мес",
        classicDeposit: "96 000–168 000 \u20BD",
        classicFitout: "360 000–720 000 \u20BD",
        classicStart: "552 000–1 056 000 \u20BD",
        compactRent: "50 000–87 000 \u20BD / мес",
        compactDeposit: "50 000–87 000 \u20BD",
        compactFitout: "186 000–372 000 \u20BD",
        compactStart: "285 000–546 000 \u20BD",
        startupSaving: "267 000–510 000 \u20BD",
        monthlySaving: "46 000–81 000 \u20BD / мес"
      },
      nizhnevartovsk: {
        label: "Нижневартовска и сценария с ТРЦ",
        classicRent: "84 000–144 000 \u20BD / мес",
        classicDeposit: "84 000–144 000 \u20BD",
        classicFitout: "360 000–780 000 \u20BD",
        classicStart: "528 000–1 068 000 \u20BD",
        compactRent: "43 000–74 000 \u20BD / мес",
        compactDeposit: "43 000–74 000 \u20BD",
        compactFitout: "186 000–403 000 \u20BD",
        compactStart: "273 000–552 000 \u20BD",
        startupSaving: "255 000–516 000 \u20BD",
        monthlySaving: "41 000–70 000 \u20BD / мес"
      }
    }
  };

  const fields = {
    classicRent: document.getElementById("classicRentRange"),
    classicDeposit: document.getElementById("classicDepositRange"),
    classicFitout: document.getElementById("classicFitoutRange"),
    classicStart: document.getElementById("classicStartRange"),
    compactRent: document.getElementById("compactRentRange"),
    compactDeposit: document.getElementById("compactDepositRange"),
    compactFitout: document.getElementById("compactFitoutRange"),
    compactStart: document.getElementById("compactStartRange"),
    startupSaving: document.getElementById("frictionStartupSaving"),
    monthlySaving: document.getElementById("frictionMonthlySaving"),
    scenarioLabel: document.getElementById("frictionScenarioLabel"),
    startupBullet: document.getElementById("frictionStartupBullet"),
    monthlyBullet: document.getElementById("frictionMonthlyBullet"),
    winsStartupSaving: document.getElementById("winsStartupSaving"),
    classicLaunchPremises: document.getElementById("classicLaunchPremises"),
    compactLaunchPremises: document.getElementById("compactLaunchPremises"),
    classicLaunchTotal: document.getElementById("classicLaunchTotal"),
    compactLaunchTotal: document.getElementById("compactLaunchTotal"),
    launchSetupDelta: document.getElementById("launchSetupDelta"),
    classicLaunchRentNow: document.getElementById("classicLaunchRentNow"),
    compactLaunchRentNow: document.getElementById("compactLaunchRentNow"),
    classicLaunchRentLater: document.getElementById("classicLaunchRentLater"),
    compactLaunchRentLater: document.getElementById("compactLaunchRentLater"),
    launchStartClassicRange: document.getElementById("launchStartClassicRange"),
    launchStartCompactRange: document.getElementById("launchStartCompactRange"),
    launchStartClassicTotal: document.getElementById("launchStartClassicTotal"),
    launchStartCompactTotal: document.getElementById("launchStartCompactTotal"),
    launchStartDelta: document.getElementById("launchStartDelta"),
    launchLaterClassicRange: document.getElementById("launchLaterClassicRange"),
    launchLaterCompactRange: document.getElementById("launchLaterCompactRange"),
    launchLaterClassicTotal: document.getElementById("launchLaterClassicTotal"),
    launchLaterCompactTotal: document.getElementById("launchLaterCompactTotal"),
    launchLaterDelta: document.getElementById("launchLaterDelta"),
    heroSavingsFill: document.getElementById("heroSavingsFill"),
    heroSavingsMarker: document.getElementById("heroSavingsMarker"),
    heroSavingsMarkerValue: document.getElementById("heroSavingsMarkerValue"),
    heroSavingsTotal: document.getElementById("heroSavingsTotal")
  };

  const frictionSection = document.getElementById("market-friction") || document.getElementById("problem");
  let currentStartupSaving = "557 000–1 114 000 \u20BD";
  function updateHeroSavingsMarkerLabel(rangeText) {
    if (!fields.heroSavingsMarkerValue) {
      return;
    }

    fields.heroSavingsMarkerValue.textContent = rangeText;
    if (fields.heroSavingsTotal) {
      fields.heroSavingsTotal.textContent = rangeText;
    }
  }

  function updateHeroSavingsProgress() {
    if (!fields.heroSavingsFill) {
      return;
    }

    const scrollTop = window.scrollY || window.pageYOffset;
    const scrollable = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
    const progress = Math.max(0, Math.min(1, scrollTop / scrollable));
    fields.heroSavingsFill.style.height = `${progress * 100}%`;
    fields.heroSavingsFill.style.marginTop = "0";

    if (!frictionSection || !fields.heroSavingsMarker) {
      return;
    }

    const markerProgress = Math.max(0, Math.min(1, frictionSection.offsetTop / scrollable));
    fields.heroSavingsMarker.style.top = `${markerProgress * 100}%`;
    const reachedFriction = scrollTop + window.innerHeight * 0.35 >= frictionSection.offsetTop;
    fields.heroSavingsMarker.classList.toggle("is-visible", reachedFriction);
  }

  function updateScenario() {
    const scenario = data[typeSelect.value][citySelect.value];

    renderCompactValue(fields.classicRent, scenario.classicRent);
    renderCompactValue(fields.classicDeposit, scenario.classicDeposit);
    renderCompactValue(fields.classicFitout, scenario.classicFitout);
    renderCompactValue(fields.classicStart, scenario.classicStart);
    renderCompactValue(fields.compactRent, scenario.compactRent);
    renderCompactValue(fields.compactDeposit, scenario.compactDeposit);
    renderCompactValue(fields.compactFitout, scenario.compactFitout);
    renderCompactValue(fields.compactStart, scenario.compactStart);
    renderCompactValue(fields.startupSaving, scenario.startupSaving);
    renderCompactValue(fields.monthlySaving, scenario.monthlySaving);
    currentStartupSaving = scenario.startupSaving;
    updateHeroSavingsMarkerLabel(currentStartupSaving);
    updateHeroSavingsProgress();
    if (fields.scenarioLabel) {
      fields.scenarioLabel.textContent = scenario.label;
    }
    if (fields.startupBullet) {
      fields.startupBullet.textContent = scenario.startupSaving;
    }
    if (fields.monthlyBullet) {
      fields.monthlyBullet.textContent = scenario.monthlySaving;
    }
    if (fields.winsStartupSaving) {
      renderCompactValue(fields.winsStartupSaving, scenario.startupSaving);
    }
    if (fields.classicLaunchRentNow) {
      renderCompactValue(fields.classicLaunchRentNow, scenario.classicRent);
    }
    if (fields.compactLaunchRentNow) {
      renderCompactValue(fields.compactLaunchRentNow, scenario.compactRent);
    }
    if (fields.classicLaunchRentLater) {
      renderCompactValue(fields.classicLaunchRentLater, scenario.classicRent);
    }
    if (fields.compactLaunchRentLater) {
      renderCompactValue(fields.compactLaunchRentLater, scenario.compactRent);
    }
    if (fields.launchStartClassicRange && fields.launchStartCompactRange && fields.launchStartDelta) {
      const [classicRentMin, classicRentMax] = parseMoneyRange(scenario.classicRent);
      const [compactRentMin, compactRentMax] = parseMoneyRange(scenario.compactRent);
      const softwareMonthlyMin = 30000;
      const softwareMonthlyMax = 69000;
      const leaseMonthly = 108691;

      const classicStartMin = classicRentMin + softwareMonthlyMin;
      const classicStartMax = classicRentMax + softwareMonthlyMax;
      const compactStartMin = compactRentMin + leaseMonthly;
      const compactStartMax = compactRentMax + leaseMonthly;
      const deltaMin = classicStartMin - compactStartMin;
      const deltaMax = classicStartMax - compactStartMax;

      renderCompactValue(fields.launchStartClassicRange, `${formatMoney(classicRentMin)}–${formatMoney(classicRentMax)} / мес`);
      renderCompactValue(fields.launchStartCompactRange, `${formatMoney(compactRentMin)}–${formatMoney(compactRentMax)} / мес`);
      renderCompactValue(fields.launchStartClassicTotal, `${formatMoney(classicStartMin)}–${formatMoney(classicStartMax)} / мес`);
      renderCompactValue(fields.launchStartCompactTotal, `${formatMoney(compactStartMin)}–${formatMoney(compactStartMax)} / мес`);
      renderCompactValue(fields.launchStartDelta, `${formatMoney(deltaMin)}–${formatMoney(deltaMax)} / мес`);

      if (fields.launchLaterClassicRange && fields.launchLaterCompactRange && fields.launchLaterDelta) {
        const classicLaterMin = classicRentMin + softwareMonthlyMin;
        const classicLaterMax = classicRentMax + softwareMonthlyMax;
        const compactLaterMin = compactRentMin;
        const compactLaterMax = compactRentMax;
        const laterDeltaMin = classicLaterMin - compactLaterMin;
        const laterDeltaMax = classicLaterMax - compactLaterMax;

        renderCompactValue(fields.launchLaterClassicRange, `${formatMoney(classicRentMin)}–${formatMoney(classicRentMax)} / мес`);
        renderCompactValue(fields.launchLaterCompactRange, `${formatMoney(compactRentMin)}–${formatMoney(compactRentMax)} / мес`);
        renderCompactValue(fields.launchLaterClassicTotal, `${formatMoney(classicLaterMin)}–${formatMoney(classicLaterMax)} / мес`);
        renderCompactValue(fields.launchLaterCompactTotal, `${formatMoney(compactLaterMin)}–${formatMoney(compactLaterMax)} / мес`);
        renderCompactValue(fields.launchLaterDelta, `${formatMoney(laterDeltaMin)}–${formatMoney(laterDeltaMax)} / мес`);
      }
    }
    if (fields.classicLaunchPremises && fields.compactLaunchPremises && fields.classicLaunchTotal && fields.compactLaunchTotal) {
      const [classicMin, classicMax] = parseMoneyRange(scenario.classicStart);
      const [compactMin, compactMax] = parseMoneyRange(scenario.compactStart);
      const vrMin = 503660;
      const vrMax = 683660;
      const electronics = 300000;
      const softwareMin = 30000;
      const softwareMax = 69000;
      const securityDeposit = 300000;
      const gamesMin = 49990;
      const gamesMax = 179990;
      const classicLaunchMin = classicMin + vrMin + electronics + softwareMin;
      const classicLaunchMax = classicMax + vrMax + electronics + softwareMax;
      const compactLaunchMin = compactMin + securityDeposit + vrMin + electronics + gamesMin;
      const compactLaunchMax = compactMax + securityDeposit + vrMax + electronics + gamesMax;

      renderCompactValue(fields.classicLaunchPremises, scenario.classicStart);
      renderCompactValue(fields.compactLaunchPremises, scenario.compactStart);
      renderCompactValue(fields.classicLaunchTotal, `${formatMoney(classicLaunchMin)}–${formatMoney(classicLaunchMax)}`);
      renderCompactValue(fields.compactLaunchTotal, `${formatMoney(compactLaunchMin)}–${formatMoney(compactLaunchMax)}`);
      renderCompactValue(fields.launchSetupDelta, `${formatMoney(classicLaunchMin - compactLaunchMin)}–${formatMoney(classicLaunchMax - compactLaunchMax)}`);
    }
  }

  citySelect.addEventListener("change", updateScenario);
  typeSelect.addEventListener("change", updateScenario);
  window.addEventListener("scroll", updateHeroSavingsProgress, { passive: true });
  window.addEventListener("resize", updateHeroSavingsProgress);

  updateScenario();
}

function setupForm() {
  if (!form || !formNote) {
    return;
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();

    const payload = Object.fromEntries(new FormData(form).entries());
    console.log("Lead payload:", payload);

    formNote.textContent = "Запрос сохранён. Можно связаться с вами и подготовить стартовый расчёт по городу, формату и нагрузке.";
    formNote.classList.add("is-success");
    form.reset();
  });
}

function setupGameModal() {
  const cards = document.querySelectorAll(".game-card, .single-game-card");
  const modal = document.getElementById("gameModal");
  const dialog = modal ? modal.querySelector(".game-modal-dialog") : null;
  const stage = document.getElementById("gameModalStage");
  const title = document.getElementById("gameModalTitle");
  const meta = document.getElementById("gameModalMeta");
  const description = document.getElementById("gameModalDescription");
  const specs = document.getElementById("gameModalSpecs");
  const prev = document.getElementById("gameModalPrev");
  const next = document.getElementById("gameModalNext");
  const closeButtons = document.querySelectorAll("[data-close-modal]");

  if (!cards.length || !modal || !dialog || !stage || !title || !meta || !description || !specs || !prev || !next) {
    return;
  }

  const gameData = {
    "Pavlov Shack": {
      eyebrow: "Многопользовательская игра",
      meta: ["Аудитория 14+", "до 10 человек", "Шутер / PvP"],
      specs: [
        { label: "Основные режимы", value: "соревновательные матчи 5 на 5, командные перестрелки, Gun Game и пользовательские сценарии" },
        { label: "Как проходит сессия", value: "игроки делятся на команды и играют короткие раунды или быстрые PvP-матчи с высокой динамикой" },
        { label: "Контент внутри", value: "около 20 базовых карт для Shack, разные сеттинги, 65+ видов оружия и модификации от сообщества" },
        { label: "Игроки", value: "до 10 человек" },
        { label: "Сложность", value: "средняя" }
      ],
      description: "Pavlov Shack — командный VR-шутер с сильным акцентом на realistic weapon handling, ручную перезарядку и быстрый соревновательный ритм. В официальных описаниях Steam, PlayStation и Meta игра подается как community-driven multiplayer sandbox: она сочетает привычные PvP-форматы вроде Search & Destroy, Deathmatch, Gun Game и Team Deathmatch с более вариативными сценариями, включая TTT, офлайн-режимы, тренировочные пространства и пользовательские модификации. Отдельно подчеркиваются 5v5-сценарии, более 65 интерактивных видов оружия и навесов, proximity voice chat, техника и карты в modern- и WWII-сеттингах. За счет этого Pavlov хорошо работает не только как \"VR-аналог Counter-Strike\", но и как игра с высокой реиграбельностью: ее легко объяснить новой аудитории, при этом она остается интересной для возвращающихся игроков, командных сессий и соревновательного потока.",
      highlights: ["понятная механика для широкой аудитории", "подходит для турнирных и командных сессий", "сильный аналог Counter-Strike в VR"],
      slides: [
        { type: "video", src: "img/Pavlov VR/PavlovTrailer.mp4", label: "Трейлер", title: "Pavlov Shack" },
        { type: "image", src: "img/Pavlov VR/pavlovvr_1.png", label: "Скриншот", title: "Командный шутер" },
        { type: "image", src: "img/Pavlov VR/pavlovvr_2.jpg", label: "Скриншот", title: "PvP-сессии" },
        { type: "image", src: "img/Pavlov VR/pavlovvr_3.jpg", label: "Скриншот", title: "Командная динамика" },
        { type: "image", src: "img/Pavlov VR/pavlovvr_4.jpg", label: "Скриншот", title: "Тактический матч" },
        { type: "image", src: "img/Pavlov VR/pavlovvr_5.jpg", label: "Скриншот", title: "Для потока" },
        { type: "image", src: "img/Pavlov VR/pavlovvr_6.jpg", label: "Скриншот", title: "До 10 игроков" }
      ]
    },
    Breachers: {
      eyebrow: "Многопользовательская игра",
      meta: ["Аудитория 16+", "до 10 человек", "Тактика / PvP"],
      specs: [
        { label: "Основной режим", value: "тактические раунды 5 на 5: одна команда штурмует объект, вторая удерживает и обороняет его" },
        { label: "Как проходит сессия", value: "матч строится вокруг коротких раундов, смены ролей, гаджетов и координации внутри команды" },
        { label: "Контент внутри", value: "тактические карты ближнего боя, штурм через окна и стены, канаты, гаджеты, оружие и кастомизация" },
        { label: "Игроки", value: "до 10 человек" },
        { label: "Сложность", value: "сложная" }
      ],
      description: "Breachers — тактический 5v5 VR-шутер, который чаще всего описывают как смесь Counter-Strike и Rainbow Six Siege в виртуальной реальности. По официальным описаниям Steam и материалам разработчика, игра делает ставку не на хаотичную стрельбу, а на планирование штурма, оборону объекта, использование гаджетов и командную коммуникацию. Здесь важны не только меткость, но и вход через окна, канаты, проломы в стенах, постановка ловушек, работа с дронами и правильное распределение ролей внутри команды. За счет такого темпа Breachers хорошо подходит для более взрослой аудитории, повторных визитов и премиального PvP-сценария, когда площадке нужен не просто быстрый экшен, а более серьезный командный формат с высокой вовлеченностью.",
      highlights: ["более зрелый стиль игры", "подходит для соревновательных матчей", "хорошо работает как контент для повторных визитов"],
      slides: [
        { type: "video", src: "img/Breachers/breachers_trailer.mp4", label: "Трейлер", title: "Breachers" },
        { type: "image", src: "img/Breachers/breachers_1.jpg", label: "Скриншот", title: "Breachers" },
        { type: "image", src: "img/Breachers/breachers_2.jpg", label: "Скриншот", title: "Breachers" },
        { type: "image", src: "img/Breachers/breachers_3.jpg", label: "Скриншот", title: "Breachers" },
        { type: "image", src: "img/Breachers/breachers_4.jpg", label: "Скриншот", title: "Breachers" },
        { type: "image", src: "img/Breachers/breachers_5.jpg", label: "Скриншот", title: "Breachers" },
        { type: "image", src: "img/Breachers/breachers_6.jpg", label: "Скриншот", title: "Breachers" },
        { type: "image", src: "img/Breachers/breachers_7.jpg", label: "Скриншот", title: "Breachers" },
        { type: "image", src: "img/Breachers/breachers_8.jpg", label: "Скриншот", title: "Breachers" }
      ]
    },
    "Zero Caliber 2": {
      eyebrow: "Многопользовательская игра",
      meta: ["До 10 человек", "Шутер", "Action"],
      specs: [
        { label: "Основные режимы", value: "сюжетная кампания, кооператив до 4 игроков и отдельные PvP-матчи" },
        { label: "Как проходит сессия", value: "игроки проходят миссии вместе или заходят в классические многопользовательские перестрелки" },
        { label: "Контент внутри", value: "8+ часов кампании, 60+ видов оружия и обвесов, кастомизация и нативная поддержка модов" },
        { label: "Игроки", value: "до 4 игроков в кооперативе, до 10 в PvP" },
        { label: "Сложность", value: "средняя" }
      ],
      description: "Zero Caliber 2 — военный VR-шутер, который строится вокруг кинематографичной кампании, кооператива и более \"полноценного FPS-пакета\", чем обычный аренный матч. В официальных описаниях подчеркиваются 8+ часов сюжетного контента, возможность пройти кампанию в кооперативе до 4 игроков, PvP-режимы до 10 человек, большой арсенал оружия и кастомизация персонажа. Для площадки это полезно тем, что игра закрывает сразу два сценария: кооперативный контент для компании друзей и более насыщенный одиночный или командный action-опыт для тех, кому уже мало простого короткого PvP.",
      highlights: ["подходит для кооперативных команд", "сильный боевой сценарий", "расширяет жанровую матрицу площадки"],
      slides: [
        { type: "video", src: "img/Zero Caliber 2/zc2_trailer_1.mp4", label: "Трейлер", title: "Zero Caliber 2" },
        { type: "video", src: "img/Zero Caliber 2/zc2_trailer_2.mp4", label: "Трейлер", title: "Zero Caliber 2" },
        { type: "image", src: "img/Zero Caliber 2/zc2_1.jpg", label: "Скриншот", title: "Zero Caliber 2" },
        { type: "image", src: "img/Zero Caliber 2/zc2_2.jpg", label: "Скриншот", title: "Zero Caliber 2" },
        { type: "image", src: "img/Zero Caliber 2/zc2_3.jpg", label: "Скриншот", title: "Zero Caliber 2" },
        { type: "image", src: "img/Zero Caliber 2/zc2_4.jpg", label: "Скриншот", title: "Zero Caliber 2" },
        { type: "image", src: "img/Zero Caliber 2/zc2_5.jpg", label: "Скриншот", title: "Zero Caliber 2" }
      ]
    },
    "Green Hell VR": {
      eyebrow: "Многопользовательская игра",
      meta: ["Аудитория 14+", "до 4 человек", "Survival"],
      specs: [
        { label: "Основные режимы", value: "сюжетное выживание, свободный survival и кооператив до 4 игроков" },
        { label: "Как проходит сессия", value: "игроки исследуют джунгли, собирают ресурсы, крафтят предметы, строят укрытия и выживают вместе" },
        { label: "Контент внутри", value: "открытые джунгли Амазонии, крафт, охота, строительство, защита от хищников и враждебной среды" },
        { label: "Игроки", value: "до 4 человек" },
        { label: "Сложность", value: "сложная" }
      ],
      description: "Green Hell VR — survival-игра в декорациях амазонских джунглей, где акцент смещен с стрельбы на выживание, исследование и работу с окружением. Официальные описания Steam и PlayStation подают ее как open-world survival experience: игрок остается без еды и снаряжения, учится добывать ресурсы, лечить травмы, строить укрытия, охотиться и адаптироваться к опасной среде. В кооперативной версии до 4 игроков это превращается в более спокойный, но глубокий командный сценарий. Для площадки Green Hell полезен тем, что расширяет библиотеку за пределы шутеров и дает атмосферный формат для аудитории, которой важны не только экшен и соревновательность, но и погружение в мир.",
      highlights: ["атмосферный survival-сценарий", "разнообразит библиотеку жанров", "хорошо работает на более длинных сессиях"],
      slides: [
        { type: "video", src: "img/Green Hell VR/gh_trailer_1.mp4", label: "Трейлер", title: "Green Hell VR" },
        { type: "video", src: "img/Green Hell VR/gh_trailer_2.mp4", label: "Трейлер", title: "Green Hell VR" },
        { type: "image", src: "img/Green Hell VR/gh_1.jpg", label: "Скриншот", title: "Green Hell VR" },
        { type: "image", src: "img/Green Hell VR/gh_2.jpg", label: "Скриншот", title: "Green Hell VR" },
        { type: "image", src: "img/Green Hell VR/gh_3.jpg", label: "Скриншот", title: "Green Hell VR" },
        { type: "image", src: "img/Green Hell VR/gh_4.jpg", label: "Скриншот", title: "Green Hell VR" },
        { type: "image", src: "img/Green Hell VR/gh_5.jpg", label: "Скриншот", title: "Green Hell VR" }
      ]
    },
    "Arizona Sunshine 2": {
      eyebrow: "Многопользовательская игра",
      meta: ["Аудитория 12+", "2–4 человека", "Adventure / Co-op"],
      specs: [
        { label: "Основные режимы", value: "сюжетная кампания на 2 игроков и Horde-режим до 4 человек" },
        { label: "Как проходит сессия", value: "игроки вместе проходят зомби-сценарии, отбиваются от волн врагов и двигаются по сюжетным главам" },
        { label: "Контент внутри", value: "кампания, Horde-карты, огнестрельное и ближнее оружие, кооператив и более кинематографичная подача" },
        { label: "Игроки", value: "2–4 человека" },
        { label: "Сложность", value: "средняя" }
      ],
      description: "Arizona Sunshine 2 — кооперативный VR-экшен в зомби-сеттинге, который делает ставку на приключение, юмор, активный бой и более кинематографичную подачу, чем классические аренные шутеры. По официальным материалам игра включает полноценную кампанию для двух игроков, Horde-режим до 4 человек и cross-platform кооператив. Внутри есть как огнестрельное, так и ближнее оружие, а сама структура хорошо подходит для парных и небольших командных сессий. Для площадки это сильный сюжетный co-op-контент: его легче продавать широкой аудитории, он хорошо работает на эмоцию и дает понятный сценарий совместного прохождения, а не только соревновательного PvP.",
      highlights: ["зомби-тематика хорошо продает эмоцию", "подходит для кооперативных сессий", "понятный приключенческий формат"],
      slides: [
        { type: "video", src: "img/Arizona Sunshine 2/as2_trailer.mp4", label: "Трейлер", title: "Arizona Sunshine 2" },
        { type: "image", src: "img/Arizona Sunshine 2/as_1.png", label: "Скриншот", title: "Arizona Sunshine 2" },
        { type: "image", src: "img/Arizona Sunshine 2/as_2.png", label: "Скриншот", title: "Arizona Sunshine 2" },
        { type: "image", src: "img/Arizona Sunshine 2/as_3.png", label: "Скриншот", title: "Arizona Sunshine 2" },
        { type: "image", src: "img/Arizona Sunshine 2/as_4.png", label: "Скриншот", title: "Arizona Sunshine 2" }
      ]
    },
    "Drunkn Bar Fight": {
      eyebrow: "Многопользовательская игра",
      meta: ["Аудитория 12+", "до 4 человек", "Party / Action"],
      specs: [
        { label: "Основной формат", value: "короткие веселые сессии в барных и аренных сценах без сложного обучения" },
        { label: "Как проходит сессия", value: "игроки быстро включаются в физический party-экшен и взаимодействуют с предметами вокруг" },
        { label: "Контент внутри", value: "несколько барных и развлекательных сцен, физика предметов и легкий хаотичный бой" },
        { label: "Игроки", value: "до 4 человек" },
        { label: "Сложность", value: "легкая" }
      ],
      description: "Drunkn Bar Fight — намеренно простой и хаотичный party-action, который строится не на глубокой механике, а на мгновенно считываемом веселье. Игрок быстро понимает, что делать, почти без обучения: вокруг много интерактивных предметов, действие развивается в барных сценах, а сам темп хорошо подходит для коротких развлекательных сессий. Для площадки это полезный low-friction-контент: игра помогает посадить в VR тех, кто не хочет сложный шутер или длинное приключение, и хорошо работает как легкий, понятный и смешной формат для компаний.",
      highlights: ["простая механика", "легкий фан для компаний", "хороший сценарий для быстрых сессий"],
      slides: [
        { type: "video", src: "img/Drunkn Bar/db_trailer.mp4", label: "Трейлер", title: "Drunkn Bar Fight" },
        { type: "image", src: "img/Drunkn Bar/db_1.jpg", label: "Скриншот", title: "Drunkn Bar Fight" },
        { type: "image", src: "img/Drunkn Bar/db_2.jpg", label: "Скриншот", title: "Drunkn Bar Fight" },
        { type: "image", src: "img/Drunkn Bar/db_3.jpg", label: "Скриншот", title: "Drunkn Bar Fight" },
        { type: "image", src: "img/Drunkn Bar/db_4.jpg", label: "Скриншот", title: "Drunkn Bar Fight" }
      ]
    },
    "Bow-Bots": {
      eyebrow: "Многопользовательская игра",
      meta: ["Аудитория 12+", "до 10 человек", "Arcade / Team Play"],
      specs: [
        { label: "Основной формат", value: "массовые аркадные матчи с понятной механикой и быстрым входом" },
        { label: "Как проходит сессия", value: "игроки сразу попадают в короткий командный сценарий без долгого обучения и сложных правил" },
        { label: "Контент внутри", value: "арены под массовую игру, легкая аркадная механика и формат для потока" },
        { label: "Игроки", value: "до 10 человек" },
        { label: "Сложность", value: "легкая" }
      ],
      description: "Bow-Bots — аркадная многопользовательская игра, рассчитанная на быстрый вход, массовый формат и мягкое знакомство с VR. Ее ценность не в глубокой тактике, а в том, что она позволяет быстро запустить большую группу игроков в простой и считываемый командный сценарий. Для площадки это важный потоковый контент: такую игру проще объяснить подросткам, семейной аудитории и тем, кто впервые надевает шлем, а значит она хорошо закрывает массовые сессии и снижает барьер входа в VR.",
      highlights: ["до 10 участников", "аркадная и понятная механика", "подходит для семейного и подросткового сегмента"],
      slides: [
        { type: "image", src: "img/Bow Bots/bb_1.jpg", label: "Скриншот", title: "Bow-Bots" },
        { type: "image", src: "img/Bow Bots/bb_2.jpg", label: "Скриншот", title: "Bow-Bots" },
        { type: "image", src: "img/Bow Bots/bb_3.jpg", label: "Скриншот", title: "Bow-Bots" },
        { type: "image", src: "img/Bow Bots/bb_4.jpg", label: "Скриншот", title: "Bow-Bots" },
        { type: "image", src: "img/Bow Bots/bb_5.jpg", label: "Скриншот", title: "Bow-Bots" },
        { type: "image", src: "img/Bow Bots/bb_6.jpg", label: "Скриншот", title: "Bow-Bots" }
      ]
    },
    "Gorilla Tag": {
      eyebrow: "Многопользовательская игра",
      meta: ["Аудитория 12+", "до 10 человек", "Party / Motion"],
      specs: [
        { label: "Основной формат", value: "массовая party-игра с очень быстрым входом и акцентом на движение" },
        { label: "Как проходит сессия", value: "игроки активно перемещаются, догоняют друг друга, прячутся и соревнуются в коротких динамичных раундах" },
        { label: "Контент внутри", value: "простые правила, узнаваемая механика перемещения руками, несколько режимов и высокий потенциал реиграбельности" },
        { label: "Игроки", value: "до 10 человек" },
        { label: "Сложность", value: "легкая" }
      ],
      description: "Gorilla Tag — одна из самых понятных и вирусных VR-игр для широкой аудитории. Ее сила в том, что игроку почти не нужно обучение: базовая цель и механика считываются за минуты, а необычный способ перемещения быстро превращает сессию в активный, шумный и запоминающийся party-сценарий. Для площадки это особенно ценно как контент с низким порогом входа и сильным потенциалом повторных визитов: игра хорошо работает на подростковую аудиторию, компании друзей и потоковые развлекательные сессии, где важны не сложные правила, а мгновенное вовлечение.",
      highlights: ["мгновенно понятная механика", "сильный party-потенциал", "подходит для массовых и повторных сессий"],
      slides: [
        { type: "video", src: "img/Gorilla Tag/gt_trailer.mp4", label: "Трейлер", title: "Gorilla Tag" },
        { type: "image", src: "img/Gorilla Tag/gt_1.jpg", label: "Скриншот", title: "Gorilla Tag" },
        { type: "image", src: "img/Gorilla Tag/gt_2.jpg", label: "Скриншот", title: "Gorilla Tag" },
        { type: "image", src: "img/Gorilla Tag/gt_3.jpg", label: "Скриншот", title: "Gorilla Tag" },
        { type: "image", src: "img/Gorilla Tag/gt_4.jpg", label: "Скриншот", title: "Gorilla Tag" },
        { type: "image", src: "img/Gorilla Tag/gt_5.jpg", label: "Скриншот", title: "Gorilla Tag" }
      ]
    },
    "Windlands 2": {
      eyebrow: "Многопользовательская игра",
      meta: ["До 4 человек", "Action", "Mobility"],
      specs: [
        { label: "Основной формат", value: "кооперативное приключение с акцентом на перемещение, полет и бой на больших локациях" },
        { label: "Как проходит сессия", value: "игроки двигаются по вертикальным уровням, используют крюки и проходят action-сценарии вместе" },
        { label: "Контент внутри", value: "крупные уровни, боссы, кооператив и механики, которые подчеркивают движение в VR" },
        { label: "Игроки", value: "до 4 человек" },
        { label: "Сложность", value: "сложная" }
      ],
      description: "Windlands 2 — кооперативный VR-action, построенный вокруг перемещения, крюков, скорости и больших вертикальных пространств. В отличие от шутеров, здесь главный акцент сделан не на стрельбе как таковой, а на ощущении движения и прохождении локаций в активном темпе. Для площадки это особенно ценно как демонстрация физически подвижного VR-формата: игра хорошо показывает преимущества дорожки, дает более необычный тип впечатления и помогает расширить библиотеку за пределы стандартных PvP- и зомби-сценариев.",
      highlights: ["подчеркивает mobility-возможности", "подходит для активных сценариев", "расширяет жанр beyond shooter"],
      slides: [
        { type: "video", src: "img/Windlands 2/w2_trailer.mp4", label: "Трейлер", title: "Windlands 2" },
        { type: "image", src: "img/Windlands 2/w2_1.jpg", label: "Скриншот", title: "Windlands 2" },
        { type: "image", src: "img/Windlands 2/w2_2.jpg", label: "Скриншот", title: "Windlands 2" },
        { type: "image", src: "img/Windlands 2/w2_3.jpg", label: "Скриншот", title: "Windlands 2" },
        { type: "image", src: "img/Windlands 2/w2_4.jpg", label: "Скриншот", title: "Windlands 2" },
        { type: "image", src: "img/Windlands 2/w2_5.jpg", label: "Скриншот", title: "Windlands 2" }
      ]
    },
    "Warhammer 40,000: Battle Sister": {
      eyebrow: "Многопользовательская игра",
      meta: ["Аудитория 14+", "до 2 человек", "Sci-fi / Co-op"],
      specs: [
        { label: "Основной формат", value: "сюжетный sci-fi экшен и кооперативный формат для небольшой команды" },
        { label: "Как проходит сессия", value: "игроки проходят боевые эпизоды в мрачном sci-fi-сеттинге и работают как парный premium-сценарий" },
        { label: "Контент внутри", value: "сюжетные уровни, ближний и дальний бой, узнаваемая вселенная Warhammer 40,000" },
        { label: "Игроки", value: "до 2 человек" },
        { label: "Сложность", value: "средняя" }
      ],
      description: "Warhammer 40,000: Battle Sister — sci-fi VR-экшен на сильной и узнаваемой вселенной, который работает как более нишевый, но ценностный premium-контент. Игра интересна не массовостью, а тем, что добавляет в библиотеку тяжелый sci-fi-сеттинг, фанатскую аудиторию и более \"коллекционный\" тип тайтла. Для площадки это способ усилить воспринимаемую глубину каталога: даже если контент не будет самым массовым, он помогает показать, что библиотека собрана не только из аркад и шутеров для потока, но и из заметных франшиз с более дорогим восприятием.",
      highlights: ["нишевая фанатская аудитория", "sci-fi сегмент в каталоге", "подходит для premium-подачи"],
      slides: [
        { type: "video", src: "img/Warhammer 40,000 Battle Sister/w_trailer.mp4", label: "Трейлер", title: "Warhammer 40,000: Battle Sister" },
        { type: "image", src: "img/Warhammer 40,000 Battle Sister/w_1.jpg", label: "Скриншот", title: "Warhammer 40,000: Battle Sister" },
        { type: "image", src: "img/Warhammer 40,000 Battle Sister/w_2.jpg", label: "Скриншот", title: "Warhammer 40,000: Battle Sister" },
        { type: "image", src: "img/Warhammer 40,000 Battle Sister/w_3.jpg", label: "Скриншот", title: "Warhammer 40,000: Battle Sister" },
        { type: "image", src: "img/Warhammer 40,000 Battle Sister/w_4.jpg", label: "Скриншот", title: "Warhammer 40,000: Battle Sister" },
        { type: "image", src: "img/Warhammer 40,000 Battle Sister/w_5.jpg", label: "Скриншот", title: "Warhammer 40,000: Battle Sister" }
      ]
    },
    "Elven Assassin": {
      eyebrow: "Многопользовательская игра",
      meta: ["Аудитория 12+", "до 8 человек", "Co-op / Fantasy"],
      specs: [
        { label: "Основные режимы", value: "кооперативная защита башни до 4 игроков и PvP-режимы до 8 игроков" },
        { label: "Как проходит сессия", value: "игроки вместе отбиваются от волн врагов, распределяют цели и защищают позиции" },
        { label: "Контент внутри", value: "волны противников, fantasy-сеттинг, лук как ключевая механика и короткие командные сессии" },
        { label: "Игроки", value: "кооператив до 4 человек, PvP до 8 человек" },
        { label: "Сложность", value: "легкая" }
      ],
      description: "Elven Assassin — кооперативная fantasy-игра, которая строится вокруг очень понятной механики стрельбы из лука и совместной защиты позиции. Для площадки это удобный формат мягкого входа: игрок быстро понимает цель, не перегружается сложными правилами и при этом получает командный сценарий, который хорошо работает на компании друзей, семейные группы и короткие волновые сессии. Игра полезна как более спокойная альтернатива шутерам, особенно когда нужен узнаваемый fantasy-контент без высокого порога входа.",
      highlights: ["понятная механика с луком", "подходит для компаний и семейных групп", "мягкий командный сценарий"],
      slides: [
        { type: "video", src: "img/Elven Assasin/ea_trailer.mp4", label: "Трейлер", title: "Elven Assassin" },
        { type: "image", src: "img/Elven Assasin/ea_1.jpg", label: "Скриншот", title: "Elven Assassin" },
        { type: "image", src: "img/Elven Assasin/ea_2.jpg", label: "Скриншот", title: "Elven Assassin" },
        { type: "image", src: "img/Elven Assasin/ea_3.jpg", label: "Скриншот", title: "Elven Assassin" },
        { type: "image", src: "img/Elven Assasin/ea_4.jpg", label: "Скриншот", title: "Elven Assassin" },
        { type: "image", src: "img/Elven Assasin/ea_5.jpg", label: "Скриншот", title: "Elven Assassin" },
        { type: "image", src: "img/Elven Assasin/ea_6.jpg", label: "Скриншот", title: "Elven Assassin" },
        { type: "image", src: "img/Elven Assasin/ea_7.jpg", label: "Скриншот", title: "Elven Assassin" },
        { type: "image", src: "img/Elven Assasin/ea_8.jpg", label: "Скриншот", title: "Elven Assassin" },
        { type: "image", src: "img/Elven Assasin/ea_9.jpg", label: "Скриншот", title: "Elven Assassin" }
      ]
    },
    "Loco Dojo": {
      eyebrow: "Многопользовательская игра",
      meta: ["Аудитория 12+", "до 4 человек", "Party / Mini-games"],
      specs: [
        { label: "Основной формат", value: "набор мини-игр и коротких соревновательных сценариев для компании" },
        { label: "Как проходит сессия", value: "игроки быстро переключаются между мини-играми и соревнуются в легких party-испытаниях" },
        { label: "Контент внутри", value: "несколько мини-игр, юмористическая подача, быстрые раунды и простой вход без долгого обучения" },
        { label: "Игроки", value: "до 4 человек" },
        { label: "Сложность", value: "легкая" }
      ],
      description: "Loco Dojo — party-игра в формате набора мини-игр, рассчитанная на быстрый вход и развлекательные сессии для компании. Для площадки это полезный контент низкого порога: игрокам не нужно долго разбираться в правилах, а сама структура хорошо подходит для дней рождения, небольших компаний друзей и легких соревновательных сценариев, где важны смех, скорость и смена активности, а не глубокая механика.",
      highlights: ["быстрый вход без долгого обучения", "подходит для дней рождения и компаний", "короткие легкие соревновательные сессии"],
      slides: [
        { type: "video", src: "img/Loco Dojo/ld_trailer.mp4", label: "Трейлер", title: "Loco Dojo" },
        { type: "image", src: "img/Loco Dojo/ld_1.jpg", label: "Скриншот", title: "Loco Dojo" },
        { type: "image", src: "img/Loco Dojo/ld_2.jpg", label: "Скриншот", title: "Loco Dojo" },
        { type: "image", src: "img/Loco Dojo/ld_3.jpg", label: "Скриншот", title: "Loco Dojo" },
        { type: "image", src: "img/Loco Dojo/ld_4.jpg", label: "Скриншот", title: "Loco Dojo" },
        { type: "image", src: "img/Loco Dojo/ld_5.jpg", label: "Скриншот", title: "Loco Dojo" }
      ]
    },
    "Batman Arkham Shadow": {
      eyebrow: "Одиночная игра",
      meta: ["Single-player", "Action / Story"],
      specs: [
        { label: "Режимы", value: "сюжетная одиночная кампания" },
        { label: "Карты", value: "story-driven уровни и миссии" },
        { label: "Формат сессии", value: "премиальный solo-опыт" },
        { label: "Игроки", value: "1 игрок" },
        { label: "Сложность", value: "средняя" }
      ],
      description: "Сильный одиночный action-сценарий на узнаваемой IP, подходящий для индивидуальных сессий и premium-одиночного контента.",
      highlights: ["известная франшиза", "работает как premium-одиночный сценарий", "подходит для расширения ценности библиотеки"],
      slides: [
        { theme: "cover-hero", label: "Одиночный сценарий", title: "Batman Arkham Shadow" },
        { theme: "cover-stealth", label: "Action / Story", title: "Премиальный одиночный опыт" },
        { theme: "cover-sandbox", label: "Для библиотеки", title: "Известная IP" }
      ]
    },
    "Assassin’s Creed Nexus VR": {
      eyebrow: "Одиночная игра",
      meta: ["Single-player", "Action / Stealth"],
      specs: [
        { label: "Режимы", value: "сюжетная кампания с stealth/action-сегментами" },
        { label: "Карты", value: "исторические и story-локации" },
        { label: "Формат сессии", value: "сюжетный solo-формат" },
        { label: "Игроки", value: "1 игрок" },
        { label: "Сложность", value: "сложная" }
      ],
      description: "Одиночный action-опыт с сильной франшизой, который помогает расширить библиотеку за пределы стрелковых и party-сценариев.",
      highlights: ["узнаваемый бренд", "story-driven контент", "подходит для более взрослой аудитории"],
      slides: [
        { theme: "cover-stealth", label: "Stealth / Action", title: "Assassin’s Creed Nexus VR" },
        { theme: "cover-hero", label: "Single-player", title: "Известная франшиза" },
        { theme: "cover-motion", label: "Для библиотеки", title: "Сюжетный опыт" }
      ]
    },
    BONELAB: {
      eyebrow: "Одиночная игра",
      meta: ["Single-player", "Sandbox / Physics"],
      specs: [
        { label: "Режимы", value: "sandbox и physics-driven сценарии" },
        { label: "Карты", value: "экспериментальные уровни и лабораторные зоны" },
        { label: "Формат сессии", value: "single-player sandbox" },
        { label: "Игроки", value: "1 игрок" },
        { label: "Сложность", value: "средняя" }
      ],
      description: "Физический sandbox-сценарий, который хорошо показывает возможности VR и подходит для более экспериментального контента.",
      highlights: ["physics-driven опыт", "хорошо показывает возможности VR", "усиливает вариативность библиотеки"],
      slides: [
        { theme: "cover-sandbox", label: "Sandbox", title: "BONELAB" },
        { theme: "cover-motion", label: "Physics", title: "Экспериментальный VR" },
        { theme: "cover-melee", label: "Single-player", title: "Вариативный контент" }
      ]
    },
    "Blade & Sorcery: Nomad": {
      eyebrow: "Одиночная игра",
      meta: ["Single-player", "Melee / Sandbox"],
      specs: [
        { label: "Режимы", value: "melee sandbox и одиночные боевые сценарии" },
        { label: "Карты", value: "арены и fantasy-локации" },
        { label: "Формат сессии", value: "single-player action" },
        { label: "Игроки", value: "1 игрок" },
        { label: "Сложность", value: "средняя" }
      ],
      description: "Мelee-oriented одиночный сценарий, который расширяет библиотеку в сторону физического ближнего боя и sandbox-механик.",
      highlights: ["ближний бой и физика", "подходит для демонстрации sandbox-сценариев", "расширяет жанровую матрицу"],
      slides: [
        { theme: "cover-melee", label: "Melee", title: "Blade & Sorcery: Nomad" },
        { theme: "cover-arena", label: "Sandbox", title: "Физический бой" },
        { theme: "cover-sandbox", label: "Single-player", title: "Иммерсивный экшен" }
      ]
    },
    GORN: {
      eyebrow: "Одиночная игра",
      meta: ["Single-player", "Arena / Action"],
      specs: [
        { label: "Режимы", value: "аренный одиночный экшен" },
        { label: "Карты", value: "боевые арены" },
        { label: "Формат сессии", value: "короткие зрелищные сессии" },
        { label: "Игроки", value: "1 игрок" },
        { label: "Сложность", value: "легкая" }
      ],
      description: "Гротескный аренный экшен для более легкого и зрелищного одиночного контента внутри библиотеки.",
      highlights: ["зрелищный одиночный сценарий", "простая считываемая механика", "подходит для развлекательного сегмента"],
      slides: [
        { theme: "cover-arena", label: "Arena Action", title: "GORN" },
        { theme: "cover-melee", label: "Single-player", title: "Зрелищный бой" },
        { theme: "cover-party", label: "Развлекательный контент", title: "Легко считывается" }
      ]
    },
    "Sniper Elite VR": {
      eyebrow: "Одиночная игра",
      meta: ["Single-player", "Shooter / Tactical"],
      specs: [
        { label: "Режимы", value: "одиночная tactical-кампания" },
        { label: "Карты", value: "миссии и боевые позиции" },
        { label: "Формат сессии", value: "размеренный shooter-опыт" },
        { label: "Игроки", value: "1 игрок" },
        { label: "Сложность", value: "средняя" }
      ],
      description: "Одиночный tactical shooter-сценарий для более размеренного и прицельного игрового опыта.",
      highlights: ["подходит для tactical-сегмента", "работает как размеренный одиночный опыт", "добавляет библиотеке глубину по жанрам"],
      slides: [
        { theme: "cover-sniper", label: "Tactical Shooter", title: "Sniper Elite VR" },
        { theme: "cover-military", label: "Single-player", title: "Размеренный экшен" },
        { theme: "cover-tactical", label: "Жанровая глубина", title: "Тактический опыт" }
      ]
    },
    "Resident Evil 4": {
      eyebrow: "Одиночная игра",
      meta: ["Single-player", "Horror / Action"],
      specs: [
        { label: "Режимы", value: "сюжетная одиночная кампания" },
        { label: "Карты", value: "главы и horror-локации кампании" },
        { label: "Формат сессии", value: "premium horror-action" },
        { label: "Игроки", value: "1 игрок" },
        { label: "Сложность", value: "сложная" }
      ],
      description: "Известный horror-action сценарий для сильного одиночного премиального опыта и узнаваемой библиотеки.",
      highlights: ["сильная узнаваемая IP", "premium-одиночный horror-контент", "подходит для взрослой аудитории"],
      slides: [
        { theme: "cover-horror", label: "Horror / Action", title: "Resident Evil 4" },
        { theme: "cover-zombie", label: "Single-player", title: "Узнаваемый тайтл" },
        { theme: "cover-walker", label: "Для взрослой аудитории", title: "Иммерсивный horror" }
      ]
    },
    "The Walking Dead: Saints & Sinners": {
      eyebrow: "Одиночная игра",
      meta: ["Single-player", "Horror / Survival"],
      specs: [
        { label: "Режимы", value: "сюжетный survival-horror" },
        { label: "Карты", value: "городские и survival-локации" },
        { label: "Формат сессии", value: "атмосферный single-player" },
        { label: "Игроки", value: "1 игрок" },
        { label: "Сложность", value: "сложная" }
      ],
      description: "Сценарий для взрослой аудитории с акцентом на survival и атмосферу, хорошо работающий в премиальном одиночном сегменте.",
      highlights: ["survival и horror в одном тайтле", "подходит для зрелой аудитории", "усиливает ценность одиночной библиотеки"],
      slides: [
        { theme: "cover-walker", label: "Survival / Horror", title: "Saints & Sinners" },
        { theme: "cover-horror", label: "Single-player", title: "Атмосферный опыт" },
        { theme: "cover-survival", label: "Для взрослой аудитории", title: "Premium-сценарий" }
      ]
    },
    "Cooking Simulator VR": {
      eyebrow: "Одиночная игра",
      meta: ["Single-player", "Simulation"],
      specs: [
        { label: "Режимы", value: "симулятор и task-based сценарии" },
        { label: "Карты", value: "кухонные зоны и уровни симуляции" },
        { label: "Формат сессии", value: "single-player simulation" },
        { label: "Игроки", value: "1 игрок" },
        { label: "Сложность", value: "легкая" }
      ],
      description: "Небоевая симуляция, которая помогает расширить библиотеку за пределы action-контента и работать с более широкой аудиторией.",
      highlights: ["более спокойный формат", "подходит для семейной аудитории", "расширяет библиотеку beyond action"],
      slides: [
        { theme: "cover-sim", label: "Simulation", title: "Cooking Simulator VR" },
        { theme: "cover-clean", label: "Для широкой аудитории", title: "Небоевая механика" },
        { theme: "cover-garage", label: "Single-player", title: "Вариативность библиотеки" }
      ]
    },
    "Marvel's Iron Man VR": {
      eyebrow: "Одиночная игра",
      meta: ["Single-player", "Hero / Action"],
      specs: [
        { label: "Режимы", value: "сюжетная hero-кампания" },
        { label: "Карты", value: "миссии и hero-action локации" },
        { label: "Формат сессии", value: "сильный одиночный wow-опыт" },
        { label: "Игроки", value: "1 игрок" },
        { label: "Сложность", value: "средняя" }
      ],
      description: "Hero-action сценарий с узнаваемой франшизой, который усиливает premium-сегмент библиотеки и одиночный wow-эффект.",
      highlights: ["известный супергеройский бренд", "сильный solo wow-эффект", "подходит для premium-подачи"],
      slides: [
        { theme: "cover-iron", label: "Hero Action", title: "Marvel's Iron Man VR" },
        { theme: "cover-hero", label: "Single-player", title: "Известная франшиза" },
        { theme: "cover-sports", label: "Premium-сценарий", title: "Эмоциональный опыт" }
      ]
    },
    "NFL PRO ERA II": {
      eyebrow: "Одиночная игра",
      meta: ["Single-player", "Sports"],
      specs: [
        { label: "Режимы", value: "спортивные тренировочные и матчевые сценарии" },
        { label: "Карты", value: "стадионы и игровые сцены" },
        { label: "Формат сессии", value: "single-player sports VR" },
        { label: "Игроки", value: "1 игрок" },
        { label: "Сложность", value: "средняя" }
      ],
      description: "Спортивный VR-сценарий, который добавляет библиотеке отдельную категорию контента и расширяет аудиторию площадки.",
      highlights: ["спортивный сегмент библиотеки", "подходит для широкой аудитории", "увеличивает жанровое разнообразие"],
      slides: [
        { theme: "cover-sports", label: "Sports", title: "NFL PRO ERA II" },
        { theme: "cover-hero", label: "Single-player", title: "Спортивный VR" },
        { theme: "cover-motion", label: "Расширение библиотеки", title: "Новый сегмент контента" }
      ]
    },
    "PowerWash Simulator VR": {
      eyebrow: "Одиночная игра",
      meta: ["Single-player", "Simulation / Relax"],
      specs: [
        { label: "Режимы", value: "single-player relax / cleaning simulation" },
        { label: "Карты", value: "разные объекты и бытовые зоны" },
        { label: "Формат сессии", value: "спокойный симулятор" },
        { label: "Игроки", value: "1 игрок" },
        { label: "Сложность", value: "легкая" }
      ],
      description: "Спокойный симулятор для более расслабленного сценария, который хорошо балансирует насыщенную action-библиотеку.",
      highlights: ["relax-сценарий в библиотеке", "работает на более широкой аудитории", "балансирует action-контент"],
      slides: [
        { theme: "cover-clean", label: "Simulation / Relax", title: "PowerWash Simulator VR" },
        { theme: "cover-sim", label: "Single-player", title: "Спокойный сценарий" },
        { theme: "cover-garage", label: "Широкая аудитория", title: "Небоевое VR" }
      ]
    },
    "Car Mechanic Simulator": {
      eyebrow: "Одиночная игра",
      meta: ["Single-player", "Simulation"],
      specs: [
        { label: "Режимы", value: "single-player mechanical simulation" },
        { label: "Карты", value: "гаражные и сервисные сцены" },
        { label: "Формат сессии", value: "спокойный технический контент" },
        { label: "Игроки", value: "1 игрок" },
        { label: "Сложность", value: "легкая" }
      ],
      description: "Технический симулятор, который расширяет библиотеку в сторону прикладного и более спокойного контента.",
      highlights: ["симуляторный сегмент", "отличается от стандартных action-игр", "подходит для расширения аудитории"],
      slides: [
        { theme: "cover-garage", label: "Simulation", title: "Car Mechanic Simulator" },
        { theme: "cover-clean", label: "Single-player", title: "Технический сценарий" },
        { theme: "cover-sim", label: "Для широкой аудитории", title: "Спокойный контент" }
      ]
    },
    "I Am Cat": {
      eyebrow: "Одиночная игра",
      meta: ["Single-player", "Casual / Sandbox"],
      specs: [
        { label: "Основной формат", value: "легкий одиночный sandbox-сценарий с юмористической подачей" },
        { label: "Как проходит сессия", value: "игрок взаимодействует с предметами, исследует окружение и проходит простые задачи" },
        { label: "Контент внутри", value: "неформальная подача, бытовые сцены, физическое взаимодействие и легкий casual-геймплей" },
        { label: "Игроки", value: "1 игрок" },
        { label: "Сложность", value: "легкая" }
      ],
      description: "I Am Cat — легкий казуальный VR-сценарий с юмористическим настроением и простым порогом входа. Такие игры полезны для площадки как небоевая альтернатива шутерам и хоррорам: они расширяют библиотеку в сторону более расслабленного и семейного контента, который можно предлагать аудитории, не ищущей интенсивный action.",
      highlights: ["мягкий вход для широкой аудитории", "небоевая casual-механика", "расширяет библиотеку спокойным контентом"],
      slides: [
        { theme: "cover-party", label: "Casual / Sandbox", title: "I Am Cat" },
        { theme: "cover-clean", label: "Single-player", title: "Легкий вход" },
        { theme: "cover-sim", label: "Широкая аудитория", title: "Юмористичный формат" }
      ]
    },
    "I Am Security": {
      eyebrow: "Одиночная игра",
      meta: ["Single-player", "Casual / Simulation"],
      specs: [
        { label: "Основной формат", value: "одиночный casual-сценарий с ролевой подачей и простыми задачами" },
        { label: "Как проходит сессия", value: "игрок выполняет понятные действия, взаимодействует с персонажами и проходит короткие игровые ситуации" },
        { label: "Контент внутри", value: "юмористические эпизоды, role-play элементы и легкий симуляционный геймплей" },
        { label: "Игроки", value: "1 игрок" },
        { label: "Сложность", value: "легкая" }
      ],
      description: "I Am Security — легкий VR-сценарий с casual- и role-play-подачей, который помогает разнообразить одиночную библиотеку. Для площадки такие игры полезны тем, что дают альтернативу боевым и напряженным тайтлам: они проще воспринимаются, хорошо подходят для широкой аудитории и делают контентную матрицу менее однообразной.",
      highlights: ["простая и понятная ролевая подача", "подходит для широкой аудитории", "усиливает небойовой сегмент библиотеки"],
      slides: [
        { theme: "cover-stealth", label: "Casual / Simulation", title: "I Am Security" },
        { theme: "cover-clean", label: "Single-player", title: "Ролевой сценарий" },
        { theme: "cover-sim", label: "Легкий вход", title: "Для широкой аудитории" }
      ]
    }
  };

  let currentGame = null;
  let currentSlides = [];
  let currentSlide = 0;
  let touchStartY = 0;
  let touchStartX = 0;
  let touchStartScrollTop = 0;
  let touchScrollLocked = false;
  let lockedPageScrollY = 0;

  function getCardImageSlide(card, gameTitle) {
    const image = card ? card.querySelector("img") : null;

    if (!image || !image.getAttribute("src")) {
      return null;
    }

    return {
      type: "image",
      src: image.getAttribute("src"),
      label: "Фото игры",
      title: image.getAttribute("alt") || gameTitle
    };
  }

  function buildSlides(game, card, gameTitle) {
    const baseSlides = Array.isArray(game.slides) ? game.slides.slice() : [];
    const mediaSlides = baseSlides.filter((slide) => slide.type === "video" || slide.type === "image");

    if (mediaSlides.length) {
      return mediaSlides.concat(baseSlides.filter((slide) => slide.type !== "video" && slide.type !== "image"));
    }

    const fallbackImage = getCardImageSlide(card, gameTitle);
    return fallbackImage ? [fallbackImage] : baseSlides;
  }

  function renderSlide() {
    if (!currentGame || !currentSlides.length) {
      stage.innerHTML = "";
      return;
    }

    const slide = currentSlides[currentSlide];
    if (slide.type === "video") {
      stage.innerHTML = `
        <div class="game-modal-slide game-modal-media-slide">
          <video class="game-modal-media" controls playsinline preload="metadata">
            <source src="${slide.src}" type="video/mp4">
          </video>
        </div>
      `;
    } else if (slide.type === "image") {
      stage.innerHTML = `
        <div class="game-modal-slide game-modal-media-slide">
          <img class="game-modal-media" src="${slide.src}" alt="${slide.title}">
        </div>
      `;
    } else {
      stage.innerHTML = `
        <div class="game-modal-slide game-cover ${slide.theme}">
        </div>
      `;
    }

  }

  function resetTouchScrollState() {
    touchStartY = 0;
    touchStartX = 0;
    touchStartScrollTop = 0;
    touchScrollLocked = false;
  }

  function lockPageScroll() {
    lockedPageScrollY = window.scrollY || window.pageYOffset || 0;
    document.body.style.position = "fixed";
    document.body.style.top = `-${lockedPageScrollY}px`;
    document.body.style.left = "0";
    document.body.style.right = "0";
    document.body.style.width = "100%";
    document.body.style.overflow = "hidden";
  }

  function unlockPageScroll() {
    document.body.style.position = "";
    document.body.style.top = "";
    document.body.style.left = "";
    document.body.style.right = "";
    document.body.style.width = "";
    document.body.style.overflow = "";
    window.scrollTo(0, lockedPageScrollY);
  }

  function bindStageTouchScroll() {
    stage.addEventListener("touchstart", (event) => {
      if (!modal.classList.contains("is-open") || !event.touches.length) {
        return;
      }

      const touch = event.touches[0];
      touchStartY = touch.clientY;
      touchStartX = touch.clientX;
      touchStartScrollTop = dialog.scrollTop;
      touchScrollLocked = dialog.scrollHeight > dialog.clientHeight;
    }, { passive: true });

    stage.addEventListener("touchmove", (event) => {
      if (!touchScrollLocked || !event.touches.length) {
        return;
      }

      const touch = event.touches[0];
      const deltaY = touch.clientY - touchStartY;
      const deltaX = touch.clientX - touchStartX;

      if (Math.abs(deltaY) <= Math.abs(deltaX) || Math.abs(deltaY) < 6) {
        return;
      }

      dialog.scrollTop = touchStartScrollTop - deltaY;
      event.preventDefault();
    }, { passive: false });

    stage.addEventListener("touchend", resetTouchScrollState, { passive: true });
    stage.addEventListener("touchcancel", resetTouchScrollState, { passive: true });
  }

  function openGameModal(gameTitle, card) {
    currentGame = gameData[gameTitle];

    if (!currentGame) {
      return;
    }

    currentSlides = buildSlides(currentGame, card, gameTitle);
    currentSlide = 0;
    title.textContent = gameTitle;
    description.textContent = currentGame.description;
    meta.innerHTML = currentGame.meta.map((item) => `<span>${item}</span>`).join("");
    specs.innerHTML = currentGame.specs.map((item) => {
      if (item.label === "Сложность") {
        const levelClass =
          item.value === "легкая"
            ? "difficulty-easy"
            : item.value === "средняя"
              ? "difficulty-medium"
              : "difficulty-hard";

        return `
          <article class="game-modal-spec-item game-modal-spec-item-difficulty">
            <div class="difficulty-inline-row">
              <span>${item.label}</span>
              <strong><span class="difficulty-dot ${levelClass}" title="${item.value}" aria-label="${item.value}"></span></strong>
            </div>
          </article>
        `;
      }

      return `
        <article class="game-modal-spec-item">
          <span>${item.label}</span>
          <strong>${item.value}</strong>
        </article>
      `;
    }).join("");
    renderSlide();
    modal.classList.add("is-open");
    modal.setAttribute("aria-hidden", "false");
    dialog.scrollTop = 0;
    lockPageScroll();
  }

  function closeGameModal() {
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    unlockPageScroll();
    resetTouchScrollState();
  }

  cards.forEach((card) => {
    const titleNode = card.querySelector("h3, strong");
    if (!titleNode) {
      return;
    }

    const gameTitle = titleNode.textContent.trim();
    card.setAttribute("tabindex", "0");
    card.setAttribute("role", "button");
    card.setAttribute("aria-label", `Открыть описание игры ${gameTitle}`);

    const handler = () => openGameModal(gameTitle, card);
    card.addEventListener("click", handler);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        handler();
      }
    });
  });

  prev.addEventListener("click", () => {
    if (!currentGame || !currentSlides.length) {
      return;
    }
    currentSlide = (currentSlide - 1 + currentSlides.length) % currentSlides.length;
    renderSlide();
  });

  next.addEventListener("click", () => {
    if (!currentGame || !currentSlides.length) {
      return;
    }
    currentSlide = (currentSlide + 1) % currentSlides.length;
    renderSlide();
  });

  closeButtons.forEach((button) => button.addEventListener("click", closeGameModal));

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal.classList.contains("is-open")) {
      closeGameModal();
    }
  });

  bindStageTouchScroll();
}

setupCalculator();
setupEconomicsScenario();
function setupFranchiseCompare() {
  const section = document.querySelector(".economics-franchise-section");
  const nextButton = document.getElementById("franchiseNext");
  const name = document.getElementById("franchiseCompetitorName");
  const competitorIndex = document.getElementById("franchiseCompetitorIndex");
  const launchCost = document.getElementById("franchiseLaunchCost");
  const fee = document.getElementById("franchiseFee");
  const royalty = document.getElementById("franchiseRoyalty");
  const subscription = document.getElementById("franchiseSubscription");
  const gamesCount = document.getElementById("franchiseGamesCount");
  const cards = {
    ours: document.querySelector('[data-franchise-card="ours"]'),
    competitor: document.querySelector('[data-franchise-card="competitor"]')
  };
  const mobileTabs = Array.from(document.querySelectorAll("[data-franchise-scroll]"));
  const mobileMedia = window.matchMedia("(max-width: 860px)");

  if (!section || !nextButton || !name || !launchCost || !fee || !royalty || !subscription || !gamesCount) {
    return;
  }

  const competitors = [
    { name: "Another World", launchCost: "1 510 000–4 110 000 ₽", fee: "890 000–990 000 ₽", royalty: "7–9%", subscription: "—", gamesCount: "14" },
    { name: "WARPOINT Арена", launchCost: "2 600 000–4 610 000 ₽", fee: "1 390 000–1 400 000 ₽", royalty: "7%", subscription: "—", gamesCount: "5" },
    { name: "WARPOINT ПО", launchCost: "1 900 000 ₽", fee: "0 ₽", royalty: "0%", subscription: "500 000–800 000 ₽ / 12 мес.", gamesCount: "5" },
    { name: "MetaForce", launchCost: "1 650 000 ₽", fee: "от 850 000 ₽", royalty: "7%", subscription: "0 ₽ / мес.", gamesCount: "3" },
    { name: "MetaForce ПО", launchCost: "1 650 000 ₽", fee: "0–850 000 ₽", royalty: "0%", subscription: "69 000 ₽ / мес.", gamesCount: "3" },
    { name: "AVATAR ARENA", launchCost: "2 500 000–4 500 000 ₽", fee: "0–1 000 000 ₽", royalty: "0%", subscription: "50 000 ₽ / мес.", gamesCount: "37" },
    { name: "AVATAR ARENA ПО", launchCost: "2 500 000–4 500 000 ₽", fee: "0–1 000 000 ₽", royalty: "0%", subscription: "50 000 ₽ / мес.", gamesCount: "37" },
    { name: "WARSTATION", launchCost: "1 500 000–5 000 000 ₽", fee: "0 ₽", royalty: "0%", subscription: "70 000 ₽ / мес.", gamesCount: "5" }
  ];

  let currentIndex = 0;
  let mobileObserver = null;
  let resizeFrame = 0;

  function setActiveMobileTab(target) {
    mobileTabs.forEach((tab) => {
      const isActive = tab.dataset.franchiseScroll === target;
      tab.classList.toggle("is-active", isActive);
      tab.setAttribute("aria-selected", isActive ? "true" : "false");
    });
  }

  function syncCompareHeights() {
    const syncGroups = {};
    const syncNodes = Array.from(section.querySelectorAll("[data-compare-sync]"));

    syncNodes.forEach((node) => {
      node.style.minHeight = "";
      const key = node.dataset.compareSync;
      if (!syncGroups[key]) {
        syncGroups[key] = [];
      }
      syncGroups[key].push(node);
    });

    if (mobileMedia.matches) {
      return;
    }

    Object.values(syncGroups).forEach((group) => {
      const maxHeight = group.reduce((height, node) => Math.max(height, node.offsetHeight), 0);
      group.forEach((node) => {
        node.style.minHeight = `${maxHeight}px`;
      });
    });
  }

  function connectMobileObserver() {
    if (mobileObserver) {
      mobileObserver.disconnect();
      mobileObserver = null;
    }

    if (!mobileMedia.matches || !cards.ours || !cards.competitor || !mobileTabs.length) {
      return;
    }

    mobileObserver = new IntersectionObserver((entries) => {
      const visibleEntry = entries
        .filter((entry) => entry.isIntersecting)
        .sort((left, right) => right.intersectionRatio - left.intersectionRatio)[0];

      if (!visibleEntry) {
        return;
      }

      setActiveMobileTab(visibleEntry.target.dataset.franchiseCard);
    }, { rootMargin: "-18% 0px -52% 0px", threshold: [0.3, 0.55, 0.8] });

    Object.values(cards).forEach((card) => {
      if (card) {
        mobileObserver.observe(card);
      }
    });
  }

  function handleResize() {
    window.cancelAnimationFrame(resizeFrame);
    resizeFrame = window.requestAnimationFrame(() => {
      syncCompareHeights();
      connectMobileObserver();
    });
  }

  function renderCompetitor() {
    const current = competitors[currentIndex];
    name.textContent = current.name;
    launchCost.textContent = current.launchCost;
    fee.textContent = current.fee;
    royalty.textContent = current.royalty;
    subscription.textContent = current.subscription;
    gamesCount.textContent = current.gamesCount;

    if (competitorIndex) {
      competitorIndex.textContent = `${currentIndex + 1} / ${competitors.length}`;
    }

    syncCompareHeights();
  }

  nextButton.addEventListener("click", () => {
    currentIndex = (currentIndex + 1) % competitors.length;
    renderCompetitor();
  });

  mobileTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const targetKey = tab.dataset.franchiseScroll;
      const targetCard = cards[targetKey];

      setActiveMobileTab(targetKey);
      if (targetCard) {
        targetCard.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  });

  window.addEventListener("resize", handleResize);
  window.addEventListener("load", handleResize);
  if (typeof mobileMedia.addEventListener === "function") {
    mobileMedia.addEventListener("change", handleResize);
  } else if (typeof mobileMedia.addListener === "function") {
    mobileMedia.addListener(handleResize);
  }

  setActiveMobileTab("ours");
  renderCompetitor();
  connectMobileObserver();
}

setupReveal();
setupSolutionMode();
setupFrictionScenario();
setupForm();
setupGameModal();
setupFranchiseCompare();







