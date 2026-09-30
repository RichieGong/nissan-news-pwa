// ---- MOCK DATA -------------------------------------------------------------
// This is fake news data so the UI works before any backend exists.
// Later, this array gets replaced by data fetched from the news backend.
const MOCK_NEWS = [
  {
    id: 1,
    time: "2026-09-18T09:40:00Z",
    source: "Reuters",
    tag: "Tariffs",
    title: "EU proposes new tariff structure on imported EV battery components",
    summary: "Brussels unveiled draft rules that would phase in duties on battery cells and modules from non-EU suppliers over three years, a move the auto industry warns will raise EV costs across Europe.",
    url: "https://example.com/eu-tariffs"
  },
  {
    id: 2,
    time: "2026-09-18T07:15:00Z",
    source: "Nikkei Asia",
    tag: "Trade",
    title: "Container shipping rates on Asia-Europe routes climb ahead of peak season",
    summary: "Spot rates for Asia-to-Europe container freight rose for a fourth straight week as carriers reroute around the Red Sea, adding weeks to delivery times for auto parts shipments.",
    url: "https://example.com/shipping-rates"
  },
  {
    id: 3,
    time: "2026-09-17T18:05:00Z",
    source: "Automotive News",
    tag: "Parts",
    title: "Nissan signs new battery supply agreement with European cell maker",
    summary: "The five-year deal covers battery packs for Nissan's upcoming compact EVs built in the UK, and is designed to shield the automaker from supplier concentration risk in Asia.",
    url: "https://example.com/battery-supply"
  },
  {
    id: 4,
    time: "2026-09-17T14:30:00Z",
    source: "Bloomberg",
    tag: "Trade",
    title: "US and Mexico near agreement on rules of origin for auto parts",
    summary: "Negotiators are close to updating USMCA provisions on regional value content, which would allow more Mexican-made components to count toward tariff-free status.",
    url: "https://example.com/usmca-origin"
  },
  {
    id: 5,
    time: "2026-09-17T10:20:00Z",
    source: "Reuters",
    tag: "Parts",
    title: "Nissan recalls 40,000 vehicles over faulty steering component",
    summary: "The recall affects crossover models built between February and August 2026. Nissan says it will replace the steering column assembly free of charge and expects no supply disruption.",
    url: "https://example.com/nissan-recall"
  },
  {
    id: 6,
    time: "2026-09-16T21:00:00Z",
    source: "Financial Times",
    tag: "Tariffs",
    title: "Japan pushes back on US steel and aluminum tariff extension",
    summary: "Tokyo warned that extending Section 232 duties to Japanese steel and aluminum used in vehicles would breach past trade agreements and hike Japanese car prices in the US market.",
    url: "https://example.com/japan-steel"
  },
  {
    id: 7,
    time: "2026-09-16T16:45:00Z",
    source: "Nikkei Asia",
    tag: "Trade",
    title: "China auto parts exports to Europe fall as EU duties take effect",
    summary: "European imports of Chinese-made components dropped 12% in the first half of 2026, prompting Chinese suppliers to explore local production in Central Europe and Turkey.",
    url: "https://example.com/china-parts-exports"
  },
  {
    id: 8,
    time: "2026-09-16T08:10:00Z",
    source: "Automotive News",
    tag: "Parts",
    title: "Semiconductor shortage returns as AI demand crowds out auto chips",
    summary: "Some suppliers report 20-week lead times for automotive-grade microcontrollers again, as wafer capacity shifts to AI accelerators. Nissan says production guidance is unchanged for now.",
    url: "https://example.com/chip-shortage"
  }
];

// ---- Real data (from the backend) ------------------------------------------
// If fetch_news.py has run, it created news.js which sets window.NEWS.
// Use that; otherwise fall back to the mock stories above.
const NEWS = window.NEWS || MOCK_NEWS;

// ---- State -----------------------------------------------------------------
let activeTag = "all";
let query = "";

// ---- Rendering -------------------------------------------------------------
function slug(s) { return s.toLowerCase().replace(/[^a-z0-9]/g, ""); }

// Headlines come from the internet, so never put them into innerHTML raw.
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function formatTime(iso) {
  const d = new Date(iso);
  return d.toLocaleString("en-US", {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit", hour12: false
  });
}

function render() {
  const feed = document.getElementById("feed");
  const empty = document.getElementById("empty");
  const count = document.getElementById("count");
  feed.innerHTML = "";

  const items = NEWS
    .filter(n => activeTag === "all" || n.tag === activeTag)
    .filter(n => !query ||
      n.title.toLowerCase().includes(query) ||
      (n.source || "").toLowerCase().includes(query))
    .sort((a, b) => new Date(b.time) - new Date(a.time)); // newest first

  for (const n of items) {
    const li = document.createElement("li");
    li.className = "card";
    li.innerHTML = `
      <div class="meta">
        <span>${esc(formatTime(n.time))}</span>
        <span>·</span>
        <span>${esc(n.source)}</span>
        <span class="tag tag-${slug(n.tag)}">${esc(n.tag)}</span>
      </div>
      <h3>${esc(n.title)}</h3>
      <div class="summary">
        <a class="read" href="${esc(n.url)}" target="_blank" rel="noopener noreferrer">
          Read full article ↗
        </a>
        <span class="note">Headline and link only — the publisher may require a subscription.</span>
      </div>
    `;
    // Clicking the card expands it, but clicking the link must still open it.
    li.addEventListener("click", (e) => {
      if (e.target.closest("a")) return;
      li.classList.toggle("open");
    });
    feed.appendChild(li);
  }

  empty.classList.toggle("hidden", items.length > 0);
  count.textContent = items.length === 1
    ? "1 story"
    : `${items.length} stories`;
}

// ---- Controls --------------------------------------------------------------
document.getElementById("chips").addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  document.querySelectorAll(".chip").forEach(c => c.classList.remove("active"));
  chip.classList.add("active");
  activeTag = chip.dataset.tag;
  render();
});

document.getElementById("search").addEventListener("input", (e) => {
  query = e.target.value.trim().toLowerCase();
  render();
});

const isLive = !!window.NEWS;
if (isLive) {
  document.getElementById("badge").classList.add("hidden");
}

// Show when the data was FETCHED, not when this page was opened — otherwise
// a stale news.js looks freshly updated.
let stamp = "";
if (isLive && NEWS.length) {
  stamp = " · data fetched " + new Date(Math.max(...NEWS.map(n => new Date(n.time))))
    .toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
document.getElementById("updated-at").textContent =
  (isLive ? "Live feed" : "Mock feed — run python fetch_news.py for real news") + stamp;

// ---- Boot ------------------------------------------------------------------
render();