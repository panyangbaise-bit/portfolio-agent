"""Cyberpunk theme loader for Streamlit."""

import json
from pathlib import Path

CSS_PATH = Path(__file__).parent / "cyberpunk.css"

FONT_IMPORT = (
    "@import url('https://fonts.googleapis.com/css2?"
    "family=Orbitron:wght@500;700&family=Share+Tech+Mono&display=swap');"
)

# Hide zero-height theme iframe hosts so they never consume layout.
_HOST_HIDE = """
iframe[title="streamlit_html"] {
  display: none !important;
  height: 0 !important;
  width: 0 !important;
  position: absolute !important;
  border: 0 !important;
}
div[data-testid="stElementContainer"]:has(iframe[height="0"]),
div[data-testid="stElementContainer"]:has(iframe[style*="height: 0"]),
.element-container:has(iframe[height="0"]) {
  display: none !important;
  height: 0 !important;
  min-height: 0 !important;
  margin: 0 !important;
  padding: 0 !important;
  border: none !important;
  position: absolute !important;
  overflow: hidden !important;
  pointer-events: none !important;
}
"""


def load_cyberpunk_css():
    # type: () -> str
    if not CSS_PATH.is_file():
        return ""
    return CSS_PATH.read_text(encoding="utf-8")


def build_theme_css(css):
    # type: (str) -> str
    """Full CSS string injected into the parent document <head>."""
    return FONT_IMPORT + "\n" + _HOST_HIDE + "\n" + css


def build_theme_html(css):
    # type: (str) -> str
    """Legacy helper kept for tests — returns a style tag wrapper."""
    return "<style>\n" + build_theme_css(css) + "\n</style>"


def build_theme_markdown(css):
    # type: (str) -> str
    return build_theme_html(css)


def _hide_iframe_host_js():
    # type: () -> str
    """JS snippet that collapses the components.html host node."""
    return """
  const frame = window.frameElement;
  if (frame) {
    frame.style.setProperty("display", "none", "important");
    frame.style.setProperty("height", "0", "important");
    frame.style.setProperty("width", "0", "important");
    frame.style.setProperty("position", "absolute", "important");
    const host =
      frame.closest('[data-testid="stElementContainer"]') ||
      frame.closest(".element-container") ||
      frame.parentElement;
    if (host) {
      host.style.setProperty("display", "none", "important");
      host.style.setProperty("height", "0", "important");
      host.style.setProperty("min-height", "0", "important");
      host.style.setProperty("margin", "0", "important");
      host.style.setProperty("padding", "0", "important");
      host.style.setProperty("border", "none", "important");
      host.style.setProperty("position", "absolute", "important");
      host.style.setProperty("overflow", "hidden", "important");
      host.style.setProperty("pointer-events", "none", "important");
    }
  }
"""


def inject_cyberpunk_theme():
    # type: () -> None
    """Inject theme CSS into the parent page without taking layout space.

    st.html / st.markdown both create a visible layout slot. We inject via a
    height-0 component iframe and write <style> into window.parent.document.head,
    then hide the iframe host from the parent DOM.
    """
    import logging

    import streamlit.components.v1 as components

    css = load_cyberpunk_css()
    if not css:
        logging.getLogger(__name__).warning("cyberpunk.css missing; theme skipped")
        return

    payload = json.dumps(build_theme_css(css))
    components.html(
        """
<!DOCTYPE html>
<html><head></head><body>
<script>
(function () {
  const css = """
        + payload
        + """;
  const doc = window.parent.document;
  const id = "portfolio-agent-cyberpunk-theme";
  let el = doc.getElementById(id);
  if (!el) {
    el = doc.createElement("style");
    el.id = id;
    doc.head.appendChild(el);
  }
  el.textContent = css;
"""
        + _hide_iframe_host_js()
        + """
})();
</script>
</body></html>
        """,
        height=0,
        scrolling=False,
    )


def build_locale_toggle_html(locale):
    # type: (str) -> str
    """HTML for the EN/CN toggle component iframe.

    The toggle is an ``<a href="?locale=...">`` upserted into the parent
    ``document.body``. It must be a real link, NOT a script-driven
    navigation: Streamlit component iframes are sandboxed without
    ``allow-top-navigation``, so ``window.parent.location.assign(...)``
    from the iframe realm throws SecurityError. A parent-document anchor
    navigates in the parent's own context and needs no such permission.

    Mounted on ``document.body`` (not ``stHeader``): with
    ``toolbarMode=minimal`` Streamlit sets ``pointer-events: none`` on the
    transparent header, which would block clicks on a header-mounted child.
    """
    current = "zh" if locale == "zh" else "en"
    nxt = "en" if current == "zh" else "zh"
    label = "CN" if current == "zh" else "EN"

    return (
        """
<!DOCTYPE html>
<html><head></head><body>
<script>
(function () {
  const doc = window.parent.document;
  const current = """
        + json.dumps(current)
        + """;
  const next = """
        + json.dumps(nxt)
        + """;
  const label = """
        + json.dumps(label)
        + """;
  const elId = "pa-locale-toggle";

  function mount() {
    const host = doc.body;
    if (!host) return false;

    let el = doc.getElementById(elId);
    if (el && el.tagName !== "A") {
      el.remove();
      el = null;
    }
    if (!el) {
      el = doc.createElement("a");
      el.id = elId;
      el.className = "pa-locale-toggle";
      host.appendChild(el);
    } else if (el.parentElement !== host) {
      host.appendChild(el);
    }

    const url = new URL(window.parent.location.href);
    url.searchParams.set("locale", next);
    el.setAttribute("href", url.toString());
    el.dataset.locale = current;
    el.textContent = label;
    el.setAttribute("aria-label", "Language");
    el.title = "Language";
    return true;
  }

  if (!mount()) {
    let tries = 0;
    const timer = setInterval(function () {
      tries += 1;
      if (mount() || tries > 20) clearInterval(timer);
    }, 100);
  }
"""
        + _hide_iframe_host_js()
        + """
})();
</script>
</body></html>
"""
    )


def inject_locale_toggle(locale):
    # type: (str) -> None
    """Mount the EN/CN toggle link in the top-right banner.

    Safe to call on every rerun — the anchor is upserted by id and its href
    always points at the opposite locale.
    """
    import streamlit.components.v1 as components

    components.html(build_locale_toggle_html(locale), height=0, scrolling=False)
