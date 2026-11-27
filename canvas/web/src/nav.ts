export function go(to: string) { location.hash = to }

/* the WORKSPACE (the observatory's chat) on this origin: canvas sits at <base>canvas/ (one org) or /o/<org>/canvas/ (a
   cog), the workspace at <base>; hash is its route ('/chat', '/chat/cv:canvas-3' a canvas's own conversation) */
export const workspaceHref = (hash = '/chat') => `${location.pathname.replace(/canvas\/.*$/, '')}#${hash}`
