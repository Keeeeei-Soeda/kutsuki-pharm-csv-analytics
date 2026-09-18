/* サイドバー: モバイルドロワー + ページ内目次スクロールスパイ */
(function () {
  "use strict";

  var body = document.body;
  var toggle = document.querySelector(".nav-toggle");
  var overlay = document.querySelector(".nav-overlay");
  var sidebar = document.getElementById("sidebar");

  function setOpen(open) {
    body.classList.toggle("nav-open", open);
    if (toggle) {
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.setAttribute("aria-label", open ? "ナビゲーションを閉じる" : "ナビゲーションを開く");
    }
    if (overlay) { overlay.hidden = !open; }
    if (open && sidebar) {
      var first = sidebar.querySelector("a");
      if (first) { first.focus(); }
    }
  }

  if (toggle) {
    toggle.addEventListener("click", function () {
      setOpen(!body.classList.contains("nav-open"));
    });
  }
  if (overlay) {
    overlay.addEventListener("click", function () { setOpen(false); });
  }
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && body.classList.contains("nav-open")) {
      setOpen(false);
      if (toggle) { toggle.focus(); }
    }
  });
  // ドロワー内のリンクを踏んだら閉じる
  if (sidebar) {
    sidebar.addEventListener("click", function (e) {
      var a = e.target.closest ? e.target.closest("a") : null;
      if (a && body.classList.contains("nav-open")) { setOpen(false); }
    });
  }
  // 900px 以上へ戻ったら状態をリセット
  if (window.matchMedia) {
    var mq = window.matchMedia("(min-width: 900px)");
    var onChange = function (ev) { if (ev.matches) { setOpen(false); } };
    if (mq.addEventListener) { mq.addEventListener("change", onChange); }
    else if (mq.addListener) { mq.addListener(onChange); }
  }

  /* --- スクロールスパイ --- */
  var tocLinks = Array.prototype.slice.call(
    document.querySelectorAll(".sb-toc a[href^='#']")
  );
  if (!tocLinks.length || !("IntersectionObserver" in window)) { return; }

  var byId = {};
  var targets = [];
  tocLinks.forEach(function (link) {
    var id = decodeURIComponent(link.getAttribute("href").slice(1));
    var el = document.getElementById(id);
    if (el) { byId[id] = link; targets.push(el); }
  });
  if (!targets.length) { return; }

  var visible = new Set();

  function highlight(id) {
    tocLinks.forEach(function (l) { l.classList.remove("is-current"); });
    var link = byId[id];
    if (link) {
      link.classList.add("is-current");
      // サイドバー内で見切れていたらスクロールして見せる
      var box = link.getBoundingClientRect();
      var host = sidebar ? sidebar.getBoundingClientRect() : null;
      if (host && (box.top < host.top || box.bottom > host.bottom)) {
        link.scrollIntoView({ block: "nearest" });
      }
    }
  }

  function pickTop() {
    var best = null;
    targets.forEach(function (el) {
      if (!visible.has(el.id)) { return; }
      if (!best || el.getBoundingClientRect().top < best.getBoundingClientRect().top) {
        best = el;
      }
    });
    return best;
  }

  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) { visible.add(entry.target.id); }
      else { visible.delete(entry.target.id); }
    });
    var top = pickTop();
    if (top) { highlight(top.id); }
  }, { rootMargin: "-20% 0px -70% 0px", threshold: 0 });

  targets.forEach(function (el) { observer.observe(el); });

  // どのセクションも帯に入っていない位置（最上部・最下部）向けのフォールバック
  function fallback() {
    if (visible.size) { return; }
    var current = targets[0];
    for (var i = 0; i < targets.length; i++) {
      if (targets[i].getBoundingClientRect().top - window.innerHeight * 0.25 <= 0) {
        current = targets[i];
      }
    }
    if (current) { highlight(current.id); }
  }
  window.addEventListener("scroll", fallback, { passive: true });
  fallback();
}());
