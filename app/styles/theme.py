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


def inject_locale_toggle(locale):
    # type: (str) -> None
    """Mount an EN/CN button fixed in the top-right banner.

    Clicking toggles the `locale` query param so Streamlit reruns with the
    new language. Safe to call on every rerun — the button is upserted by id.
    """
    import streamlit.components.v1 as components

    current = "zh" if locale == "zh" else "en"
    label = "CN" if current == "zh" else "EN"
    current_js = json.dumps(current)
    label_js = json.dumps(label)

    components.html(
        """
<!DOCTYPE html>
<html><head></head><body>
<script>
(function () {
  const doc = window.parent.document;
  const current = """
        + current_js
        + """;
  const label = """
        + label_js
        + """;
  const btnId = "pa-locale-toggle";

  function mount() {
    // Prefer attaching inside the header toolbar area; fall back to body.
    const header = doc.querySelector('header[data-testid="stHeader"]');
    const host = header || doc.body;
    if (!host) return false;

    let btn = doc.getElementById(btnId);
    if (!btn) {
      btn = doc.createElement("button");
      btn.id = btnId;
      btn.type = "button";
      btn.className = "pa-locale-toggle";
      btn.addEventListener("click", function () {
        const next = btn.dataset.locale === "en" ? "zh" : "en";
        const url = new URL(window.parent.location.href);
        url.searchParams.set("locale", next);
        window.parent.location.href = url.toString();
      });
      host.appendChild(btn);
    } else if (btn.parentElement !== host) {
      host.appendChild(btn);
    }

    btn.dataset.locale = current;
    btn.textContent = label;
    btn.setAttribute("aria-label", "Language");
    btn.title = "Language";
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
        """,
        height=0,
        scrolling=False,
    )
