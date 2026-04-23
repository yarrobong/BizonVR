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

bindNavigation();
bindReveal();
bindForm();
updateEconomics();
