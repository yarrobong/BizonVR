const model = {
  launchCost: 3736330,
  revenue: 800000,
  expenses: 325700,
  netProfit: 474300,
  investorShare: 0.7,
  paybackBufferMonths: 3.1,
  rent: 80000,
  salary: 80000,
  ops: 12000,
  royaltyRate: 0.06,
  taxRate: 0.15,
};

const marketingRate = 0.05;
const MOBILE_MENU_BREAKPOINT = "(max-width: 760px)";
const MOBILE_DATA_CARD_CONFIG = {
  "investor-upside": {
    titleLabel: "Открыто точек",
    title: (cells) => formatPointsTitle(cells[0]),
    summary: (cells) => `Доход инвестора: ${cells[3]}`,
    details: (headers, cells) => [
      { label: headers[1], value: cells[1] },
      { label: headers[2], value: cells[2] },
      { label: headers[3], value: cells[3] },
    ],
  },
  "growth-plan": {
    titleLabel: "Период",
    title: (cells) => cells[0],
    summary: (cells) => `${cells[2]} точек • ${cells[3]} • ${cells[4]}`,
    details: (headers, cells) => [
      { label: headers[1], value: cells[1] },
      { label: headers[2], value: cells[2] },
      { label: headers[3], value: cells[3] },
      { label: headers[4], value: cells[4] },
    ],
  },
  "exit-strategy": {
    titleLabel: "Когда",
    title: (cells) => cells[0],
    summary: (cells) => cells[1],
    details: (headers, cells) => [
      { label: headers[2], value: cells[2] },
      { label: headers[3], value: cells[3] },
      { label: headers[4], value: cells[4] },
    ],
  },
};

function normalizeText(value) {
  return (value || "").replace(/\s+/g, " ").trim();
}

function formatPointsTitle(value) {
  const count = Number.parseInt(value, 10);

  if (!Number.isFinite(count)) return `${value} точек`;

  const remainder10 = count % 10;
  const remainder100 = count % 100;

  if (remainder10 === 1 && remainder100 !== 11) return `${count} точка`;
  if (remainder10 >= 2 && remainder10 <= 4 && (remainder100 < 12 || remainder100 > 14)) return `${count} точки`;
  return `${count} точек`;
}

function formatCurrency(value) {
  return `${Math.round(value).toLocaleString("ru-RU")} ₽`;
}

function formatMonths(value) {
  if (!Number.isFinite(value)) return "н/д";

  return `${value.toLocaleString("ru-RU", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })} мес`;
}

function calculateScenario(revenue, marketing) {
  const fixedCosts = model.rent + model.salary + model.ops;
  const variableCosts = revenue * (marketing + model.royaltyRate);
  const expenses = fixedCosts + variableCosts;
  const profitBeforeTax = revenue - expenses;
  const netProfit = Math.max(profitBeforeTax * (1 - model.taxRate), 0);
  const payback = netProfit > 0 ? model.launchCost / netProfit : Number.POSITIVE_INFINITY;

  return { expenses, netProfit, payback };
}

function updateEconomics() {
  const investorIncome = model.netProfit * model.investorShare;
  const pointPayback = model.netProfit > 0 ? (model.launchCost / model.netProfit) + model.paybackBufferMonths : Number.POSITIVE_INFINITY;
  const investorPayback = investorIncome > 0 ? (model.launchCost / investorIncome) + model.paybackBufferMonths : Number.POSITIVE_INFINITY;

  document.getElementById("ecoRevenue").textContent = formatCurrency(model.revenue);
  document.getElementById("ecoExpenses").textContent = formatCurrency(model.expenses);
  document.getElementById("ecoProfit").textContent = formatCurrency(model.netProfit);
  document.getElementById("ecoInvestorIncome").textContent = formatCurrency(investorIncome);
  document.getElementById("ecoPayback").textContent = formatMonths(pointPayback);
  document.getElementById("ecoInvestorPayback").textContent = formatMonths(investorPayback);
}

function bindNavigation() {
  const links = Array.from(document.querySelectorAll(".nav a[href^='#']"));
  const sections = links
    .map((link) => document.querySelector(link.getAttribute("href")))
    .filter(Boolean);

  if (!links.length || !sections.length) return;

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;

        const current = `#${entry.target.id}`;
        links.forEach((link) => {
          link.classList.toggle("is-active", link.getAttribute("href") === current);
        });
      });
    },
    { rootMargin: "-35% 0px -50% 0px", threshold: 0.1 }
  );

  sections.forEach((section) => observer.observe(section));
}

function buildMobileDataCards() {
  const tables = Array.from(document.querySelectorAll("[data-mobile-cards]"));
  let hasBuiltCards = false;

  tables.forEach((table) => {
    if (table.dataset.mobileCardsBuilt === "1") return;

    const config = MOBILE_DATA_CARD_CONFIG[table.dataset.mobileCards];
    const rows = Array.from(table.querySelectorAll("tbody tr"));
    const headers = Array.from(table.querySelectorAll("thead th")).map((cell) => normalizeText(cell.textContent));

    if (!config || !headers.length || !rows.length) return;

    const root = document.createElement("div");
    root.className = "mobile-data-accordion";
    root.dataset.mobileCardsRoot = table.dataset.mobileCards;

    rows.forEach((row, index) => {
      const cells = Array.from(row.cells).map((cell) => normalizeText(cell.textContent));
      const contentId = `${table.dataset.mobileCards}-mobile-card-${index}`;
      const article = document.createElement("article");
      article.className = "mobile-data-card";

      const detailMarkup = config.details(headers, cells)
        .map(
          (item) => `
            <div class="mobile-data-card-detail">
              <dt>${item.label}</dt>
              <dd>${item.value}</dd>
            </div>
          `
        )
        .join("");

      article.innerHTML = `
        <div class="mobile-data-card-head">
          <span class="mobile-data-card-kicker">${config.titleLabel}</span>
          <strong class="mobile-data-card-title">${config.title(cells)}</strong>
          <p class="mobile-data-card-summary">${config.summary(cells)}</p>
          <button
            class="mobile-data-card-toggle"
            type="button"
            aria-expanded="false"
            aria-controls="${contentId}"
          >
            <span>Показать детали</span>
          </button>
        </div>
        <div class="mobile-data-card-content" id="${contentId}" hidden>
          <dl class="mobile-data-card-details">
            ${detailMarkup}
          </dl>
        </div>
      `;

      root.appendChild(article);
    });

    table.insertAdjacentElement("afterend", root);
    table.dataset.mobileCardsBuilt = "1";
    hasBuiltCards = true;
  });

  if (hasBuiltCards) {
    document.body.classList.add("mobile-data-enhanced");
  }
}

function bindMobileDataCards() {
  document.addEventListener("click", (event) => {
    const button = event.target.closest(".mobile-data-card-toggle");

    if (!button) return;

    const contentId = button.getAttribute("aria-controls");
    const content = contentId ? document.getElementById(contentId) : null;

    if (!content) return;

    const isOpen = button.getAttribute("aria-expanded") === "true";
    button.setAttribute("aria-expanded", String(!isOpen));
    button.querySelector("span").textContent = isOpen ? "Показать детали" : "Скрыть детали";
    content.hidden = isOpen;
  });
}

function bindMobileMenu() {
  const topbar = document.querySelector(".topbar");
  const toggle = document.querySelector(".topbar-menu-toggle");

  if (!topbar || !toggle) return;

  const panelId = toggle.getAttribute("aria-controls");
  const panel = panelId ? document.getElementById(panelId) : null;

  if (!panel) return;

  const mediaQuery = window.matchMedia(MOBILE_MENU_BREAKPOINT);
  const menuLinks = Array.from(panel.querySelectorAll("a"));

  function isMobileViewport() {
    return mediaQuery.matches;
  }

  function setMenuState(isOpen) {
    if (!isMobileViewport()) {
      topbar.classList.remove("is-menu-open");
      toggle.setAttribute("aria-expanded", "false");
      panel.setAttribute("aria-hidden", "false");
      return;
    }

    topbar.classList.toggle("is-menu-open", isOpen);
    toggle.setAttribute("aria-expanded", String(isOpen));
    panel.setAttribute("aria-hidden", String(!isOpen));
  }

  function closeMenu() {
    setMenuState(false);
  }

  function syncMenuState() {
    if (isMobileViewport()) {
      const isOpen = topbar.classList.contains("is-menu-open");
      toggle.setAttribute("aria-expanded", String(isOpen));
      panel.setAttribute("aria-hidden", String(!isOpen));
      return;
    }

    closeMenu();
  }

  toggle.addEventListener("click", () => {
    const isOpen = toggle.getAttribute("aria-expanded") === "true";
    setMenuState(!isOpen);
  });

  menuLinks.forEach((link) => {
    link.addEventListener("click", () => {
      closeMenu();
    });
  });

  document.addEventListener("click", (event) => {
    if (!isMobileViewport()) return;
    if (!topbar.classList.contains("is-menu-open")) return;
    if (topbar.contains(event.target)) return;
    closeMenu();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    closeMenu();
  });

  if (typeof mediaQuery.addEventListener === "function") {
    mediaQuery.addEventListener("change", syncMenuState);
  } else if (typeof mediaQuery.addListener === "function") {
    mediaQuery.addListener(syncMenuState);
  }

  syncMenuState();
}

function bindReveal() {
  const items = document.querySelectorAll(".reveal");

  const observer = new IntersectionObserver(
    (entries, obs) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        obs.unobserve(entry.target);
      });
    },
    { threshold: 0.16 }
  );

  items.forEach((item) => observer.observe(item));
}

function bindForm() {
  const form = document.getElementById("contact-form");
  const feedback = document.getElementById("formFeedback");

  if (!form || !feedback) return;

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    feedback.hidden = false;
  });
}

buildMobileDataCards();
bindMobileDataCards();
bindMobileMenu();
bindNavigation();
bindReveal();
bindForm();
updateEconomics();
