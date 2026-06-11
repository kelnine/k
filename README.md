# Terminal Financiero IA

Terminal financiero interactivo construido a partir de los **4 Prompts Maestros** de la guía
*Terminal Financiero IA*. Cada módulo es un archivo HTML autónomo (HTML + CSS + JavaScript,
sin dependencias externas) con tema oscuro profesional y datos simulados realistas.

## Módulos

| Archivo | Módulo | Descripción |
|---|---|---|
| `index.html` | 📊 Dashboard de Mercado | Índices principales (S&P 500, NASDAQ, Dow, Russell 2000, VIX, FTSE, DAX, Nikkei) con precio, variación, mini-gráficos de 5 sesiones, estado del mercado y actualización automática cada 30 s. |
| `analizador.html` | 🔎 Analizador de Acciones | Busca cualquier ticker (AAPL, TSLA, BTC-USD…) y obtén datos básicos, análisis técnico (RSI, MACD, SMAs, soporte/resistencia), fundamental (P/E, EPS, dividendos, ROE/ROA) y un resumen ejecutivo con señal COMPRAR/MANTENER/VENDER. |
| `macro.html` | 🌍 Análisis Macroeconómico | Resumen ejecutivo en lenguaje simple, semáforo de riesgo global, indicadores clave (Fed, CPI/PCE, NFP, PIB, ISM), mercados globales, curva del Tesoro, calendario económico y sección educativa "lo que esto significa para ti". |
| `portafolio.html` | 💼 Análisis de Portafolio | Tabla editable de posiciones (demo pre-cargada), resumen, distribución por activo/sector/geografía, análisis de riesgo (volatilidad, Sharpe, drawdown, beta), comparativa vs S&P 500, recomendaciones IA y reporte exportable (PDF / copiar resumen). |

## Cómo verlo

Es un sitio 100 % estático: descarga el repositorio y abre `index.html` en cualquier navegador,
o sírvelo con `python3 -m http.server` y visita `http://localhost:8000`.

## Diseño

- Fondo `#0A0A0A`, acentos verdes `#00C896`, tipografía monospace estilo terminal.
- Código de colores: verde = positivo, rojo = negativo, amarillo = neutral.
- Responsive (escritorio y móvil). Gráficos dibujados con `<canvas>` nativo.

> ⚠️ Todos los datos son **simulados** con fines demostrativos y no constituyen asesoría financiera.
