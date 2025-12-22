// MathJax configuration for MkDocs
// This must be loaded BEFORE the MathJax script (mkdocs.yml lists it first)
window.MathJax = {
  tex: {
    inlineMath: [['$', '$'], ['\\(', '\\)']],
    displayMath: [['$$', '$$'], ['\\[', '\\]']],
    // optionally enable other packages
    packages: {'[+]': ['ams']}
  },
  options: {
    // skip rendering inside code/pre
    skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']
  }
};