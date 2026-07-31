// Hash router (#/map, #/category, #/authority?muni_id=...), tab switching, top-bar search.
(function () {
  const views = {
    map: document.getElementById("view-map"),
    category: document.getElementById("view-category"),
    authority: document.getElementById("view-authority"),
  };
  const pages = { map: PageMap, category: PageCategory, authority: PageAuthority };
  const tabs = document.querySelectorAll(".tab");

  function parseHash() {
    const hash = window.location.hash || "#/map";
    const [pathPart, queryPart] = hash.replace(/^#\//, "").split("?");
    const page = pathPart || "map";
    const params = {};
    if (queryPart) {
      for (const pair of queryPart.split("&")) {
        const [k, v] = pair.split("=");
        params[decodeURIComponent(k)] = decodeURIComponent(v || "");
      }
    }
    return { page: pages[page] ? page : "map", params };
  }

  async function route() {
    const { page, params } = parseHash();
    for (const key of Object.keys(views)) {
      if (key === page) {
        await pages[key].show(views[key], params);
      } else {
        pages[key].hide(views[key]);
      }
    }
    tabs.forEach((t) => t.classList.toggle("active", t.dataset.tab === page));
  }

  window.addEventListener("hashchange", route);
  window.addEventListener("DOMContentLoaded", route);
})();
