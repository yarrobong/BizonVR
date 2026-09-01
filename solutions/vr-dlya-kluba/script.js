const menuToggle = document.getElementById("menuToggle");
const body = document.body;
const navLinks = Array.from(document.querySelectorAll(".nav a"));
const sections = navLinks
  .map((link) => document.querySelector(link.getAttribute("href")))
  .filter(Boolean);
const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

if (menuToggle) {
  menuToggle.addEventListener("click", () => {
    const isExpanded = menuToggle.getAttribute("aria-expanded") === "true";
    menuToggle.setAttribute("aria-expanded", String(!isExpanded));
    body.classList.toggle("menu-open", !isExpanded);
  });
}

navLinks.forEach((link) => {
  link.addEventListener("click", () => {
    body.classList.remove("menu-open");
    menuToggle?.setAttribute("aria-expanded", "false");
  });
});

function setActiveLink() {
  const offset = window.scrollY + 140;
  let currentId = sections[0]?.id;

  sections.forEach((section) => {
    if (section.offsetTop <= offset) {
      currentId = section.id;
    }
  });

  navLinks.forEach((link) => {
    const isActive = link.getAttribute("href") === `#${currentId}`;
    link.classList.toggle("is-active", isActive);
  });
}

let navSyncFrame = 0;

function syncActiveLinkOnScroll() {
  if (navSyncFrame) {
    return;
  }

  navSyncFrame = window.requestAnimationFrame(() => {
    setActiveLink();
    navSyncFrame = 0;
  });
}

window.addEventListener("scroll", syncActiveLinkOnScroll, { passive: true });
window.addEventListener("resize", syncActiveLinkOnScroll, { passive: true });
setActiveLink();

const revealItems = document.querySelectorAll(".reveal");

if (prefersReducedMotion || typeof IntersectionObserver !== "function") {
  revealItems.forEach((item) => item.classList.add("is-visible"));
} else {
  const revealObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          revealObserver.unobserve(entry.target);
        }
      });
    },
    {
      threshold: 0.16,
      rootMargin: "0px 0px -40px 0px",
    }
  );

  revealItems.forEach((item) => revealObserver.observe(item));
}

function setupGameModal() {
  const cards = Array.from(document.querySelectorAll(".game-card"));
  const modal = document.getElementById("gameModal");
  const stage = document.getElementById("gameModalStage");
  const title = document.getElementById("gameModalTitle");
  const meta = document.getElementById("gameModalMeta");
  const description = document.getElementById("gameModalDescription");
  const specs = document.getElementById("gameModalSpecs");
  const prev = document.getElementById("gameModalPrev");
  const next = document.getElementById("gameModalNext");
  const closeButtons = document.querySelectorAll("[data-close-modal]");

  if (!cards.length || !modal || !stage || !title || !meta || !description || !specs || !prev || !next) {
    return;
  }

  let currentSlides = [];
  let currentSlide = 0;

  function renderSlide() {
    const slide = currentSlides[currentSlide];

    if (!slide) {
      stage.innerHTML = "";
      prev.hidden = true;
      next.hidden = true;
      return;
    }

    prev.hidden = currentSlides.length < 2;
    next.hidden = currentSlides.length < 2;

    if (slide.type === "cover") {
      stage.innerHTML = `
        <div class="game-modal-slide game-modal-media-slide">
          <div class="game-cover game-modal-cover ${slide.className}">
            <span>${slide.title}</span>
          </div>
        </div>
      `;
      return;
    }

    stage.innerHTML = `
      <div class="game-modal-slide game-modal-media-slide">
        <img class="game-modal-media" src="${slide.src}" alt="${slide.title}">
      </div>
    `;
  }

  function openGameModal(card) {
    const titleNode = card.querySelector("h3");
    const badgeNode = card.querySelector(".game-badge");
    const descriptionNode = card.querySelector("p");
    const metaNodes = Array.from(card.querySelectorAll(".game-meta span"));
    const imageNode = card.querySelector(".game-cover img");
    const coverNode = card.querySelector(".game-cover");
    const image = imageNode?.getAttribute("src");

    const gameTitle = titleNode?.textContent.trim() || "Игра";
    const badge = badgeNode?.textContent.trim() || "—";
    const metaItems = metaNodes.map((item) => item.textContent.trim()).filter(Boolean);
    const gameDescription = descriptionNode?.textContent.trim() || "";

    currentSlides = [];

    if (image) {
      currentSlides.push({ type: "image", src: image, title: gameTitle });
    } else if (coverNode) {
      const coverClasses = Array.from(coverNode.classList)
        .filter((className) => className !== "game-cover")
        .join(" ");

      currentSlides.push({
        type: "cover",
        className: coverClasses,
        title: gameTitle,
      });
    }

    currentSlide = 0;
    title.textContent = gameTitle;
    meta.innerHTML = [badge, ...metaItems].map((item) => `<span>${item}</span>`).join("");
    description.textContent = gameDescription;
    specs.innerHTML = `
      <article class="game-modal-spec-item">
        <span>Формат</span>
        <strong>${badge}</strong>
      </article>
      <article class="game-modal-spec-item">
        <span>Теги</span>
        <strong>${metaItems.length ? metaItems.join(" / ") : "—"}</strong>
      </article>
    `;

    renderSlide();
    modal.classList.add("is-open");
    modal.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
  }

  function closeGameModal() {
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
    stage.innerHTML = "";
  }

  cards.forEach((card) => {
    const titleNode = card.querySelector("h3");
    if (!titleNode) {
      return;
    }

    const gameTitle = titleNode.textContent.trim();
    card.setAttribute("tabindex", "0");
    card.setAttribute("role", "button");
    card.setAttribute("aria-label", `Открыть описание игры ${gameTitle}`);

    const handler = () => openGameModal(card);
    card.addEventListener("click", handler);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        handler();
      }
    });
  });

  prev.addEventListener("click", () => {
    if (currentSlides.length < 2) {
      return;
    }
    currentSlide = (currentSlide - 1 + currentSlides.length) % currentSlides.length;
    renderSlide();
  });

  next.addEventListener("click", () => {
    if (currentSlides.length < 2) {
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
}

function setupGamesPagination() {
  const pagedGrids = Array.from(document.querySelectorAll("[data-paged-games]"));

  pagedGrids.forEach((grid) => {
    const cards = Array.from(grid.querySelectorAll(".game-card"));
    const pageSize = Number(grid.dataset.pageSize) || 3;
    const pagination = grid.parentElement?.querySelector("[data-games-pagination]");

    if (!pagination || cards.length <= pageSize) {
      if (pagination) {
        pagination.hidden = true;
      }
      return;
    }

    const pageCount = Math.ceil(cards.length / pageSize);

    function renderPage(pageIndex) {
      cards.forEach((card, index) => {
        const start = pageIndex * pageSize;
        const end = start + pageSize;
        card.hidden = index < start || index >= end;
      });

      Array.from(pagination.querySelectorAll(".games-page-button")).forEach((button, index) => {
        const isActive = index === pageIndex;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-current", isActive ? "page" : "false");
      });
    }

    pagination.innerHTML = "";

    for (let index = 0; index < pageCount; index += 1) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "games-page-button";
      button.textContent = String(index + 1);
      button.setAttribute("aria-label", `Показать страницу ${index + 1}`);
      button.addEventListener("click", () => renderPage(index));
      pagination.appendChild(button);
    }

    renderPage(0);
  });
}

setupGamesPagination();
setupGameModal();
