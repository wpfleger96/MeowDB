/* ============================================================
   views/algorithm.js — renders docs/algorithm.md (markdown + math)

   Renders the segment-detection and uniqueness-scoring write-up
   live in the browser:
   fetch the markdown, parse it with markdown-it, and typeset its
   LaTeX with MathJax (SVG output). The markdown source is the single
   source of truth — editing docs/algorithm.md is all that's required.
   ============================================================ */

/**
 * Render markdown that contains LaTeX math, without the markdown parser
 * mangling backslashes / underscores / asterisks inside the math.
 *
 * Math spans are stashed as opaque placeholders BEFORE markdown runs, then
 * restored afterwards as MathJax delimiters (\[..\] block, \(..\) inline).
 * Code spans/blocks are stashed too so a `$` inside code is never treated
 * as math. TeX is HTML-escaped on restore because formulas here contain
 * literal `<`, `>` and `&` (e.g. `l_m \leq k < c_m`, the `&` column
 * separators in `\begin{cases}`) which would otherwise corrupt innerHTML.
 */
function renderMarkdownWithMath(src) {
  const math = [];
  const code = [];

  // Tokens are letter-bounded (…MJX) so the numeric index stays unambiguous
  // and no surrounding whitespace is required — markdown-it trims paragraph
  // whitespace, which would strip space-delimited placeholders.
  const stashMath = (tex, display) => {
    const token = `MJXMATH${math.length}MJX`;
    math.push({ tex: tex.trim(), display });
    return token;
  };
  const stashCode = (m) => {
    const token = `MJXCODE${code.length}MJX`;
    code.push(m);
    return token;
  };

  // 1. Protect code (fenced blocks, then inline spans) so $ inside code is safe.
  let text = src
    .replace(/```[\s\S]*?```/g, stashCode)
    .replace(/`[^`\n]*`/g, stashCode);

  // 2. Extract block math ($$..$$) first, then inline math ($..$).
  text = text
    .replace(/\$\$([\s\S]+?)\$\$/g, (_, tex) => stashMath(tex, true))
    .replace(/\$((?:\\.|[^$\\\n])+?)\$/g, (_, tex) => stashMath(tex, false));

  // 3. Restore code so markdown-it renders it as normal code.
  text = text.replace(/MJXCODE(\d+)MJX/g, (_, i) => code[+i]);

  // 4. Render markdown.
  const html = window.markdownit({ html: false, linkify: true, typographer: false }).render(text);

  // 5. Restore math as (HTML-escaped) MathJax delimiters.
  return html.replace(/MJXMATH(\d+)MJX/g, (_, i) => {
    const { tex, display } = math[+i];
    const esc = tex.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return display ? `\\[${esc}\\]` : `\\(${esc}\\)`;
  });
}

// Keyed by src. Caching the promise (not checking the DOM) makes concurrent
// callers await the same in-flight load instead of proceeding before the
// script has executed; a failed entry is evicted so Retry re-attempts.
const _scriptPromises = {};

function _loadScript(src) {
  if (!_scriptPromises[src]) {
    _scriptPromises[src] = new Promise((resolve, reject) => {
      const el = document.createElement('script');
      el.src = src;
      el.onload = resolve;
      el.onerror = () => {
        delete _scriptPromises[src];
        el.remove();
        reject(new Error(`Failed to load ${src}`));
      };
      document.head.appendChild(el);
    });
  }
  return _scriptPromises[src];
}

function algorithmView() {
  return {
    // No init(): Alpine auto-calls init() on x-data components, which would
    // download the ~2.2MB vendors on every route. The container's x-effect
    // triggers load() only when this view is active.
    isLoading: false,
    error: null,
    rendered: false,

    async load() {
      if (this.rendered) return; // static content — render once
      this.isLoading = true;
      this.error = null;
      try {
        await this._loadDeps();
        const res = await fetch('/static/docs/algorithm.md');
        if (!res.ok) throw new Error(`Failed to load doc (${res.status})`);
        const src = await res.text();

        this.$refs.body.innerHTML = renderMarkdownWithMath(src);

        // Wait for MathJax startup, then typeset only our container.
        if (window.MathJax.startup?.promise) {
          await window.MathJax.startup.promise;
        }
        await window.MathJax.typesetPromise([this.$refs.body]);

        this.rendered = true;
      } catch (err) {
        this.error = err.message || 'Failed to load algorithm doc';
      } finally {
        this.isLoading = false;
      }
    },

    async _loadDeps() {
      // window.MathJax exists from the inline config before tex-svg.js loads;
      // typesetPromise appears only after the library fully initializes.
      if (window.markdownit && window.MathJax?.typesetPromise) return;
      // $root (the x-data container carrying the data-* URLs), NOT $el:
      // $el is the *current* element, e.g. the Retry button when load()
      // runs from its @click.
      await Promise.all([
        _loadScript(this.$root.dataset.texSvgSrc),
        _loadScript(this.$root.dataset.markdownItSrc),
      ]);
    },
  };
}
