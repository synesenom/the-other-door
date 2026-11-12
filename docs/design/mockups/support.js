// Minimal static renderer for the canvas's .dc.html mockups (screenshots only).
window.DCLogic = class { constructor(p) { this.props = p || {}; this.state = {}; } setState(s) { Object.assign(this.state, s); } };
function lookup(path, scope) {
  path = path.replace(/[{}]/g, '').trim();
  if (path === 'true') return true; if (path === 'false') return false;
  return path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), scope);
}
function interp(str, scope) { return str.replace(/\{\{\s*([^}]+?)\s*\}\}/g, (_, p) => { const v = lookup(p, scope); return v == null ? '' : String(v); }); }
function expand(node, scope) {
  for (const child of [...node.childNodes]) {
    if (child.nodeType === 3) { if (child.nodeValue.includes('{{')) child.nodeValue = interp(child.nodeValue, scope); continue; }
    if (child.nodeType !== 1) continue;
    const tag = child.tagName.toLowerCase();
    if (tag === 'sc-for') {
      const list = lookup(child.getAttribute('list'), scope) || [];
      const as = child.getAttribute('as'); const frag = document.createDocumentFragment();
      list.forEach((item, i) => { const c = child.cloneNode(true); expand(c, Object.assign(Object.create(scope), { [as]: item, $index: i })); while (c.firstChild) frag.appendChild(c.firstChild); });
      child.replaceWith(frag); continue;
    }
    if (tag === 'sc-if') { if (lookup(child.getAttribute('value'), scope)) { expand(child, scope); child.replaceWith(...child.childNodes); } else child.remove(); continue; }
    for (const a of [...child.attributes]) {
      if (!a.value.includes('{{')) continue;
      if (/^on/i.test(a.name)) child.removeAttribute(a.name); else child.setAttribute(a.name, interp(a.value, scope));
    }
    expand(child, scope);
  }
}
document.addEventListener('DOMContentLoaded', () => {
  const script = document.querySelector('script[data-dc-script]');
  const dp = JSON.parse(script.getAttribute('data-props') || '{}'); const props = {};
  for (const k in dp) if (dp[k] && dp[k].default !== undefined) props[k] = dp[k].default;
  // ?dark=true etc. overrides a declared prop, so one mockup renders in several variants.
  for (const [k, v] of new URLSearchParams(location.search)) { try { props[k] = JSON.parse(v); } catch (e) { props[k] = v; } }
  const Component = new Function('DCLogic', script.textContent + '; return Component;')(window.DCLogic);
  const vals = new Component(props).renderVals();
  const root = document.querySelector('x-dc');
  const helmet = root.querySelector('helmet');
  if (helmet) { document.head.append(...helmet.childNodes); helmet.remove(); }
  expand(root, vals); root.replaceWith(...root.childNodes);
  document.documentElement.dataset.ready = '1';
});
