# API Reference

WikiMind exposes a REST API via the FastAPI gateway running on port 7842. The interactive documentation below is generated from the [OpenAPI specification](openapi.yaml).

!!! tip "Interactive docs"
    When running locally, FastAPI also serves interactive docs at [localhost:7842/docs](http://localhost:7842/docs) (Swagger UI) and [localhost:7842/redoc](http://localhost:7842/redoc) (ReDoc).

<div id="redoc-container"></div>

<link href="https://fonts.googleapis.com/css?family=Inter:400,500,600,700" rel="stylesheet">
<script src="https://cdn.redoc.ly/redoc/latest/bundles/redoc.standalone.js"></script>
<script>
  Redoc.init('openapi.yaml', {
    scrollYOffset: 64,
    theme: {
      colors: {
        primary: { main: '#4673ad' },
      },
      typography: {
        fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, sans-serif',
        fontSize: '14px',
        headings: { fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, sans-serif' },
        code: { fontFamily: 'JetBrains Mono, monospace', fontSize: '13px' },
      },
      sidebar: {
        width: '260px',
      },
    },
    hideDownloadButton: false,
    expandResponses: '200,201',
    pathInMiddlePanel: true,
    nativeScrollbars: true,
  }, document.getElementById('redoc-container'));
</script>

<style>
  /* Ensure Redoc integrates with Material theme */
  #redoc-container { margin: 0 -1.2rem; }
  [data-md-color-scheme="slate"] #redoc-container { filter: invert(0.88) hue-rotate(180deg); }
  [data-md-color-scheme="slate"] #redoc-container img { filter: invert(1) hue-rotate(180deg); }
</style>
