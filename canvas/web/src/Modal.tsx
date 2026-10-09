import { useEffect, type ReactNode } from 'react'
import { motion } from 'motion/react'
import { I } from './ui'

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])
  return (
    <motion.div className="fixed inset-0 z-50 grid place-items-center p-4 bg-black/55 backdrop-blur-sm"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} onMouseDown={e => e.target === e.currentTarget && onClose()}>
      <motion.div
        initial={{ opacity: 0, y: 16, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ type: 'spring', damping: 26, stiffness: 320 }}
        className={`w-full ${wide ? 'max-w-2xl' : 'max-w-lg'} glass rounded-3xl shadow-2xl shadow-black/50 max-h-[88vh] flex flex-col`}
      >
        <div className="flex items-center px-6 pt-5 pb-3">
          <h2 className="font-serif text-[28px] leading-none tracking-tight">{title}</h2>
          <button onClick={onClose} className="ml-auto p-2 -mr-2 rounded-lg hover:bg-white/[.06] text-fg-dim">{I.x()}</button>
        </div>
        <div className="px-6 pb-6 overflow-y-auto">{children}</div>
      </motion.div>
    </motion.div>
  )
}
