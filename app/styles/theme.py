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
})();
</script>
</body></html>
        """,
        height=0,
        scrolling=False,
    )
