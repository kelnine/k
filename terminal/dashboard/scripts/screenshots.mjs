// Screenshots of the main dashboard pages, taken with Playwright's Chromium.
//
// Needs a running dashboard (Caddy or `npm run preview`) with an API behind it and
// data in the database — see README.md ("Screenshots") for the demo stack:
//
//   npm i --no-save playwright
//   KT_URL=http://127.0.0.1:8088 KT_USER=otto KT_PASSWORD=... node scripts/screenshots.mjs
//
// Fails when the browser logs an error (a Content-Security-Policy violation, a
// failed request, an exception), so it doubles as a smoke test of the build.

import { mkdir } from 'node:fs/promises'
import { chromium } from 'playwright'

const BASE = process.env.KT_URL ?? 'http://127.0.0.1:4173'
const USER = process.env.KT_USER ?? 'otto'
const PASSWORD = process.env.KT_PASSWORD ?? ''
const OUT = process.env.KT_OUT ?? 'screenshots'

const errors = []
const browser = await chromium.launch()
await mkdir(OUT, { recursive: true })

async function newPage(viewport) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1, colorScheme: 'dark' })
  const page = await context.newPage()
  page.on('console', (message) => {
    // The session probe before sign-in answers 401 by design; anything else counts.
    if (message.type() === 'error' && !message.text().includes('status of 401')) {
      errors.push(`${page.url()}: ${message.text()}`)
    }
  })
  page.on('pageerror', (error) => errors.push(`${page.url()}: ${error.message}`))
  return page
}

async function settle(page) {
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(400) // canvas charts draw on the next animation frame
}

async function shot(page, name, { fullPage = true } = {}) {
  await settle(page)
  if (fullPage) await page.evaluate(() => window.scrollTo(0, 0)) // else the sticky top bar lands mid-page
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage })
  console.log(`saved ${OUT}/${name}.png`)
}

async function signIn(page) {
  await page.goto(BASE)
  await page.getByLabel('Username').fill(USER)
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: /sign in/i }).click()
  await page.waitForSelector('.topbar')
}

const desktop = await newPage({ width: 1440, height: 900 })
await desktop.goto(BASE)
await shot(desktop, '01-login', { fullPage: false })
await signIn(desktop)
await shot(desktop, '02-overview')

await desktop.locator('table.board tbody tr').first().click()
await desktop.waitForSelector('.account-head')
await shot(desktop, '03-account')
await desktop.getByRole('button', { name: 'Explain' }).first().click()
await desktop.waitForSelector('.drawer')
await shot(desktop, '04-trade-explain', { fullPage: false })
await desktop.keyboard.press('Escape')
await desktop.getByRole('tab', { name: /^Chart/ }).click()
await shot(desktop, '05-account-chart')
await desktop.getByRole('tab', { name: /^Signals/ }).click()
await shot(desktop, '06-account-signals')

for (const [path, name, fullPage] of [
  ['/instruments', '07-instruments', true],
  ['/instruments/XAUUSD', '08-instrument', true],
  ['/chart?instrument=XAUUSD&tf=5m', '09-chart', true],
  ['/trades', '10-trades', false], // long tables: the first screenful is enough
  ['/signals', '11-signals', false],
  ['/system', '12-system', true],
]) {
  await desktop.goto(`${BASE}${path}`)
  await shot(desktop, name, { fullPage })
}

const phone = await newPage({ width: 390, height: 844 })
await signIn(phone)
await shot(phone, '13-mobile-overview')
await browser.close()

if (errors.length) {
  console.error(`browser errors:\n${errors.join('\n')}`)
  process.exit(1)
}
