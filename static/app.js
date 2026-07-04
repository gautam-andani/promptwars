/* Side Quest — frontend logic (loaded with `defer`, so the DOM is ready). */
"use strict";

const MONTHS = ["January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December"];
const LOADING_MESSAGES = [
  "Consulting local experts…",
  "Searching festivals…",
  "Comparing recommendations…",
  "Writing your story…",
  "Pinning the map…",
];
const PIN_COLORS = {
  attraction: "#3b82f6",
  hidden_gem: "#a855f7",
  heritage: "#f59e0b",
  experience: "#14b8a6",
  nearby: "#22c55e",
};
const TYPE_BADGES = {
  attraction: { label: "Attraction", classes: "bg-blue-500/20 text-blue-200 ring-1 ring-blue-400/40" },
  hidden_gem: { label: "Hidden gem", classes: "bg-purple-500/20 text-purple-200 ring-1 ring-purple-400/40" },
  heritage:   { label: "Heritage",   classes: "bg-amber-500/20 text-amber-200 ring-1 ring-amber-400/40" },
  experience: { label: "Experience", classes: "bg-teal-500/20 text-teal-200 ring-1 ring-teal-400/40" },
};
const PLACEHOLDER_EMOJI = {
  attraction: ["🌆", "🗼", "🎡", "🌉"],
  hidden_gem: ["💎", "🗝️", "✨", "🕯️"],
  heritage:   ["🏛️", "🏰", "⛩️", "🕌"],
  experience: ["🎭", "🍜", "🎪", "🛶"],
};
const PLACEHOLDER_GRADIENTS = [
  "linear-gradient(135deg, rgba(217,70,239,.55), rgba(79,70,229,.75))",
  "linear-gradient(135deg, rgba(251,191,36,.55), rgba(225,29,72,.7))",
  "linear-gradient(135deg, rgba(45,212,191,.5), rgba(2,132,199,.75))",
  "linear-gradient(135deg, rgba(167,139,250,.55), rgba(107,33,168,.75))",
  "linear-gradient(135deg, rgba(52,211,153,.5), rgba(8,145,178,.75))",
  "linear-gradient(135deg, rgba(251,146,60,.55), rgba(190,24,93,.7))",
];
const MAX_INTERESTS = 5;

const form = document.getElementById("discover-form");
const submitBtn = document.getElementById("submit-btn");
const monthSelect = document.getElementById("month");
const radiusInput = document.getElementById("radius");
const radiusLabel = document.getElementById("radius-label");
const chipsContainer = document.getElementById("chips");
const loadingEl = document.getElementById("loading");
const loadingMessageEl = document.getElementById("loading-message");
const resultsEl = document.getElementById("results");
const errorBanner = document.getElementById("error-banner");

let map = null;
let markerLayer = null;
let loadingTimer = null;

const revealObserver = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (entry.isIntersecting) {
      entry.target.classList.add("on");
      revealObserver.unobserve(entry.target);
    }
  });
}, { threshold: 0.12 });

// --- Form setup -----------------------------------------------------------
MONTHS.forEach((month) => {
  const option = document.createElement("option");
  option.value = month;
  option.textContent = month;
  monthSelect.appendChild(option);
});
monthSelect.value = MONTHS[new Date().getMonth()];

radiusInput.addEventListener("input", () => {
  radiusLabel.textContent = `${radiusInput.value} km`;
});

chipsContainer.addEventListener("click", (event) => {
  const chip = event.target.closest(".chip");
  if (!chip) return;
  const pressed = chip.getAttribute("aria-pressed") === "true";
  const activeCount = chipsContainer.querySelectorAll('.chip[aria-pressed="true"]').length;
  if (!pressed && activeCount >= MAX_INTERESTS) return;
  chip.setAttribute("aria-pressed", String(!pressed));
});

// --- Helpers --------------------------------------------------------------
function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function hashCode(text) {
  let hash = 0;
  for (const ch of String(text)) hash = (hash * 31 + ch.codePointAt(0)) >>> 0;
  return hash;
}

function setLoading(active) {
  submitBtn.disabled = active;
  loadingEl.classList.toggle("hidden", !active);
  if (active) {
    resultsEl.classList.add("hidden");
    errorBanner.classList.add("hidden");
    let index = 0;
    loadingMessageEl.textContent = LOADING_MESSAGES[0];
    loadingTimer = setInterval(() => {
      index = (index + 1) % LOADING_MESSAGES.length;
      loadingMessageEl.textContent = LOADING_MESSAGES[index];
    }, 2200);
  } else if (loadingTimer) {
    clearInterval(loadingTimer);
    loadingTimer = null;
  }
}

function showError(message) {
  errorBanner.textContent = message;
  errorBanner.classList.remove("hidden");
}

// --- Rendering ------------------------------------------------------------
function renderMap(data) {
  if (!map) {
    map = L.map("map", { scrollWheelZoom: false });
    // Esri World Street Map: free, no API key, and labels major places in
    // English/romanized text (default OSM tiles use local-language names).
    L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}", {
      maxZoom: 19,
      attribution: 'Tiles &copy; Esri &mdash; Sources: Esri, HERE, Garmin, &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    markerLayer = L.layerGroup().addTo(map);
  }
  markerLayer.clearLayers();
  const bounds = [];

  (data.attractions || []).forEach((place) => {
    if (typeof place.lat !== "number" || typeof place.lon !== "number") return;
    const color = PIN_COLORS[place.type] || PIN_COLORS.attraction;
    L.circleMarker([place.lat, place.lon], {
      radius: 9, color: "#ffffff", weight: 2, fillColor: color, fillOpacity: 0.95,
    }).bindPopup(
      `<strong>${esc(place.name)}</strong><br><span class="text-sm">${esc(place.why_this_month)}</span>`
    ).addTo(markerLayer);
    bounds.push([place.lat, place.lon]);
  });

  (data.nearby_recommendations || []).forEach((city) => {
    if (typeof city.lat !== "number" || typeof city.lon !== "number") return;
    L.circleMarker([city.lat, city.lon], {
      radius: 10, color: "#ffffff", weight: 2, fillColor: PIN_COLORS.nearby, fillOpacity: 0.95,
    }).bindPopup(
      `<strong>${esc(city.city)}</strong><br><span class="text-sm">${esc(city.distance_km)} km away — ${esc((city.highlights || []).join(", "))}</span>`
    ).addTo(markerLayer);
    bounds.push([city.lat, city.lon]);
  });

  setTimeout(() => {
    map.invalidateSize();
    if (bounds.length) map.fitBounds(bounds, { padding: [36, 36], maxZoom: 12 });
    else map.setView([20, 0], 2);
  }, 60);
}

function placeholderMedia(place) {
  const hash = hashCode(place.name);
  const gradient = PLACEHOLDER_GRADIENTS[hash % PLACEHOLDER_GRADIENTS.length];
  const emojiSet = PLACEHOLDER_EMOJI[place.type] || PLACEHOLDER_EMOJI.attraction;
  const emoji = emojiSet[hash % emojiSet.length];
  const initial = esc((place.name || "?").trim().charAt(0).toUpperCase());
  return `
    <div class="relative h-44 w-full flex items-center justify-center overflow-hidden" style="background:${gradient}">
      <span class="absolute -right-3 -bottom-7 text-[7rem] font-black text-white/10 select-none" aria-hidden="true">${initial}</span>
      <span class="absolute left-3 top-3 text-white/25 text-xl" aria-hidden="true">✦</span>
      <span class="text-6xl drop-shadow-[0_10px_16px_rgba(0,0,0,.45)]">${emoji}</span>
    </div>`;
}

function attractionCard(place, index) {
  const badge = TYPE_BADGES[place.type] || TYPE_BADGES.attraction;
  const media = place.photo_url
    ? `<img src="${esc(place.photo_url)}" alt="${esc(place.name)}" loading="lazy"
            class="h-44 w-full object-cover"
            onerror="this.style.display='none';this.nextElementSibling.style.display='block'">
       <div style="display:none">${placeholderMedia(place)}</div>`
    : placeholderMedia(place);
  return `
    <article class="glass glow-card fade-up overflow-hidden rounded-2xl" style="animation-delay:${index * 90}ms">
      ${media}
      <div class="p-4 space-y-2">
        <div class="flex items-start justify-between gap-2">
          <h4 class="font-bold text-slate-100 leading-snug">${esc(place.name)}</h4>
          <span class="shrink-0 rounded-full px-2.5 py-0.5 text-xs font-semibold ${badge.classes}">${badge.label}</span>
        </div>
        <p class="text-sm text-slate-300">${esc(place.why_this_month)}</p>
        ${place.authenticity_tip
          ? `<p class="rounded-lg bg-amber-400/10 ring-1 ring-amber-300/30 px-3 py-2 text-xs text-amber-200">💡 ${esc(place.authenticity_tip)}</p>`
          : ""}
      </div>
    </article>`;
}

function renderResults(data) {
  document.getElementById("results-title").textContent =
    `${data.destination} in ${data.month}`;
  document.getElementById("results-subtitle").textContent = data.search_used
    ? "Cross-checked with live web results."
    : "Curated by multiple AI travel guides for your month.";
  document.getElementById("degraded-banner").classList.toggle("hidden", !data.degraded);

  document.getElementById("attractions-grid").innerHTML =
    (data.attractions || []).map(attractionCard).join("") ||
    `<p class="text-slate-400">No attractions found.</p>`;

  const stories = data.stories || [];
  document.getElementById("stories-section").classList.toggle("hidden", stories.length === 0);
  document.getElementById("stories-list").innerHTML = stories.map((story) => `
    <div class="gradient-border">
      <article class="story-card rounded-[calc(1.25rem-1px)] bg-[#141a33]/95 p-6 sm:p-7">
        <h4 class="text-xl font-bold text-amber-300">${esc(story.place)}</h4>
        <p class="mt-3 leading-relaxed text-slate-200">${esc(story.narrative)}</p>
      </article>
    </div>`).join("");

  const events = data.local_events || [];
  document.getElementById("events-section").classList.toggle("hidden", events.length === 0);
  document.getElementById("events-list").innerHTML = events.map((ev) => `
    <li class="glass glow-card rounded-xl p-4">
      <div class="flex flex-wrap items-baseline justify-between gap-2">
        <span class="font-semibold text-slate-100">🎉 ${esc(ev.name)}</span>
        <span class="text-xs font-medium text-fuchsia-300">${esc(ev.dates)}</span>
      </div>
      <p class="mt-1 text-sm text-slate-300">${esc(ev.description)}</p>
    </li>`).join("");

  const seasons = data.seasonal_alternatives || [];
  document.getElementById("seasonal-section").classList.toggle("hidden", seasons.length === 0);
  document.getElementById("seasonal-list").innerHTML = seasons.map((season) => `
    <details class="glass rounded-xl p-4">
      <summary class="flex items-center justify-between font-semibold text-slate-100">
        <span>🍂 ${esc(season.season)}</span>
        <span class="accordion-arrow text-amber-300" aria-hidden="true">▾</span>
      </summary>
      <p class="mt-2 text-sm text-slate-300">${esc(season.why)}</p>
      ${(season.highlights || []).length
        ? `<ul class="mt-2 list-disc pl-5 text-sm text-slate-300">
             ${(season.highlights || []).map((h) => `<li>${esc(h)}</li>`).join("")}
           </ul>`
        : ""}
    </details>`).join("");

  const nearby = data.nearby_recommendations || [];
  document.getElementById("nearby-section").classList.toggle("hidden", nearby.length === 0);
  document.getElementById("nearby-list").innerHTML = nearby.map((city, index) => `
    <article class="glass glow-card fade-up w-64 shrink-0 rounded-2xl p-4" style="animation-delay:${index * 90}ms">
      <div class="flex items-baseline justify-between gap-2">
        <h4 class="font-bold text-slate-100">🚗 ${esc(city.city)}</h4>
        <span class="rounded-full bg-green-400/15 ring-1 ring-green-300/40 px-2 py-0.5 text-xs font-semibold text-green-300">${esc(city.distance_km)} km</span>
      </div>
      <ul class="mt-2 list-disc pl-5 text-sm text-slate-300">
        ${(city.highlights || []).map((h) => `<li>${esc(h)}</li>`).join("")}
      </ul>
    </article>`).join("");

  resultsEl.classList.remove("hidden");
  resultsEl.querySelectorAll(".reveal").forEach((el) => {
    el.classList.remove("on");
    revealObserver.observe(el);
  });
  renderMap(data);
  resultsEl.scrollIntoView({ behavior: "smooth", block: "start" });
}

// --- Submit ---------------------------------------------------------------
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const interests = Array.from(
    chipsContainer.querySelectorAll('.chip[aria-pressed="true"]')
  ).map((chip) => chip.dataset.interest);
  const body = {
    destination: document.getElementById("destination").value.trim(),
    travel_month: monthSelect.value,
    extra_radius_km: Number(radiusInput.value),
    interests,
  };

  setLoading(true);
  try {
    const response = await fetch("/api/discover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (response.status === 429) {
      throw new Error("You're questing fast! Please wait a minute before searching again.");
    }
    if (response.status === 502) {
      throw new Error("Our AI guild is unavailable right now. Please try again shortly.");
    }
    if (response.status === 422) {
      throw new Error("Please check your inputs — destination and month look invalid.");
    }
    if (!response.ok) {
      throw new Error("Something went wrong. Please try again.");
    }
    renderResults(await response.json());
  } catch (err) {
    showError(err instanceof Error && err.message
      ? err.message
      : "Something went wrong. Please try again.");
  } finally {
    setLoading(false);
  }
});
