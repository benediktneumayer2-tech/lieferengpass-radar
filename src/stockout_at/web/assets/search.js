/* Client-side search over search-index.json (product name, substance, PZN). Without JS the form
   submits to the A-Z substance list. No requests to third parties, nothing is stored. */
(function () {
  "use strict";
  var form = document.querySelector("form[data-search]");
  if (!form) return;
  var root = form.getAttribute("data-root") || "";
  var input = form.querySelector("input[type=search]");
  var out = document.getElementById("search-results");
  var index = null, loading = null, timer = null;

  function norm(s) {
    return (s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/ß/g, "ss");
  }
  function load() {
    if (!loading) {
      loading = fetch(root + "search-index.json").then(function (r) { return r.json(); }).then(function (d) {
        index = {
          p: d.p.map(function (x) { return { pzn: x[0], name: x[1], sub: x[2], path: x[3], status: x[4], key: norm(x[1] + " " + x[2]) }; }),
          s: d.s.map(function (x) { return { name: x[0], path: x[1], n: x[2], key: norm(x[0]) }; })
        };
      });
    }
    return loading;
  }
  function el(tag, text, cls) {
    var e = document.createElement(tag);
    if (text) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  }
  function link(href, text) { var a = el("a", text); a.href = root + href; return a; }

  function render(q) {
    out.textContent = "";
    var nq = norm(q).trim();
    if (nq.length < 2) return;
    var terms = nq.split(/\s+/), digits = /^\d+$/.test(nq);
    function hit(key) { return terms.every(function (t) { return key.indexOf(t) !== -1; }); }
    var subs = digits ? [] : index.s.filter(function (s) { return hit(s.key); });
    var pkgs = index.p.filter(function (p) { return digits ? p.pzn.indexOf(nq) === 0 : hit(p.key); });
    subs.sort(function (a, b) { return (a.key.indexOf(terms[0]) === 0 ? 0 : 1) - (b.key.indexOf(terms[0]) === 0 ? 0 : 1) || a.name.localeCompare(b.name); });
    pkgs.sort(function (a, b) { return (a.status ? 0 : 1) - (b.status ? 0 : 1) || a.name.localeCompare(b.name); });
    if (!subs.length && !pkgs.length) {
      var p = el("p", "Keine Treffer für „" + q.trim() + "“. ");
      p.appendChild(link("wirkstoffe/", "Zur Wirkstoffliste A–Z"));
      out.appendChild(p);
      return;
    }
    if (subs.length) {
      out.appendChild(el("h3", "Wirkstoffe (" + subs.length + ")"));
      var ul = el("ul");
      subs.slice(0, 8).forEach(function (s) {
        var li = el("li"); li.appendChild(link(s.path, s.name)); li.appendChild(el("span", " · " + s.n + " Packungen", "small")); ul.appendChild(li);
      });
      out.appendChild(ul);
    }
    if (pkgs.length) {
      out.appendChild(el("h3", "Packungen (" + pkgs.length + (pkgs.length > 25 ? ", die ersten 25" : "") + ")"));
      var ul2 = el("ul");
      pkgs.slice(0, 25).forEach(function (p) {
        var li = el("li"); li.appendChild(link(p.path, p.name));
        li.appendChild(el("span", (p.pzn ? " · PZN " + p.pzn : "") + " · " + (p.status || "nicht mehr gelistet"), "small"));
        ul2.appendChild(li);
      });
      out.appendChild(ul2);
    }
  }
  function run() {
    var q = input.value;
    load().then(function () { render(q); }, function () {
      out.textContent = "";
      var p = el("p", "Suchindex konnte nicht geladen werden. ");
      p.appendChild(link("wirkstoffe/", "Zur Wirkstoffliste A–Z"));
      out.appendChild(p);
    });
  }
  input.addEventListener("focus", load, { once: true });
  input.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(run, 120); });
  form.addEventListener("submit", function (e) { e.preventDefault(); run(); });
  var initial = new URLSearchParams(location.search).get("q");
  if (initial) { input.value = initial; run(); }
})();
