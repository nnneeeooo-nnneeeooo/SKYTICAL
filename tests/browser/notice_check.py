"""Real Chromium checks against the built site, or --url after deployment."""
import argparse
import functools
import http.server
import json
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
KEY = "skytical:update-notice:last-shown:v1"
INTERVAL = 10_800_000
START = 1_794_787_200_000


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url")
    parser.add_argument("--output", default="notice-browser-results")
    args = parser.parse_args()
    output = Path(args.output); output.mkdir(parents=True, exist_ok=True)
    server = None
    if args.url:
        url = args.url.rstrip("/") + "/"
    else:
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT / "site"))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_port}/"
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        def context(width=1440, height=900, **kwargs):
            ctx = browser.new_context(viewport={"width": width, "height": height}, **kwargs)
            ctx.add_init_script(f"Date.now=()=>{{try{{return Number(localStorage.getItem('__qa_notice_now'))||{START};}}catch(e){{return {START};}}}};")
            def resource(route):
                request = route.request
                if "googletagmanager.com" in request.url or "google-analytics.com" in request.url or (request.resource_type == 'image' and not request.url.startswith(url)):
                    route.abort()
                else:
                    route.continue_()
            ctx.route("**/*", resource)
            return ctx
        def ready(page, path=""):
            page.goto(url + path, wait_until="load")
            page.locator('#site-update-notice .update').first.wait_for(state='attached')
        def check(name, value):
            if not value:
                page.screenshot(path=str(output / 'failure.png'))
                (output / 'results.json').write_text(json.dumps(results + [{"name": name, "pass": False}], indent=2), encoding='utf-8')
            assert value, name
            results.append({"name": name, "pass": True})
        ctx = context(); page = ctx.new_page(); errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        ready(page)
        dialog = page.locator('#site-update-notice')
        dialog.wait_for(state="visible")
        check("first visit shows notice", dialog.is_visible())
        check("close button initially focused", page.locator('[data-notice-close]').first.evaluate('(el)=>el===document.activeElement'))
        shown = page.evaluate(f"Number(localStorage.getItem('{KEY}'))")
        page.locator('.notice-primary').click()
        check("continue returns directly to homepage", not dialog.is_visible() and page.url == url)
        check("closing does not reset timestamp", page.evaluate(f"Number(localStorage.getItem('{KEY}'))") == shown)
        page.evaluate("value=>localStorage.setItem('__qa_notice_now',String(value))", START + INTERVAL - 1)
        ready(page, "en/")
        check("2h59m59.999s suppressed across languages", not dialog.is_visible())
        page.reload(wait_until="load")
        check("reload within interval suppressed", not dialog.is_visible())
        page.evaluate("value=>localStorage.setItem('__qa_notice_now',String(value))", START + INTERVAL)
        page.wait_for_timeout(150)
        check("time passing does not interrupt reading", not dialog.is_visible())
        ready(page, "en/news/")
        dialog.wait_for(state="visible")
        check("exactly three hours shows again", dialog.is_visible())
        check("new interval starts at display", page.evaluate(f"Number(localStorage.getItem('{KEY}'))") == START + INTERVAL)
        page.keyboard.press("Escape")
        check("Escape closes notice", not dialog.is_visible())
        other = ctx.new_page(); ready(other)
        check("another tab shares cooldown", not other.locator('#site-update-notice').is_visible())
        check("no uncaught browser errors", not errors)
        ctx.close()
        for lang, path in (("zh", ""), ("en", "en/")):
            for width, height in ((1440, 900), (768, 1024), (390, 844), (320, 740)):
                ctx = context(width, height)
                page = ctx.new_page(); ready(page, path)
                page.locator('#site-update-notice').wait_for(state="visible")
                image = page.locator('#site-update-notice .station-portrait img')
                image.evaluate('(el)=>el.decode()')
                metrics = page.evaluate("""()=>{const d=document.querySelector('#site-update-notice');const r=d.getBoundingClientRect();const x=d.querySelector('.notice-close').getBoundingClientRect();const f=d.querySelector('.notice-footer').getBoundingClientRect();return {overflow:document.documentElement.scrollWidth>innerWidth||d.scrollWidth>d.clientWidth,inside:r.left>=0&&r.right<=innerWidth,close:x.top>=0&&x.bottom<=innerHeight,footer:f.bottom<=innerHeight,dates:[...d.querySelectorAll('time')].every(t=>/^\\d{2}\\/\\d{2}$/.test(t.textContent)),oldDate:!!d.querySelector('.edition')};}""")
                check(f"{lang}/{width} responsive dialog and controls", not metrics['overflow'] and metrics['inside'] and metrics['close'] and metrics['footer'])
                check(f"{lang}/{width} short per-item dates", metrics['dates'] and not metrics['oldDate'])
                check(f"{lang}/{width} mail link", page.locator('#site-update-notice .station-note a').get_attribute('href') == 'mailto:kass09221477@gmail.com')
                if lang == 'en':
                    text = page.locator('#site-update-notice').inner_text()
                    check(f"English/{width} fully translated", not any('\u4e00' <= c <= '\u9fff' for c in text))
                page.screenshot(path=str(output / f"{lang}-{width}.png"))
                page.locator('.notice-copy').evaluate('(el)=>el.scrollTop=el.scrollHeight')
                check(f"{lang}/{width} close remains visible after scroll", page.locator('.notice-close').is_visible())
                page.locator('.notice-close').click()
                check(f"{lang}/{width} cross closes overlay", not page.locator('#site-update-notice').is_visible())
                ctx.close()
        for theme in ('light', 'dark', '8bit'):
            for lang, path in (('zh', ''), ('en', 'en/')):
                for width, height in ((1440, 900), (1280, 800), (1024, 768), (768, 1024), (390, 844), (320, 740)):
                    phone = width <= 720
                    label = f'{theme}/{lang}/{width}'
                    ctx = context(width, height, is_mobile=phone, has_touch=phone)
                    ctx.add_init_script(f"localStorage.setItem('skytical-8bit-unlocked','true');localStorage.setItem('avwire-theme','{theme}');localStorage.setItem('{KEY}',String(Date.now()));")
                    page = ctx.new_page(); ready(page, path)
                    page.locator('[data-notice-open]').wait_for(state='attached')
                    page.wait_for_timeout(100)
                    check(label + ' theme applied', page.locator('html').get_attribute('data-theme') == theme)
                    metrics = page.evaluate("""()=>{
                        const h=document.querySelector('.header-search-row');
                        const nodes=innerWidth<=720?[h.querySelector('.mobile-search-brand'),h.querySelector('.header-search-form'),h.querySelector('.mobile-more>summary')]:[h.querySelector('.header-search-form'),...h.querySelectorAll('.header-social-links>a,.header-announcement-button')];
                        const rects=nodes.map(n=>{const r=n.getBoundingClientRect();return {left:r.left,right:r.right,cy:(r.top+r.bottom)/2,height:r.height};});
                        return {overflow:h.scrollWidth>h.clientWidth+1,rects,mobile:document.documentElement.classList.contains('mobile-refresh')};
                    }""")
                    rects = metrics['rects']
                    check(label + ' aligned header without overlap', not metrics['overflow'] and max(r['cy'] for r in rects)-min(r['cy'] for r in rects)<2 and all(r['left']>=0 and r['right']<=width and r['height']>=30 for r in rects) and all(rects[i-1]['right']<=rects[i]['left']+1 for i in range(1,len(rects))))
                    if phone:
                        check(label + ' current phone layout', metrics['mobile'])
                        page.locator('.mobile-more>summary').click()
                    elif theme == '8bit':
                        check(label + ' single pixel brand', not page.locator('.header-search-row .brand-link').is_visible() and page.locator('.header-search-row .pixel-brand').is_visible())
                    page.screenshot(path=str(output / f'header-{theme}-{lang}-{width}.png'), clip={'x':0,'y':0,'width':width,'height':190})
                    old_stamp = page.evaluate(f"localStorage.getItem('{KEY}')")
                    page.locator('[data-notice-open]').click()
                    dialog = page.locator('#site-update-notice'); dialog.wait_for(state='visible')
                    check(label + ' wing visible', page.locator('[data-notice-wing]').is_visible())
                    check(label + ' manual replay preserves cooldown', page.evaluate(f"localStorage.getItem('{KEY}')") == old_stamp)
                    pane = page.locator('.notice-copy')
                    check(label + ' scrollbar hidden with native scrolling', pane.evaluate("el=>getComputedStyle(el).scrollbarWidth==='none'&&getComputedStyle(el).overflowY==='auto'"))
                    pane.locator('p').first.click()
                    check(label + ' content click stays open', dialog.is_visible())
                    scrolled = pane.evaluate("el=>{el.scrollTop=100;return el.scrollHeight<=el.clientHeight||el.scrollTop>0;}")
                    check(label + ' overflowing content still scrolls', scrolled)
                    pane.evaluate('el=>el.scrollTop=0')
                    if width in (1440,390):
                        page.screenshot(path=str(output / f'notice-{theme}-{lang}-{width}.png'))
                    if theme == '8bit':
                        check(label + ' pixel colors and type', dialog.evaluate("el=>getComputedStyle(el).backgroundColor==='rgb(18, 32, 57)'&&getComputedStyle(el).fontFamily.includes('Fusion Pixel')"))
                    if not phone:
                        point = pane.locator('p').first.bounding_box()
                        page.mouse.move(point['x']+5,point['y']+5)
                        page.mouse.down(); page.mouse.move(2,2); page.mouse.up()
                        check(label + ' dragging out does not dismiss', dialog.is_visible())
                    if phone:
                        page.touchscreen.tap(2,2)
                    else:
                        page.mouse.click(2,2)
                    check(label + ' outside gesture closes dialog', not dialog.is_visible())
                    focused = page.locator('.mobile-more>summary' if phone else '[data-notice-open]')
                    check(label + ' focus restored', focused.evaluate('el=>el===document.activeElement'))
                    ctx.close()
        ctx = context(390, 844, reduced_motion="reduce")
        page = ctx.new_page(); ready(page, "team/")
        page.locator('#site-update-notice').wait_for(state="visible")
        page.locator('[data-notice-wing]').click()
        check("reduced motion respected on team page", not page.locator('[data-notice-wing]').evaluate("el=>el.classList.contains('is-playing')"))
        page.evaluate("document.documentElement.dataset.theme='dark'")
        page.screenshot(path=str(output / "zh-dark-reduced-motion.png"))
        ctx.close()
        ctx = context()
        ctx.add_init_script("Object.defineProperty(window,'localStorage',{configurable:true,get(){throw new Error('blocked');}})")
        page = ctx.new_page(); ready(page)
        page.locator('#site-update-notice').wait_for(state="visible")
        page.locator('.notice-close').click()
        page.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}))")
        check("blocked storage retains page-level cooldown", not page.locator('#site-update-notice').is_visible())
        ctx.close(); browser.close()
    if server:
        server.shutdown()
    (output / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(f"Notice browser QA: {len(results)} checks passed")


if __name__ == '__main__':
    main()
