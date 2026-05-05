const pageRoot = document.getElementById("compact-vr-v3-page");
const rootQuery = (selector) => (pageRoot ? pageRoot.querySelector(selector) : null);
const rootQueryAll = (selector) => (pageRoot ? [...pageRoot.querySelectorAll(selector)] : []);
const scrollLinks = rootQueryAll("[data-cvr-scroll]");
const navLinks = rootQueryAll("[data-cvr-nav-item]");
const revealItems = rootQueryAll(".section-heading, .section-copy, .panel, .metric-chip");
const stickyRail = rootQuery(".sticky-rail");

revealItems.forEach((item) => {
  item.dataset.reveal = "";
});

const revealObserver = new IntersectionObserver((entries, observer) => {
  entries.forEach((entry) => {
    if (!entry.isIntersecting) {
      return;
    }

    entry.target.classList.add("is-visible");
    observer.unobserve(entry.target);
  });
}, { threshold: 0.12 });

revealItems.forEach((item) => revealObserver.observe(item));

const sectionLinks = navLinks.filter((link) => {
  const href = link.getAttribute("href") || "";
  return href.startsWith("#") && href.length > 1;
});

const sections = sectionLinks
  .map((link) => rootQuery(link.getAttribute("href")))
  .filter(Boolean);
let sectionOffsetFrame = 0;

function getHeaderCandidates() {
  return [
    document.querySelector("header"),
    document.querySelector("#mobile-header-slot .mobile-header"),
    document.getElementById("sticky-header"),
    document.getElementById("header-main-row"),
  ].filter(Boolean);
}

function updateSectionScrollOffsets() {
  if (!sections.length) {
    return 96;
  }

  const candidates = getHeaderCandidates();

  const headerBottom = candidates.reduce((maxBottom, element) => {
    if (!element) {
      return maxBottom;
    }

    const rect = element.getBoundingClientRect();
    const style = window.getComputedStyle(element);
    if (style.display === "none" || style.visibility === "hidden" || rect.height <= 0) {
      return maxBottom;
    }

    return Math.max(maxBottom, rect.bottom);
  }, 0);

  const railOffset = Math.max(Math.round(headerBottom + 18), 18);
  if (pageRoot && stickyRail) {
    pageRoot.style.setProperty("--cvr-sticky-rail-top", `${railOffset}px`);
  }

  const offset = Math.max(Math.round(headerBottom + 24), 96);
  sections.forEach((section) => {
    section.style.scrollMarginTop = `${offset}px`;
  });
  return offset;
}

function scrollToHash(hash, smooth = true) {
  if (!hash || !hash.startsWith("#")) {
    return;
  }

  const target = rootQuery(hash);
  if (!target) {
    return;
  }

  updateSectionScrollOffsets();
  target.scrollIntoView({
    behavior: smooth ? "smooth" : "auto",
    block: "start",
  });

  if (window.location.hash !== hash) {
    history.replaceState(null, "", hash);
  }
}

function scheduleSectionOffsetSync(delay = 0) {
  if (delay > 0) {
    window.setTimeout(() => {
      scheduleSectionOffsetSync();
    }, delay);
    return;
  }

  if (sectionOffsetFrame) {
    return;
  }

  sectionOffsetFrame = window.requestAnimationFrame(() => {
    sectionOffsetFrame = 0;
    updateSectionScrollOffsets();
  });
}

function setupHeaderStateObservers() {
  const candidates = getHeaderCandidates();
  if (!candidates.length) {
    return;
  }

  if (typeof MutationObserver === "function") {
    const mutationObserver = new MutationObserver(() => {
      scheduleSectionOffsetSync();
    });

    candidates.forEach((element) => {
      mutationObserver.observe(element, {
        attributes: true,
        attributeFilter: ["class", "style"],
      });
    });
  }

  if (typeof ResizeObserver === "function") {
    const resizeObserver = new ResizeObserver(() => {
      scheduleSectionOffsetSync();
    });

    candidates.forEach((element) => {
      resizeObserver.observe(element);
    });
  }

  if (typeof IntersectionObserver === "function") {
    const visibilityObserver = new IntersectionObserver(() => {
      scheduleSectionOffsetSync();
    }, {
      threshold: [0, 1],
    });

    candidates.forEach((element) => {
      visibilityObserver.observe(element);
    });
  }
}

const navObserver = new IntersectionObserver((entries) => {
  const visibleEntry = entries
    .filter((entry) => entry.isIntersecting)
    .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];

  if (!visibleEntry) {
    return;
  }

  sectionLinks.forEach((link) => {
    const isActive = link.getAttribute("href") === `#${visibleEntry.target.id}`;
    link.classList.toggle("is-active", isActive);
  });
}, {
  threshold: 0.3,
  rootMargin: "-20% 0px -55% 0px"
});

sections.forEach((section) => navObserver.observe(section));

scrollLinks.forEach((link) => {
  link.addEventListener("click", (event) => {
    const href = link.getAttribute("href") || "";
    if (!href.startsWith("#")) {
      return;
    }
    event.preventDefault();
    scrollToHash(href);
  });
});

window.addEventListener("resize", () => {
  scheduleSectionOffsetSync();
});

window.addEventListener("layout-scroll-threshold", () => {
  scheduleSectionOffsetSync();
});

window.addEventListener("header-expand", () => {
  scheduleSectionOffsetSync();
});

window.addEventListener("load", () => {
  updateSectionScrollOffsets();
  if (window.location.hash) {
    scrollToHash(window.location.hash, false);
  }

  // The site header can switch between several states after first paint.
  scheduleSectionOffsetSync();
  scheduleSectionOffsetSync(120);
  scheduleSectionOffsetSync(360);
});

setupHeaderStateObservers();

function setupGameModal() {
  const cards = rootQueryAll(".game-card, .single-game-card");
  const modal = rootQuery("#gameModal");
  const stage = rootQuery("#gameModalStage");
  const title = rootQuery("#gameModalTitle");
  const meta = rootQuery("#gameModalMeta");
  const description = rootQuery("#gameModalDescription");
  const specs = rootQuery("#gameModalSpecs");
  const prev = rootQuery("#gameModalPrev");
  const next = rootQuery("#gameModalNext");
  const closeButtons = rootQueryAll("[data-close-modal]");

  if (!cards.length || !modal || !stage || !title || !meta || !description || !specs || !prev || !next) {
    return;
  }

  let currentIndex = 0;

  function buildStage(card) {
    const image = card.querySelector(".game-cover-image img");
    const cover = card.querySelector(".game-cover");

    if (image) {
      return `
        <div class="game-modal-slide game-modal-media-slide">
          <img class="game-modal-media" src="${image.getAttribute("src")}" alt="${image.getAttribute("alt") || ""}">
        </div>
      `;
    }

    return cover ? `<div class="game-modal-slide">${cover.outerHTML}</div>` : '<div class="game-modal-slide"></div>';
  }

  function buildMeta(card) {
    const tags = [...card.querySelectorAll(".game-meta span")].map((item) => item.textContent.trim());
    const badge = card.querySelector(".game-badge");
    if (badge) {
      tags.unshift(badge.textContent.trim());
    }
    return tags.length ? tags.map((item) => `<span>${item}</span>`).join("") : "<span>Контентный блок</span>";
  }

  function buildSpecs(card) {
    const badge = card.querySelector(".game-badge")?.textContent.trim();
    const metaTags = [...card.querySelectorAll(".game-meta span")].map((item) => item.textContent.trim());
    const coverLabel = card.querySelector(".card-kicker")?.textContent.trim();
    const isSingle = card.classList.contains("single-game-card");
    const items = [];

    if (coverLabel) {
      items.push({ label: "Категория", value: coverLabel });
    }
    if (badge) {
      items.push({ label: "Формат", value: badge });
    }
    if (metaTags.length) {
      items.push({ label: "Теги", value: metaTags.join(" / ") });
    }
    if (isSingle) {
      items.push({ label: "Режим", value: "Одиночный сценарий" });
      items.push({ label: "Блок", value: "Расширение контентной матрицы" });
    }

    if (!items.length) {
      items.push({ label: "Блок", value: "Контентная библиотека" });
    }

    return items.map((item) => `
      <article class="game-modal-spec-item">
        <span>${item.label}</span>
        <strong>${item.value}</strong>
      </article>
    `).join("");
  }

  function renderCard(index) {
    const card = cards[index];
    const titleNode = card.querySelector("h3, strong");
    const textNode = card.querySelector("p");
    const isSingle = card.classList.contains("single-game-card");

    currentIndex = index;
    title.textContent = titleNode ? titleNode.textContent.trim() : "Игра";
    meta.innerHTML = buildMeta(card);
    description.textContent = textNode
      ? textNode.textContent.trim()
      : isSingle
        ? "Игра из библиотеки одиночных сценариев для расширения контентной матрицы площадки."
        : "Игра из контентной библиотеки площадки.";
    specs.innerHTML = buildSpecs(card);
    stage.innerHTML = buildStage(card);
  }

  function openModal(index) {
    renderCard(index);
    modal.classList.add("is-open");
    modal.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
  }

  function closeModal() {
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
  }

  cards.forEach((card, index) => {
    const titleNode = card.querySelector("h3, strong");
    if (!titleNode) {
      return;
    }

    card.setAttribute("tabindex", "0");
    card.setAttribute("role", "button");
    card.setAttribute("aria-label", `Открыть описание игры ${titleNode.textContent.trim()}`);

    card.addEventListener("click", () => openModal(index));
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openModal(index);
      }
    });
  });

  prev.addEventListener("click", () => openModal((currentIndex - 1 + cards.length) % cards.length));
  next.addEventListener("click", () => openModal((currentIndex + 1) % cards.length));
  closeButtons.forEach((button) => button.addEventListener("click", closeModal));

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal.classList.contains("is-open")) {
      closeModal();
    }
  });
}

function setupMonthlyEconomics() {
  const citySelect = document.getElementById("monthlyCity");
  const typeSelect = document.getElementById("monthlyType");

  if (!citySelect || !typeSelect) {
    return;
  }

  const salaryMin = 65000;
  const salaryMax = 70000;
  const internet = 4000;
  const supplies = 8000;
  const marketingMin = 25210;
  const marketingMax = 50000;
  const fixedOpsMin = internet + supplies + marketingMin;
  const fixedOpsMax = internet + supplies + marketingMax;
  const baseTechCost = 1854964;
  const revenues = [250000, 500000, 750000, 1000000];
  const data = {
    office: {
      moscow: { compactRent: "70 000–130 000 ₽ / мес", compactStart: "512 000–1 190 000 ₽" },
      ekb: { compactRent: "62 000–81 000 ₽ / мес", compactStart: "403 000–657 000 ₽" },
      astrakhan: { compactRent: "43 000–62 000 ₽ / мес", compactStart: "273 000–496 000 ₽" },
      nizhnevartovsk: { compactRent: "40 000–56 000 ₽ / мес", compactStart: "267 000–515 000 ₽" }
    },
    retail: {
      moscow: { compactRent: "186 000–620 000 ₽ / мес", compactStart: "744 000–2 170 000 ₽" },
      ekb: { compactRent: "74 000–143 000 ₽ / мес", compactStart: "428 000–781 000 ₽" },
      astrakhan: { compactRent: "43 000–74 000 ₽ / мес", compactStart: "273 000–521 000 ₽" },
      nizhnevartovsk: { compactRent: "43 000–90 000 ₽ / мес", compactStart: "273 000–583 000 ₽" }
    },
    mall: {
      moscow: { compactRent: "516 000–930 000 ₽ / мес", compactStart: "1 404 000–2 790 000 ₽" },
      ekb: { compactRent: "112 000–186 000 ₽ / мес", compactStart: "502 000–868 000 ₽" },
      astrakhan: { compactRent: "50 000–87 000 ₽ / мес", compactStart: "285 000–546 000 ₽" },
      nizhnevartovsk: { compactRent: "43 000–74 000 ₽ / мес", compactStart: "273 000–552 000 ₽" }
    }
  };

  const fields = {
    rent: document.getElementById("monthlyRentRange"),
    total: document.getElementById("monthlyTotalRange"),
    structureRent: document.getElementById("monthlyStructureRent"),
    paybackProfit250: document.getElementById("paybackProfit250"),
    paybackMonths250: document.getElementById("paybackMonths250"),
    paybackProfit500: document.getElementById("paybackProfit500"),
    paybackMonths500: document.getElementById("paybackMonths500"),
    paybackProfit750: document.getElementById("paybackProfit750"),
    paybackMonths750: document.getElementById("paybackMonths750"),
    paybackProfit1000: document.getElementById("paybackProfit1000"),
    paybackMonths1000: document.getElementById("paybackMonths1000"),
    paybackLaunchCost: document.getElementById("paybackLaunchCost")
  };

  const rubFormatter = new Intl.NumberFormat("ru-RU");
  const monthFormatter = new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1
  });

  function parseRange(rangeText) {
    const matches = [...rangeText.matchAll(/\d[\d ]*/g)].map((match) => Number(match[0].replace(/\s/g, "")));
    return [matches[0], matches[1]];
  }

  function formatRange(min, max, suffix = "") {
    return `${rubFormatter.format(min)}–${rubFormatter.format(max)} ₽${suffix}`;
  }

  function updateMonthlyEconomics() {
    const scenario = data[typeSelect.value][citySelect.value];
    const [rentMin, rentMax] = parseRange(scenario.compactRent);
    const [startMin, startMax] = parseRange(scenario.compactStart);
    const monthlyMin = rentMin + salaryMin + fixedOpsMin;
    const monthlyMax = rentMax + salaryMax + fixedOpsMax;
    const launchMin = baseTechCost + startMin;
    const launchMax = baseTechCost + startMax;

    if (fields.rent) {
      fields.rent.textContent = scenario.compactRent;
    }

    if (fields.total) {
      fields.total.textContent = formatRange(monthlyMin, monthlyMax, " / мес");
    }

    if (fields.structureRent) {
      fields.structureRent.textContent = scenario.compactRent;
    }

    if (fields.paybackLaunchCost) {
      fields.paybackLaunchCost.textContent = `Окупаемость точки считается от полной себестоимости запуска: ${formatRange(launchMin, launchMax)}`;
    }

    revenues.forEach((revenue) => {
      const key = revenue / 1000;
      const profitMin = Math.max(revenue - monthlyMax, 0);
      const profitMax = Math.max(revenue - monthlyMin, 0);
      const profitField = fields[`paybackProfit${key}`];
      const monthsField = fields[`paybackMonths${key}`];

      if (!profitField || !monthsField) {
        return;
      }

      profitField.textContent = formatRange(profitMin, profitMax, " / мес");

      if (profitMin <= 0) {
        monthsField.textContent = "Операционная прибыль: при таком обороте точка не покрывает ежемесячные расходы";
        return;
      }

      const monthsMin = launchMin / profitMax;
      const monthsMax = launchMax / profitMin;
      monthsField.textContent = `Операционная прибыль: окупаемость полной точки ≈ ${monthFormatter.format(monthsMin)}–${monthFormatter.format(monthsMax)} месяца`;
    });
  }

  citySelect.addEventListener("change", updateMonthlyEconomics);
  typeSelect.addEventListener("change", updateMonthlyEconomics);
  updateMonthlyEconomics();
}

function setupFranchiseCompare() {
  const nextButton = document.getElementById("franchiseNext");
  const name = document.getElementById("franchiseCompetitorName");
  const launchCost = document.getElementById("franchiseLaunchCost");
  const fee = document.getElementById("franchiseFee");
  const royalty = document.getElementById("franchiseRoyalty");
  const gamesCount = document.getElementById("franchiseGamesCount");
  const caseProviderTitle = document.getElementById("caseProviderTitle");
  const caseProviderNext = document.getElementById("caseProviderNext");
  const franchiseCaseTabs = document.getElementById("franchiseCaseTabs");
  const caseTabs = rootQueryAll(".franchise-case-tab");
  const caseCity = document.getElementById("caseCity");
  const casePopulation = document.getElementById("casePopulation");
  const casePrimaryBrand = document.getElementById("casePrimaryBrand");
  const normalizedCaseBrand = document.getElementById("normalizedCaseBrand");
  const normalizedCaseRow = document.getElementById("normalizedCaseRow");
  const caseTicket = document.getElementById("caseTicket");
  const caseHelmets = document.getElementById("caseHelmets");
  const caseMarginPercent = document.getElementById("caseMarginPercent");
  const aw10Ticket = document.getElementById("aw10Ticket");
  const aw10Helmets = document.getElementById("aw10Helmets");
  const aw10MarginPercent = document.getElementById("aw10MarginPercent");
  const aw10CaseChart = document.getElementById("aw10CaseChart");
  const bizoneTicket = document.getElementById("bizoneTicket");
  const bizoneHelmets = document.getElementById("bizoneHelmets");
  const bizoneMarginPercent = document.getElementById("bizoneMarginPercent");
  const bizoneEfficiencyDelta = document.getElementById("bizoneEfficiencyDelta");
  const caseChart = document.getElementById("franchiseCaseChart");
  const bizoneCaseChart = document.getElementById("bizoneCaseChart");

  if (!nextButton || !name || !launchCost || !fee || !royalty || !gamesCount) {
    return;
  }

  const competitors = [
    { name: "Another World", launchCost: "от 2 500 000 – 5 000 000 млн+ ₽", fee: "от 890 000 ₽ (проверить)", royalty: "7-9% (проверить)", subscription: "нет", gamesCount: "~15 собственных игр / до 350+ в каталоге" },
    { name: "WARPOINT", launchCost: "от 2 610 000 ₽", fee: "от 1 390 000 ₽", royalty: "7% с выручки (с 5-го месяца)", subscription: "от ~50 000 ₽/мес (модель подписки)", gamesCount: "ограничено (основная собственная PvP-игра + контент сети)" },
    { name: "MetaForce", launchCost: "от 2 000 000 ₽", fee: "890 000 - 1 890 000 ₽", royalty: "7% с выручки (с 5-го месяца) от 40 000", subscription: "от ~50 000 ₽/мес (модель подписки)", gamesCount: "6" }
  ];

  const competitorCases = {
    krasnogorsk: {
      city: "Красногорск",
      population: "189 000",
      ticket: "1 000 ₽ / человек",
      helmets: "20",
      photoOne: "Игровое пространство",
      photoTwo: "Игроки в сессии",
      months: ["01.2024", "02.2024", "03.2024", "04.2024", "05.2024", "06.2024"],
      revenue: [800000, 1200000, 1300000, 1400000, 1250000, 1150000],
      profit: [370000, 550000, 500000, 350000, 510000, 480000]
    },
    kazan: {
      city: "Казань",
      population: "1 300 000",
      ticket: "1 300 ₽ / человек",
      helmets: "15",
      photoOne: "Брендированная зона",
      photoTwo: "Командная игра",
      months: ["01.2024", "02.2024", "03.2024", "04.2024", "05.2024", "06.2024"],
      revenue: [1200000, 1300000, 1600000, 1700000, 1400000, 1300000],
      profit: [600000, 600000, 670000, 800000, 670000, 550000]
    },
    irkutsk: {
      city: "Иркутск",
      population: "611 000",
      ticket: "1 000 ₽ / человек",
      helmets: "14",
      photoOne: "Комплект шлемов",
      photoTwo: "Детский визит",
      months: ["01.2024", "02.2024", "03.2024", "04.2024", "05.2024", "06.2024"],
      revenue: [800000, 1200000, 1300000, 1400000, 1250000, 1150000],
      profit: [370000, 550000, 500000, 350000, 510000, 480000]
    }
  };

  const caseProviders = [
    {
      name: "Another World",
      title: "Another World",
      cases: competitorCases,
      order: ["krasnogorsk", "kazan", "irkutsk"],
      normalizeToTen: true
    },
    {
      name: "MetaForce",
      title: "MetaForce",
      cases: {
        ekaterinburg: {
          city: "Екатеринбург",
          population: "1 539 000",
          ticket: "1 200 ₽ / человек",
          helmets: "10",
          months: ["03.2024", "04.2024", "05.2024", "06.2024", "07.2024", "08.2024", "09.2024", "10.2024", "11.2024", "12.2024"],
          revenue: [524150, 799410, 811410, 830950, 1083780, 971910, 765160, 787750, 873155, 1006175],
          profit: [168436, 379223, 384459, 408644, 650098, 540311, 336446, 355254, 430814, 546542]
        }
      },
      order: ["ekaterinburg"],
      normalizeToTen: false
    }
  ];

  const bizoneModelCosts = {
    rent: 80000,
    teamFixed: 40000,
    teamFixedHigh: 60000,
    teamRate: 0.05,
    marketingRate: 0.05,
    royaltyRate: 0.06,
    ops: 12000,
    taxRate: 0.15
  };

  let currentIndex = 0;
  let currentCaseProviderIndex = 0;
  let currentCaseKey = "krasnogorsk";

  function renderCompetitor() {
    const current = competitors[currentIndex];
    name.textContent = current.name;
    launchCost.textContent = current.launchCost;
    fee.textContent = current.fee;
    royalty.textContent = current.royalty;
    gamesCount.textContent = current.gamesCount;
  }

  function formatShortMoney(value) {
    if (value >= 1000000) {
      const short = value / 1000000;
      return `${Number.isInteger(short) ? short : short.toFixed(2).replace(/0$/, "")} млн`;
    }

    return `${Math.round(value / 1000)} тыс`;
  }

  function formatPercent(value) {
    return `${value.toFixed(1).replace(".", ",")}%`;
  }

  function parseRubNumber(text) {
    const match = text.match(/\d[\d ]*/);
    return match ? Number(match[0].replace(/\s/g, "")) : 0;
  }

  function getActiveMarketingRate() {
    const activeButton = rootQuery("[data-marketing-rate].is-active");
    return activeButton ? Number(activeButton.dataset.marketingRate) : bizoneModelCosts.marketingRate;
  }

  function getBizoneTeamFixed(revenue) {
    return revenue === 1000000 ? bizoneModelCosts.teamFixedHigh : bizoneModelCosts.teamFixed;
  }

  function calculateBizoneExpenseAtModelPoint(revenue) {
    const marketingRate = getActiveMarketingRate();
    const teamCost = getBizoneTeamFixed(revenue) + (revenue * bizoneModelCosts.teamRate);
    const marketingCost = revenue * marketingRate;
    const royaltyCost = revenue * bizoneModelCosts.royaltyRate;
    const profitBeforeTax = revenue - bizoneModelCosts.rent - teamCost - marketingCost - royaltyCost - bizoneModelCosts.ops;
    const tax = profitBeforeTax > 0 ? profitBeforeTax * bizoneModelCosts.taxRate : 0;

    return bizoneModelCosts.rent + teamCost + marketingCost + royaltyCost + bizoneModelCosts.ops + tax;
  }

  function interpolateBizoneExpenses(revenue) {
    const points = [400000, 600000, 800000, 1000000].map((pointRevenue) => ({
      revenue: pointRevenue,
      expense: calculateBizoneExpenseAtModelPoint(pointRevenue)
    }));

    if (revenue <= points[0].revenue) {
      const start = points[0];
      const end = points[1];
      const ratio = (revenue - start.revenue) / (end.revenue - start.revenue);
      return start.expense + ((end.expense - start.expense) * ratio);
    }

    if (revenue >= points[points.length - 1].revenue) {
      const start = points[points.length - 2];
      const end = points[points.length - 1];
      const ratio = (revenue - start.revenue) / (end.revenue - start.revenue);
      return start.expense + ((end.expense - start.expense) * ratio);
    }

    for (let index = 0; index < points.length - 1; index += 1) {
      const start = points[index];
      const end = points[index + 1];

      if (revenue >= start.revenue && revenue <= end.revenue) {
        const ratio = (revenue - start.revenue) / (end.revenue - start.revenue);
        return start.expense + ((end.expense - start.expense) * ratio);
      }
    }

    return points[points.length - 1].expense;
  }

  function calculateBizoneNetProfit(revenue) {
    const totalExpense = interpolateBizoneExpenses(revenue);
    const netProfit = revenue - totalExpense;

    if (netProfit <= 0) {
      return 0;
    }

    return Math.round(netProfit);
  }

  function renderCaseTabs(provider) {
    if (!franchiseCaseTabs) {
      return;
    }

    franchiseCaseTabs.innerHTML = provider.order.map((caseKey, index) => {
      const current = provider.cases[caseKey];
      return `<button class="franchise-case-tab${index === 0 ? " is-active" : ""}" type="button" data-case="${caseKey}">${current.city}</button>`;
    }).join("");
  }

  function renderCase(caseKey) {
    if (!caseCity || !casePopulation || !caseTicket || !caseHelmets || !caseMarginPercent || !aw10Ticket || !aw10Helmets || !aw10MarginPercent || !aw10CaseChart || !bizoneTicket || !bizoneHelmets || !bizoneMarginPercent || !bizoneEfficiencyDelta || !caseChart || !bizoneCaseChart) {
      return;
    }

    const provider = caseProviders[currentCaseProviderIndex];
    const current = provider.cases[caseKey];
    if (!current) {
      return;
    }

    rootQueryAll(".franchise-case-tab").forEach((tab) => {
      tab.classList.toggle("is-active", tab.dataset.case === caseKey);
    });

    if (caseProviderTitle) {
      caseProviderTitle.textContent = provider.title;
    }
    caseCity.textContent = current.city;
    casePopulation.textContent = current.population;
    if (casePrimaryBrand) {
      casePrimaryBrand.textContent = provider.name;
    }
    caseTicket.textContent = current.ticket;
    caseHelmets.textContent = current.helmets;
    const averageMargin = current.revenue.reduce((total, revenueValue, index) => {
      const profitValue = current.profit[index];
      return total + ((profitValue / revenueValue) * 100);
    }, 0) / current.revenue.length;
    caseMarginPercent.textContent = formatPercent(averageMargin);

    const currentHelmets = Number(current.helmets);
    const aw10Factor = currentHelmets > 0 ? 10 / currentHelmets : 1;
    const aw10Revenues = current.revenue.map((revenueValue) => Math.round(revenueValue * aw10Factor));
    const aw10Profits = current.profit.map((profitValue) => Math.round(profitValue * aw10Factor));
    const aw10AverageMargin = aw10Revenues.reduce((total, revenueValue, index) => {
      return total + ((aw10Profits[index] / revenueValue) * 100);
    }, 0) / aw10Revenues.length;

    if (normalizedCaseBrand) {
      normalizedCaseBrand.textContent = provider.name;
    }
    aw10Ticket.textContent = current.ticket;
    aw10Helmets.textContent = "10";
    aw10MarginPercent.textContent = formatPercent(aw10AverageMargin);

    const competitorTicket = parseRubNumber(current.ticket);
    const bizoneTicketValue = competitorTicket;
    const baseForBizone = provider.normalizeToTen ? aw10Revenues : current.revenue;
    const baseMarginForEfficiency = provider.normalizeToTen ? aw10AverageMargin : averageMargin;
    const bizoneRevenues = baseForBizone.map((revenueValue) => {
      return Math.round(revenueValue * (bizoneTicketValue / competitorTicket));
    });
    const bizoneProfits = bizoneRevenues.map((revenueValue) => calculateBizoneNetProfit(revenueValue));
    const bizoneAverageMargin = bizoneRevenues.reduce((total, revenueValue, index) => {
      return total + ((bizoneProfits[index] / revenueValue) * 100);
    }, 0) / bizoneRevenues.length;

    bizoneTicket.textContent = current.ticket;
    bizoneHelmets.textContent = "10";
    bizoneMarginPercent.textContent = formatPercent(bizoneAverageMargin);
    const efficiencyDelta = ((bizoneAverageMargin - baseMarginForEfficiency) / baseMarginForEfficiency) * 100;
    bizoneEfficiencyDelta.textContent = formatPercent(efficiencyDelta);

    const maxValue = Math.max(...current.revenue);
    caseChart.innerHTML = current.months.map((month, index) => {
      const revenue = current.revenue[index];
      const profit = current.profit[index];
      const revenueHeight = Math.max((revenue / maxValue) * 220, 36);
      const profitHeight = Math.max((profit / maxValue) * 220, 28);

      return `
        <div class="franchise-bar-group">
          <div class="franchise-bars">
            <div class="franchise-bar revenue combined" style="height:${revenueHeight}px">
              <span class="franchise-bar-value revenue-value">${formatShortMoney(revenue)}</span>
              <span class="franchise-bar-profit-mark" style="height:${profitHeight}px"></span>
              <span class="franchise-bar-value profit-value">${formatShortMoney(profit)}</span>
            </div>
          </div>
          <span class="franchise-bar-label">${month}</span>
        </div>
      `;
    }).join("");

    if (provider.normalizeToTen) {
      if (normalizedCaseRow) {
        normalizedCaseRow.hidden = false;
        normalizedCaseRow.style.display = "";
      }
      const aw10MaxValue = Math.max(...aw10Revenues);
      aw10CaseChart.innerHTML = current.months.map((month, index) => {
        const revenue = aw10Revenues[index];
        const profit = aw10Profits[index];
        const revenueHeight = Math.max((revenue / aw10MaxValue) * 220, 36);
        const profitHeight = Math.max((profit / aw10MaxValue) * 220, 28);

        return `
          <div class="franchise-bar-group">
            <div class="franchise-bars">
              <div class="franchise-bar revenue combined" style="height:${revenueHeight}px">
                <span class="franchise-bar-value revenue-value">${formatShortMoney(revenue)}</span>
                <span class="franchise-bar-profit-mark" style="height:${profitHeight}px"></span>
                <span class="franchise-bar-value profit-value">${formatShortMoney(profit)}</span>
              </div>
            </div>
            <span class="franchise-bar-label">${month}</span>
          </div>
        `;
      }).join("");
    } else {
      if (normalizedCaseRow) {
        normalizedCaseRow.hidden = true;
        normalizedCaseRow.style.display = "none";
      }
      aw10CaseChart.innerHTML = "";
    }

    const bizoneMaxValue = Math.max(...bizoneRevenues);
    bizoneCaseChart.innerHTML = current.months.map((month, index) => {
      const revenue = bizoneRevenues[index];
      const profit = bizoneProfits[index];
      const revenueHeight = Math.max((revenue / bizoneMaxValue) * 220, 36);
      const profitHeight = Math.max((profit / bizoneMaxValue) * 220, 28);

      return `
        <div class="franchise-bar-group">
          <div class="franchise-bars">
            <div class="franchise-bar revenue combined" style="height:${revenueHeight}px">
              <span class="franchise-bar-value revenue-value">${formatShortMoney(revenue)}</span>
              <span class="franchise-bar-profit-mark" style="height:${profitHeight}px"></span>
              <span class="franchise-bar-value profit-value">${formatShortMoney(profit)}</span>
            </div>
          </div>
          <span class="franchise-bar-label">${month}</span>
        </div>
      `;
    }).join("");
  }

  nextButton.addEventListener("click", () => {
    currentIndex = (currentIndex + 1) % competitors.length;
    renderCompetitor();
  });

  if (franchiseCaseTabs) {
    franchiseCaseTabs.addEventListener("click", (event) => {
      const tab = event.target.closest(".franchise-case-tab");
      if (!tab) {
        return;
      }
      currentCaseKey = tab.dataset.case;
      renderCase(currentCaseKey);
    });
  }

  if (caseProviderNext) {
    caseProviderNext.addEventListener("click", () => {
      currentCaseProviderIndex = (currentCaseProviderIndex + 1) % caseProviders.length;
      const provider = caseProviders[currentCaseProviderIndex];
      renderCaseTabs(provider);
      currentCaseKey = provider.order[0];
      renderCase(currentCaseKey);
    });
  }

  rootQueryAll("[data-marketing-rate]").forEach((button) => {
    button.addEventListener("click", () => {
      requestAnimationFrame(() => {
        renderCase(currentCaseKey);
      });
    });
  });

  renderCompetitor();
  renderCaseTabs(caseProviders[currentCaseProviderIndex]);
  renderCase(currentCaseKey);
}

function setupFranchiseFormats() {
  const nextButton = document.getElementById("franchiseFormatNext");
  const index = document.getElementById("franchiseFormatIndex");
  const kicker = document.getElementById("franchiseFormatKicker");
  const title = document.getElementById("franchiseFormatTitle");
  const text = document.getElementById("franchiseFormatText");
  const scale = document.getElementById("franchiseFormatScale");
  const income = document.getElementById("franchiseFormatIncome");
  const payback = document.getElementById("franchiseFormatPayback");
  const royalty = document.getElementById("franchiseFormatRoyalty");
  const bullets = document.getElementById("franchiseFormatBullets");
  const caption = document.getElementById("franchiseFormatCaption");
  const zoneLeft = document.getElementById("franchiseZoneLeft");
  const zoneCenter = document.getElementById("franchiseZoneCenter");
  const zoneRight = document.getElementById("franchiseZoneRight");
  const map = document.getElementById("franchiseFormatMap");
  const incomeTitle = document.getElementById("franchiseIncomeTitle");
  const incomeText = document.getElementById("franchiseIncomeText");
  const incomeList = document.getElementById("franchiseIncomeList");
  const gamesMargin = document.getElementById("franchiseGamesMargin");
  const softwareMargin = document.getElementById("franchiseSoftwareMargin");
  const equipmentTurnover = document.getElementById("franchiseEquipmentTurnover");
  const equipmentMargin = document.getElementById("franchiseEquipmentMargin");
  const equipmentTableBody = document.getElementById("franchiseEquipmentTableBody");
  const roadCost = document.getElementById("franchiseRoadCost");
  const roadDeposit = document.getElementById("franchiseRoadDeposit");
  const roadContribution = document.getElementById("franchiseRoadContribution");
  const roadMetrics = document.getElementById("franchiseRoadMetrics");
  const attractionsCard = document.getElementById("franchiseAttractionsCard");
  const attractionsDeposit = document.getElementById("franchiseAttractionsDeposit");
  const attractionsPayment = document.getElementById("franchiseAttractionsPayment");
  const attractionsTableBody = document.getElementById("franchiseAttractionsTableBody");
  const packageSummaryRow = document.getElementById("franchisePackageSummaryRow");

  if (!nextButton || !index || !kicker || !title || !text || !scale || !income || !payback || !royalty || !bullets || !caption || !zoneLeft || !zoneCenter || !zoneRight || !map || !incomeTitle || !incomeText || !incomeList || !gamesMargin || !softwareMargin || !equipmentTurnover || !equipmentMargin || !equipmentTableBody || !roadCost || !roadDeposit || !roadContribution || !roadMetrics || !attractionsCard || !attractionsDeposit || !attractionsPayment || !attractionsTableBody || !packageSummaryRow) {
    return;
  }

  const baseEquipmentRows = [
    ["Meta Quest 3S", "25 000", "31 990", "10", "6 990", "69 900"],
    ["BoboVR S3 Pro", "5 200", "7 990", "10", "2 790", "27 900"],
    ["Зарядная станция BD3", "3 800", "5 990", "4", "2 190", "8 760"],
    ["Аккумулятор B100", "3 800", "5 990", "10", "2 190", "21 900"],
    ["Чехлы Q3S", "600", "1 990", "10", "1 390", "13 900"],
    ["Роутер BE10000", "16 000", "27 990", "1", "11 990", "11 990"],
    ['Телевизор Redmi (L43RA-RAE), 43"', "15 000", "24 990", "10", "9 990", "99 900"],
    ["Рабочее место админа", "23 000", "23 000", "1", "0", "0"],
    ["Аудио оборудование", "0", "0", "0", "0", "0"]
  ];

  const plusEquipmentRows = [
    ["Meta Quest 3S", "25 000", "31 990", "20", "6 990", "139 800"],
    ["BoboVR S3 Pro", "5 200", "7 990", "20", "2 790", "55 800"],
    ["Зарядная станция BD3", "3 800", "5 990", "8", "2 190", "17 520"],
    ["Аккумулятор B100", "3 800", "5 990", "20", "2 190", "43 800"],
    ["Чехлы Q3S", "600", "1 990", "20", "1 390", "27 800"],
    ["Роутер BE10000", "16 000", "27 990", "1", "11 990", "11 990"],
    ['Телевизор Redmi (L43RA-RAE), 43"', "15 000", "24 990", "20", "9 990", "199 800"],
    ["Рабочее место админа", "23 000", "23 000", "1", "0", "0"],
    ["Аудио оборудование", "0", "0", "0", "0", "0"]
  ];

  const formats = [
    {
      index: "",
      kicker: "Базовый формат",
      title: "Арена (Compact) 10 + 4",
      text: "",
      scale: "10 мест / 1 арена",
      income: "3 606 330 ₽",
      payback: "≈ 3.21 месяца",
      royalty: '5%<span class="franchise-metric-sub">25 000 ₽ / мес</span><span class="franchise-metric-sub">600 000 ₽ за 24 мес</span>',
      bullets: ["10 основных мест", "4 дополнительных места", "Зона для мероприятий"],
      caption: "",
      zones: ["Зона мероприятий", "10 мест", "4 места"],
      tone: "arena",
      incomeTitle: "Что продаём во франшизе",
      incomeText: "Компания зарабатывает на собранной системе запуска точки, а не на одном элементе.",
      incomeList: ["Игры", "VR-оборудование", "Прочее оборудование", "Система (сайт)", "Дорожки"],
      finance: {
        gamesMargin: "49 490 ₽",
        softwareMargin: "46 990 ₽",
        equipmentTurnover: "Оборот: 804 450 ₽",
        equipmentMargin: "Маржа: 254 250 ₽",
        equipmentRows: baseEquipmentRows,
        roadCost: "Себестоимость: 1 000 000 ₽",
        roadDeposit: "Обеспечительный платёж: 300 000 ₽",
        roadContribution: "Вклад: 700 000 ₽",
        roadMetrics: [
          ["Шт", "10"],
          ["Стоимость за единицу", "199 990 ₽"],
          ["Сумма", "1 999 900 ₽"]
        ],
        attractions: null,
        summary: [
          "Пакет игр FULL: 179 990 ₽",
          "ПО: 49 990 ₽",
          "VR-Оборудование: 804 450 ₽",
          "VR-дорожки: 1 999 900 ₽",
          "Помещение: 572 000 ₽"
        ]
      }
    },
    {
      index: "02",
      kicker: "Усиленный формат франшизы",
      title: "Арена+",
      text: "Формат для площадок, где уже есть потенциал большего трафика и более сильной событийной загрузки. Даёт компании удвоенный уровень дохода на запуске и более сильный роялти-поток.",
      scale: "20 мест / 2 арены",
      income: "4 289 270 ₽",
      payback: "≈ 2.35 месяца",
      royalty: '6%<span class="franchise-metric-sub">48 000 ₽ / мес</span><span class="franchise-metric-sub">1 152 000 ₽ за 24 мес</span>',
      bullets: ["20 игровых мест", "Помещение от 130 метров", "Запуск для франчайзи: от 3 497 300 ₽", "Запуск WARPOINT от 5 000 000 ₽", "Запуск AnotherWorld от 5 000 000 ₽"],
      caption: "",
      zones: ["арена 1", "20 мест", "арена 2"],
      tone: "arena-plus",
      incomeTitle: "Что продаём в усиленном формате",
      incomeText: "Во втором формате компания увеличивает объём продажи системы и усиливает поток за счёт двух арен.",
      incomeList: ["Игры", "VR-оборудование", "Прочее оборудование", "Система (сайт)", "Дорожки"],
      finance: {
        gamesMargin: "98 980 ₽",
        softwareMargin: "93 980 ₽",
        equipmentTurnover: "Оборот: 1 557 910 ₽",
        equipmentMargin: "Маржа: 496 510 ₽",
        equipmentRows: plusEquipmentRows,
        roadCost: "Себестоимость: 2 000 000 ₽",
        roadDeposit: "Обеспечительный платёж: 800 000 ₽",
        roadContribution: "Вклад: 1 200 000 ₽",
        roadMetrics: [
          ["Закуп", "100 000 ₽"],
          ["Продажа", "279 990 ₽"],
          ["Продажа парт", "5 599 800 ₽"],
          ["Шт", "20"],
          ["Маржа (шт)", "179 990 ₽"],
          ["Маржа парт", "3 599 800 ₽"]
        ],
        attractions: null,
        summary: [
          "Вклад на запуск: 510 530 ₽",
          "Платёж в месяц: 217 382 ₽ × 23 месяца",
          "Окупаемость: ≈ 2.35 месяца",
          "Чистая прибыль: 4 289 270 ₽"
        ]
      }
    },
    {
      index: "03",
      kicker: "Флагманский формат франшизы",
      title: "Арена PRO",
      text: "Флагманский формат для самых сильных локаций. Добавление двух VR-аттракционов усиливает выручку, повышает коммерческий потенциал объекта и увеличивает доходность франшизы для компании.",
      scale: "20 мест / 2 арены + 2 аттракциона",
      income: "5 789 270 ₽",
      payback: "≈ 1.49 месяца",
      royalty: '7%<span class="franchise-metric-sub">84 000 ₽ / мес</span><span class="franchise-metric-sub">2 016 000 ₽ за 24 мес</span>',
      bullets: ["20 игровых мест", "Помещение от 155 метров", "Запуск для франчайзи: от 4 497 300 ₽", "Запуск WARPOINT от 10 000 000 ₽"],
      caption: "",
      zones: ["арена 1", "2 аттракциона", "арена 2"],
      tone: "arena-pro",
      incomeTitle: "Что продаём в Арена PRO",
      incomeText: "В PRO-формате доход строится не только на базовой системе запуска, но и на дополнительном слое из двух VR-аттракционов.",
      incomeList: ["Игры", "VR-оборудование", "Прочее оборудование", "Система (сайт)", "Дорожки", "2 VR-аттракциона"],
      finance: {
        gamesMargin: "98 980 ₽",
        softwareMargin: "93 980 ₽",
        equipmentTurnover: "Оборот: 1 557 910 ₽",
        equipmentMargin: "Маржа: 496 510 ₽",
        equipmentRows: plusEquipmentRows,
        roadCost: "Себестоимость: 2 000 000 ₽",
        roadDeposit: "Обеспечительный платёж: 800 000 ₽",
        roadContribution: "Вклад: 1 200 000 ₽",
        roadMetrics: [
          ["Закуп", "100 000 ₽"],
          ["Продажа", "279 990 ₽"],
          ["Продажа парт", "5 599 800 ₽"],
          ["Шт", "20"],
          ["Маржа (шт)", "179 990 ₽"],
          ["Маржа парт", "3 599 800 ₽"]
        ],
        attractions: {
          deposit: "Обеспечительный платёж: 1 000 000 ₽",
          payment: "Остаток: равными платежами 23 месяца",
          rows: [
            ["Аттракцион 1", "450 000 ₽", "940 000 ₽", "490 000 ₽"],
            ["Аттракцион 2", "450 000 ₽", "940 000 ₽", "490 000 ₽"]
          ]
        },
        summary: [
          "Вклад на запуск: 410 530 ₽",
          "Платёж в месяц: 275 882 ₽ × 23 месяца",
          "Окупаемость: ≈ 1.49 месяца",
          "Чистая прибыль: 5 789 270 ₽"
        ]
      }
    },
    {
      index: "04",
      kicker: "Базовый формат франшизы / FULL",
      title: "Арена (Full)",
      text: "FULL-вариант базового формата для партнёра, которому нужен первый вход в модель уже с расширенной игровой конфигурацией и более сильной продуктовой упаковкой.",
      scale: "10 мест / 1 арена / FULL",
      income: "1 350 730 ₽",
      payback: "сразу",
      royalty: '5%<span class="franchise-metric-sub">25 000 ₽ / мес</span><span class="franchise-metric-sub">600 000 ₽ за 24 мес</span>',
      bullets: ["10 игровых мест", "FULL-конфигурация", "Помещение от 62 метров", "Запуск франчайзи: от 3 535 450 ₽", "Запуск WARPOINT от 4 000 000 ₽", "Запуск AnotherWorld от 3 500 000 ₽"],
      caption: "",
      zones: ["1 арена", "10 мест", "FULL"],
      tone: "arena",
      incomeTitle: "Что продаём во франшизе",
      incomeText: "Компания зарабатывает на собранной системе запуска точки, а не на одном элементе.",
      incomeList: ["Игры FULL", "VR-оборудование", "Прочее оборудование", "Система (сайт)", "Дорожки"],
      finance: {
        gamesMargin: "49 490 ₽",
        softwareMargin: "46 990 ₽",
        equipmentTurnover: "Оборот: 804 450 ₽",
        equipmentMargin: "Маржа: 254 250 ₽",
        equipmentRows: baseEquipmentRows,
        roadCost: "Себестоимость: 1 000 000 ₽",
        roadDeposit: "Продажа партнёру: 2 000 000 ₽",
        roadContribution: "Лизинг: не используется",
        roadMetrics: [
          ["Закуп", "100 000 ₽"],
          ["Продажа", "200 000 ₽"],
          ["Продажа парт", "2 000 000 ₽"],
          ["Шт", "10"],
          ["Маржа (шт)", "100 000 ₽"],
          ["Маржа парт", "1 000 000 ₽"]
        ],
        attractions: null,
        summary: [
          "Вклад на запуск: 0 ₽",
          "Платёж в месяц: не используется",
          "Окупаемость: сразу",
          "Чистая прибыль: 1 350 730 ₽"
        ]
      }
    },
    {
      index: "05",
      kicker: "Усиленный формат франшизы / FULL",
      title: "Арена + (Full)",
      text: "FULL-вариант усиленного формата для площадок с большим трафиком, где нужно собрать более мощную продуктовую конфигурацию на двух аренах.",
      scale: "20 мест / 2 арены / FULL",
      income: "2 689 470 ₽",
      payback: "сразу",
      royalty: '6%<span class="franchise-metric-sub">48 000 ₽ / мес</span><span class="franchise-metric-sub">1 152 000 ₽ за 24 мес</span>',
      bullets: ["20 игровых мест", "FULL-конфигурация", "Помещение от 130 метров", "Запуск для франчайзи: от 7 070 750 ₽", "Запуск WARPOINT от 5 000 000 ₽", "Запуск AnotherWorld от 5 000 000 ₽"],
      caption: "",
      zones: ["арена 1", "20 мест", "FULL"],
      tone: "arena-plus",
      incomeTitle: "Что продаём в усиленном формате",
      incomeText: "Во втором формате компания увеличивает объём продажи системы и усиливает поток за счёт двух арен.",
      incomeList: ["Игры FULL", "VR-оборудование", "Прочее оборудование", "Система (сайт)", "Дорожки"],
      finance: {
        gamesMargin: "98 980 ₽",
        softwareMargin: "93 980 ₽",
        equipmentTurnover: "Оборот: 1 557 910 ₽",
        equipmentMargin: "Маржа: 496 510 ₽",
        equipmentRows: plusEquipmentRows,
        roadCost: "Себестоимость: 2 000 000 ₽",
        roadDeposit: "Продажа партнёру: 4 000 000 ₽",
        roadContribution: "Лизинг: не используется",
        roadMetrics: [
          ["Закуп", "100 000 ₽"],
          ["Продажа", "200 000 ₽"],
          ["Продажа парт", "4 000 000 ₽"],
          ["Шт", "20"],
          ["Маржа (шт)", "100 000 ₽"],
          ["Маржа парт", "2 000 000 ₽"]
        ],
        attractions: null,
        summary: [
          "Вклад на запуск: 0 ₽",
          "Платёж в месяц: не используется",
          "Окупаемость: сразу",
          "Чистая прибыль: 2 689 470 ₽"
        ]
      }
    },
    {
      index: "06",
      kicker: "Флагманский формат франшизы / FULL",
      title: "Арена Pro (Full)",
      text: "FULL-вариант флагманского формата для самых сильных площадок: две арены, два аттракциона и расширенная игровая конфигурация.",
      scale: "20 мест / 2 арены + 2 аттракциона / FULL",
      income: "3 669 470 ₽",
      payback: "сразу",
      royalty: '7%<span class="franchise-metric-sub">84 000 ₽ / мес</span><span class="franchise-metric-sub">2 016 000 ₽ за 24 мес</span>',
      bullets: ["20 игровых мест", "FULL-конфигурация", "Помещение от 155 метров", "Запуск для франчайзи: от 9 155 910 ₽", "Запуск WARPOINT от 10 000 000 ₽"],
      caption: "",
      zones: ["арена 1", "FULL + аттракционы", "арена 2"],
      tone: "arena-pro",
      incomeTitle: "Что продаём в Арена PRO",
      incomeText: "В PRO-формате доход строится не только на базовой системе запуска, но и на дополнительном слое из двух VR-аттракционов.",
      incomeList: ["Игры FULL", "VR-оборудование", "Прочее оборудование", "Система (сайт)", "Дорожки", "2 VR-аттракциона"],
      finance: {
        gamesMargin: "98 980 ₽",
        softwareMargin: "93 980 ₽",
        equipmentTurnover: "Оборот: 1 557 910 ₽",
        equipmentMargin: "Маржа: 496 510 ₽",
        equipmentRows: plusEquipmentRows,
        roadCost: "Себестоимость: 2 000 000 ₽",
        roadDeposit: "Продажа партнёру: 4 000 000 ₽",
        roadContribution: "Лизинг: не используется",
        roadMetrics: [
          ["Закуп", "100 000 ₽"],
          ["Продажа", "200 000 ₽"],
          ["Продажа парт", "4 000 000 ₽"],
          ["Шт", "20"],
          ["Маржа (шт)", "100 000 ₽"],
          ["Маржа парт", "2 000 000 ₽"]
        ],
        attractions: {
          deposit: "Обеспечительный платёж: 1 000 000 ₽",
          payment: "Остаток: равными платежами 23 месяца",
          rows: [
            ["Аттракцион 1", "450 000 ₽", "940 000 ₽", "490 000 ₽"],
            ["Аттракцион 2", "450 000 ₽", "940 000 ₽", "490 000 ₽"]
          ]
        },
        summary: [
          "Вклад на запуск: 0 ₽",
          "Платёж в месяц: не используется",
          "Окупаемость: сразу",
          "Чистая прибыль: 3 669 470 ₽"
        ]
      }
    }
  ];

  let currentIndex = 0;

  function renderFormat() {
    const current = formats[currentIndex];
    index.textContent = current.index;
    kicker.textContent = current.kicker;
    title.textContent = current.title;
    text.textContent = current.text;
    scale.textContent = current.scale;
    income.textContent = current.income;
    payback.textContent = current.payback;
    royalty.innerHTML = current.royalty;
    caption.textContent = current.caption;
    caption.style.display = current.caption ? "block" : "none";
    zoneLeft.textContent = current.zones[0];
    zoneCenter.textContent = current.zones[1];
    zoneRight.textContent = current.zones[2];
    bullets.innerHTML = current.bullets.map((item) => `<li>${item}</li>`).join("");
    incomeTitle.textContent = current.incomeTitle;
    incomeText.textContent = current.incomeText;
    incomeList.innerHTML = current.incomeList.map((item) => `<li>${item}</li>`).join("");
    gamesMargin.textContent = current.finance.gamesMargin;
    softwareMargin.textContent = current.finance.softwareMargin;
    equipmentTurnover.textContent = current.finance.equipmentTurnover;
    equipmentMargin.textContent = current.finance.equipmentMargin;
    equipmentTableBody.innerHTML = current.finance.equipmentRows
      .map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`)
      .join("");
    roadCost.textContent = current.finance.roadCost;
    roadDeposit.textContent = current.finance.roadDeposit;
    roadContribution.textContent = current.finance.roadContribution;
    roadMetrics.innerHTML = current.finance.roadMetrics
      .map(([label, value]) => `<li><span>${label}</span><strong>${value}</strong></li>`)
      .join("");

    if (current.finance.attractions) {
      attractionsCard.style.display = "grid";
      attractionsDeposit.textContent = current.finance.attractions.deposit;
      attractionsPayment.textContent = current.finance.attractions.payment;
      attractionsTableBody.innerHTML = current.finance.attractions.rows
        .map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`)
        .join("");
    } else {
      attractionsCard.style.display = "none";
      attractionsTableBody.innerHTML = "";
    }

    packageSummaryRow.innerHTML = current.finance.summary
      .map((item) => `<span>${item}</span>`)
      .join("");
    map.dataset.tone = current.tone;
  }

  nextButton.addEventListener("click", () => {
    currentIndex = (currentIndex + 1) % formats.length;
    renderFormat();
  });

  renderFormat();
}

function setupRevenueModelSwitcher() {
  const prevButton = document.getElementById("revenueModelPrev");
  const nextButton = document.getElementById("revenueModelNext");
  const caption = document.getElementById("revenueModelCaption");
  const profitDelta = document.getElementById("monthlyProfitDelta");
  const ownProfitRub = document.getElementById("monthlyOwnProfitRub");
  const competitorProfitRub = document.getElementById("monthlyCompetitorProfitRub");
  const ownCenterCaption = document.getElementById("monthlyOwnCenterCaption");
  const competitorCenterCaption = document.getElementById("monthlyCompetitorCenterCaption");
  const ownLegend = document.getElementById("monthlyOwnLegend");
  const competitorLegend = document.getElementById("monthlyCompetitorLegend");
  const ownRing = rootQuery(".monthly-ring-own");
  const competitorRing = rootQuery(".monthly-ring-competitor");

  if (!prevButton || !nextButton || !caption || !profitDelta || !ownProfitRub || !competitorProfitRub || !ownCenterCaption || !competitorCenterCaption || !ownLegend || !competitorLegend || !ownRing || !competitorRing) {
    return;
  }

  const models = [400000, 600000, 800000, 1000000];
  const ownCosts = { rent: 80000, teamFixed: 40000, teamFixedHigh: 60000, marketing: 120000, ops: 12000 };
  const competitorCosts = { rent: 160000, teamFixed: 40000, teamFixedHigh: 60000, marketing: 120000, ops: 12000 };
  const teamRate = 0.05;
  let marketingRate = 0.05;
  const ownRoyaltyRate = 0.06;
  const competitorRoyaltyRate = 0.07;
  const taxRate = 0.15;
  const marketingRateButtons = rootQueryAll("[data-marketing-rate]");
  let currentIndex = 2;

  const percentFormatter = new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 1
  });
  const currencyFormatter = new Intl.NumberFormat("ru-RU");

  function percent(value, revenue) {
    return Number(((value / revenue) * 100).toFixed(1));
  }

  function formatSignedPercent(value) {
    const sign = value > 0 ? "+" : value < 0 ? "-" : "";
    return `${sign}${percentFormatter.format(Math.abs(value))}%`;
  }

  function getTeamFixed(costs, revenue) {
    return revenue === 1000000 ? costs.teamFixedHigh : costs.teamFixed;
  }

  function updateMarketingRateButtons() {
    marketingRateButtons.forEach((button) => {
      const isActive = Number(button.dataset.marketingRate) === marketingRate;
      button.classList.toggle("is-active", isActive);
      button.setAttribute("aria-pressed", isActive ? "true" : "false");
    });
  }

  function buildLegendHtml(costs, revenue, royaltyRate, royaltyLabel) {
    const rent = percent(costs.rent, revenue);
    const salaryRub = getTeamFixed(costs, revenue) + (revenue * teamRate);
    const salary = percent(salaryRub, revenue);
    const marketingRub = revenue * marketingRate;
    const marketing = Number((marketingRate * 100).toFixed(1));
    const royaltyRub = revenue * royaltyRate;
    const royalty = Number((royaltyRate * 100).toFixed(1));
    const ops = percent(costs.ops, revenue);
    const profitBeforeTax = Number((100 - rent - salary - marketing - royalty - ops).toFixed(1));
    const taxRub = (revenue - costs.rent - salaryRub - marketingRub - royaltyRub - costs.ops) * taxRate;
    const tax = Number((profitBeforeTax * taxRate).toFixed(1));
    const profitRub = revenue - costs.rent - salaryRub - marketingRub - royaltyRub - costs.ops - taxRub;
    const profit = Number((profitBeforeTax - tax).toFixed(1));

    return {
      html: `
        <li><i class="ring-swatch ring-rent"></i><span class="monthly-ring-label">Аренда<small class="monthly-ring-sub">${currencyFormatter.format(Math.round(costs.rent))} ₽</small></span><strong>≈ ${percentFormatter.format(rent)}%</strong></li>
        <li><i class="ring-swatch ring-salary"></i><span class="monthly-ring-label">Команда<small class="monthly-ring-sub">${currencyFormatter.format(Math.round(salaryRub))} ₽</small></span><strong>≈ ${percentFormatter.format(salary)}%</strong></li>
        <li><i class="ring-swatch ring-marketing"></i><span class="monthly-ring-label">Маркетинг<small class="monthly-ring-sub">${currencyFormatter.format(Math.round(marketingRub))} ₽</small></span><strong>≈ ${percentFormatter.format(marketing)}%</strong></li>
        <li><i class="ring-swatch ring-royalty"></i><span class="monthly-ring-label">Роялти<small class="monthly-ring-sub">${currencyFormatter.format(Math.round(royaltyRub))} ₽</small></span><strong>${royaltyLabel}</strong></li>
        <li><i class="ring-swatch ring-ops"></i><span class="monthly-ring-label">Интернет + расходники<small class="monthly-ring-sub">${currencyFormatter.format(Math.round(costs.ops))} ₽</small></span><strong>≈ ${percentFormatter.format(ops)}%</strong></li>
        <li><i class="ring-swatch ring-tax"></i><span class="monthly-ring-label">Налоги<small class="monthly-ring-sub">${currencyFormatter.format(Math.round(taxRub))} ₽</small></span><strong>≈ ${percentFormatter.format(tax)}%</strong></li>
        <li class="monthly-ring-growth"><i class="ring-swatch ring-growth"></i><span class="monthly-ring-label">Чистая прибыль<small class="monthly-ring-sub">${currencyFormatter.format(Math.round(profitRub))} ₽</small></span><strong>≈ ${percentFormatter.format(profit)}%</strong></li>
      `,
      profitRub,
      segments: { rent, salary, marketing, royalty, ops, tax, profit }
    };
  }

  function applyRing(element, segments) {
    const { rent, salary, marketing, royalty, ops, tax, profit } = segments;
    const s1 = rent;
    const s2 = rent + salary;
    const s3 = s2 + marketing;
    const s4 = s3 + royalty;
    const s5 = s4 + ops;
    const s6 = s5 + tax;
    element.style.background = `conic-gradient(
      #c37635 0 ${s1}%,
      #244f87 ${s1}% ${s2}%,
      #5b8bd7 ${s2}% ${s3}%,
      #7b61c9 ${s3}% ${s4}%,
      #cfd9e7 ${s4}% ${s5}%,
      #c94f4f ${s5}% ${s6}%,
      #44a36f ${s6}% ${s6 + profit}%
    )`;
  }

  function render() {
    const revenue = models[currentIndex];
    const revenueLabel = new Intl.NumberFormat("ru-RU").format(revenue);
    const own = buildLegendHtml(ownCosts, revenue, ownRoyaltyRate, `${percentFormatter.format(ownRoyaltyRate * 100)}%`);
    const competitor = buildLegendHtml(competitorCosts, revenue, competitorRoyaltyRate, `от ${percentFormatter.format(competitorRoyaltyRate * 100)}%`);

    caption.textContent = `Пример модели при обороте ${revenueLabel} ₽`;
    ownCenterCaption.textContent = `Оборот — ${revenueLabel} ₽`;
    competitorCenterCaption.textContent = `Оборот — ${revenueLabel} ₽`;
    ownLegend.innerHTML = own.html;
    competitorLegend.innerHTML = competitor.html;
    ownProfitRub.textContent = `${currencyFormatter.format(Math.round(own.profitRub))} ₽`;
    competitorProfitRub.textContent = `${currencyFormatter.format(Math.round(competitor.profitRub))} ₽`;
    const competitorBaseProfit = competitor.profitRub > 0 ? competitor.profitRub : 0;
    const efficiencyDelta = competitorBaseProfit ? ((own.profitRub - competitor.profitRub) / competitor.profitRub) * 100 : 0;
    profitDelta.textContent = formatSignedPercent(efficiencyDelta);
    applyRing(ownRing, own.segments);
    applyRing(competitorRing, competitor.segments);
    updateMarketingRateButtons();
  }

  marketingRateButtons.forEach((button) => {
    button.addEventListener("click", () => {
      marketingRate = Number(button.dataset.marketingRate);
      render();
    });
  });

  prevButton.addEventListener("click", () => {
    currentIndex = (currentIndex - 1 + models.length) % models.length;
    render();
  });

  nextButton.addEventListener("click", () => {
    currentIndex = (currentIndex + 1) % models.length;
    render();
  });

  render();
}

setupMonthlyEconomics();
setupGameModal();
setupFranchiseCompare();
setupFranchiseFormats();
setupRevenueModelSwitcher();
updateSectionScrollOffsets();
