import { useEffect } from 'react'
import CallDock from './CallDock'
import CallAvatar from './CallAvatar'
import { setSelectedAgent, toggleCall } from './state'
import { hangup } from '../pilot/voice'
import './call.css'

/* THE CALL's layer (iteration 17): mounted ONCE for the owner, on every observatory page AND in the chat workspace
   (App.tsx mounts it beside both), so a live call survives moving between them. It holds the dock, the figure and
   the one shortcut: ⌘/Ctrl+Shift+L starts a call with the agent on screen, or hangs up the live one (a key press is
   a user activation, so the mic may open from it). `selected` is the observatory's open agent (profile or chat
   sheet), the call's agent when no chat is open. */
export default function CallLayer({ selected = null }: { selected?: string | null }) {
  useEffect(() => { setSelectedAgent(selected) }, [selected])
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && !e.altKey && e.code === 'KeyL') { e.preventDefault(); toggleCall() }
    }
    addEventListener('keydown', k)
    return () => removeEventListener('keydown', k)
  }, [])
  useEffect(() => () => hangup(), [])            // the layer leaves (signed out): the call ends, minutes reported
  return (
    <>
      <CallDock />
      <CallAvatar />
    </>
  )
}
