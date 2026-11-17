// The canvas app's way home (owner 11-17: "home button is not there"): the workspace's URL is derived from the page's
// own path, never a host; and the org a member list is asked for. Called by tests/test_canvas_nav.py (medic 13003).
const at = (pathname: string) => { (globalThis as unknown as { location: { pathname: string } }).location = { pathname } }
const { workspaceHref } = await import('../canvas/web/src/nav.ts')

let fails = 0
const arm = (name: string, ok: boolean, got?: unknown) => { console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}${ok ? '' : `  (got ${JSON.stringify(got)})`}`); if (!ok) fails++ }

at('/o/astryx/canvas/'); arm('a cog: /o/<org>/canvas/ → /o/<org>/#/chat', workspaceHref() === '/o/astryx/#/chat', workspaceHref())
at('/o/astryx/canvas/index.html'); arm('...a deeper canvas path lands the same', workspaceHref() === '/o/astryx/#/chat', workspaceHref())
at('/canvas/'); arm('one org: /canvas/ → /#/chat', workspaceHref() === '/#/chat', workspaceHref())
at('/o/astryx/canvas/'); arm("a canvas's own conversation", workspaceHref('/chat/cv:canvas-3') === '/o/astryx/#/chat/cv:canvas-3', workspaceHref('/chat/cv:canvas-3'))

console.log(fails ? `FAIL (${fails})` : 'ALL PASS')
process.exit(fails ? 1 : 0)
