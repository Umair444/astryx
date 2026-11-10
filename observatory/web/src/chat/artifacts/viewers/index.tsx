import { lazy, Suspense } from 'react'
import { download } from '../../model'
import { extOf, isProse, type Opened } from '../api'
import { bytes, KindIcon, KIND_WORD } from '../kinds'
import { Failed, Loading, useBlob, useMediaSrc, useText } from './common'
import Markdown, { Plain } from './Markdown'
import ImageView from './Image'
import Table from './Table'

/* One artifact version on screen, by kind. The light viewers (markdown, image, table) ship with the workspace; the
   heavy ones (code's highlighter, pdf.js, docx-preview, the xlsx reader) are their own chunks, fetched the first time
   that kind opens. */
const Code = lazy(() => import('./Code'))
const PdfView = lazy(() => import('./Pdf'))
const DocxView = lazy(() => import('./Docx'))
const SheetView = lazy(() => import('./Sheet'))

export default function ArtifactView({ art, rev }: { art: Opened; rev?: string }) {
  return (
    <Suspense fallback={<Loading />}>
      {art.kind === 'text' || art.kind === 'code' || art.kind === 'table' ? <TextKinds art={art} rev={rev} /> : <BlobKinds art={art} rev={rev} />}
    </Suspense>
  )
}

function TextKinds({ art, rev }: { art: Opened; rev?: string }) {
  const { text, err } = useText(art, rev)
  if (err) return <Failed err={err} />
  if (text == null) return <Loading />
  const ext = extOf(art.name)
  if (art.kind === 'table') return <Table text={text} ext={ext} name={art.name} memo={art.id} />
  if (art.kind === 'code') return <Code text={text} ext={ext} />
  return ext === 'md' || ext === 'markdown' ? <Markdown text={text} /> : isProse(art.name) ? <Plain text={text} /> : <Code text={text} ext={ext} />
}

function BlobKinds({ art, rev }: { art: Opened; rev?: string }) {
  const { blob, err } = useBlob(art, rev)
  if (err) return <Failed err={err} />
  if (!blob) return <Loading />
  switch (art.kind) {
    case 'image': return <ImageView blob={blob} name={art.name} />
    case 'pdf': return <PdfView blob={blob} />
    case 'docx': return <DocxView blob={blob} />
    case 'sheet': return <SheetView blob={blob} name={art.name} memo={art.id} />
    case 'audio': case 'video': return <Player blob={blob} kind={art.kind} name={art.name} />
    default: return <Card art={art} blob={blob} />
  }
}

function Player({ blob, kind, name }: { blob: Blob; kind: 'audio' | 'video'; name: string }) {
  const video = useMediaSrc<HTMLVideoElement>(blob), audio = useMediaSrc<HTMLAudioElement>(blob)
  return (
    <div className="h-full grid place-items-center p-8">
      {kind === 'video'
        ? <video ref={video} controls className="max-w-full max-h-full rounded-[12px] shadow-[0_12px_40px_-16px_rgba(0,0,0,.5)] bg-black" aria-label={name} />
        : (
          <div className="w-full max-w-[460px] ws-card p-5 flex flex-col gap-4">
            <div className="flex items-center gap-3"><span className="ws-chip-icon w-10 h-10 rounded-[11px] grid place-items-center"><KindIcon kind="audio" className="w-5 h-5" /></span>
              <span className="text-[14px] font-medium text-ink truncate">{name}</span></div>
            <audio ref={audio} controls className="w-full" aria-label={name} />
          </div>
        )}
    </div>
  )
}

/* anything without a viewer: what it is and a download, never an attempt to open it here */
function Card({ art, blob }: { art: Opened; blob: Blob }) {
  return (
    <div className="h-full grid place-items-center p-8">
      <div className="ws-card w-full max-w-[340px] p-6 flex flex-col items-center text-center">
        <span className="ws-chip-icon w-12 h-12 rounded-[14px] grid place-items-center"><KindIcon kind={art.kind} className="w-6 h-6" /></span>
        <div className="mt-3 text-[14px] font-medium text-ink break-all">{art.name}</div>
        <div className="mt-1 text-[12.5px] text-ink-mute">{KIND_WORD[art.kind]}{extOf(art.name) ? ` · .${extOf(art.name)}` : ''} · {bytes(blob.size)}</div>
        <p className="mt-3 text-[12.5px] text-ink-dim leading-relaxed">There is no viewer for this kind of file. It opens on your device.</p>
        <button onClick={() => download(blob, art.name)} className="ws-btn mt-4">Download</button>
      </div>
    </div>
  )
}
