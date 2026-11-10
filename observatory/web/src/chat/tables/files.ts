import { download } from '../model'
import { parseNum } from './infer'

/* A table leaves the workspace as a file: CSV (RFC 4180, UTF-8 with a BOM so Excel reads Urdu and ₨ right) or a real
   .xlsx written here, a minimal SpreadsheetML package zipped by JSZip (already a dependency; no spreadsheet engine).
   Strings go in as inline strings, so nothing an agent wrote can ever become a formula; numbers go in as numbers
   (a figure with grouping commas keeps them as a number format), percentages as fractions with a % format, and a
   value that only LOOKS numeric (a leading zero, more than 15 digits: an id, an account) stays text.
   The CSV guards the same way the other direction: a text cell starting = + @ (a formula to a spreadsheet) is
   prefixed with ' so opening the file never runs it. */

const safeName = (s: string) => s.replace(/[\\/:*?"<>|\u0000-\u001f]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 120) || 'table'
export const stemOf = (name: string) => safeName(name.replace(/\.[a-z0-9]{1,5}$/i, '').replace(/\s*·\s*/g, ' - '))

/* ── CSV ─────────────────────────────────────────────────────────────────────────────────────────────────── */
export function toCsv(rows: string[][]): string {
  const cell = (v: string) => {
    let s = v ?? ''
    if (/^[=+@\t\r]/.test(s) && parseNum(s) === null) s = `'${s}`
    return /[",\n\r]/.test(s) || /^\s|\s$/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  return rows.map((r) => r.map(cell).join(',')).join('\r\n') + '\r\n'
}
export function downloadCsv(rows: string[][], name: string) {
  download(new Blob(['﻿' + toCsv(rows)], { type: 'text/csv;charset=utf-8' }), `${stemOf(name)}.csv`)
}

/* ── XLSX ────────────────────────────────────────────────────────────────────────────────────────────────── */
const XML_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
const esc = (s: string) => s.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f￾￿]/g, '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
const colName = (i: number) => { let s = ''; for (i++; i > 0; i = Math.floor((i - 1) / 26)) s = String.fromCharCode(65 + ((i - 1) % 26)) + s; return s }
/* styles: 0 general · 1 bold header · 2 #,##0 · 3 #,##0.00 · 4 0.0% */
const STYLES = `${XML_HEAD}<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="1"><numFmt numFmtId="164" formatCode="0.0%"/></numFmts>
<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>
<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="5"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/><xf numFmtId="3" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="4" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>`

function cellXml(ref: string, raw: string, header: boolean): string {
  const v = raw ?? ''
  if (v === '') return ''
  const t = v.trim()
  const n = header ? null : parseNum(t)
  const textual = n === null || /^-?0\d/.test(t) || t.replace(/\D/g, '').length > 15
  if (textual) return `<c r="${ref}" t="inlineStr"${header ? ' s="1"' : ''}><is><t xml:space="preserve">${esc(v)}</t></is></c>`
  if (/%\s*\)?$/.test(t)) return `<c r="${ref}" s="4"><v>${n! / 100}</v></c>`
  const style = /\d,\d{3}/.test(t) ? (/\.\d/.test(t) ? 3 : 2) : 0
  return `<c r="${ref}"${style ? ` s="${style}"` : ''}><v>${n}</v></c>`
}

function sheetXml(rows: string[][]): string {
  const width = Math.max(1, ...rows.map((r) => r.length))
  const widths = Array.from({ length: width }, (_, c) => Math.min(60, Math.max(8, ...rows.slice(0, 500).map((r) => (r[c] ?? '').length + 2))))
  const cols = `<cols>${widths.map((w, i) => `<col min="${i + 1}" max="${i + 1}" width="${w}" customWidth="1"/>`).join('')}</cols>`
  const data = rows.map((r, ri) => `<row r="${ri + 1}">${r.map((v, ci) => cellXml(`${colName(ci)}${ri + 1}`, v, ri === 0)).join('')}</row>`).join('')
  const pane = rows.length > 1 ? '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>' : ''
  return `${XML_HEAD}<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">${pane}${cols}<sheetData>${data}</sheetData></worksheet>`
}

export async function toXlsx(sheets: { name: string; rows: string[][] }[]): Promise<Blob> {
  const { default: JSZip } = await import('jszip')
  const zip = new JSZip()
  const names: string[] = []
  for (const s of sheets) {           // Excel: ≤31 chars, none of []:*?/\ , unique
    let n = (s.name.replace(/[[\]:*?/\\]/g, ' ').trim() || 'Sheet').slice(0, 31)
    for (let k = 2; names.includes(n); k++) n = `${n.slice(0, 27)} (${k})`
    names.push(n)
  }
  zip.file('[Content_Types].xml', `${XML_HEAD}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>${names.map((_, i) => `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join('')}</Types>`)
  zip.file('_rels/.rels', `${XML_HEAD}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>`)
  zip.file('xl/workbook.xml', `${XML_HEAD}<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>${names.map((n, i) => `<sheet name="${esc(n)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join('')}</sheets></workbook>`)
  zip.file('xl/_rels/workbook.xml.rels', `${XML_HEAD}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${names.map((_, i) => `<Relationship Id="rId${i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`).join('')}<Relationship Id="rId${names.length + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>`)
  zip.file('xl/styles.xml', STYLES)
  sheets.forEach((s, i) => zip.file(`xl/worksheets/sheet${i + 1}.xml`, sheetXml(s.rows)))
  return zip.generateAsync({ type: 'blob', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', compression: 'DEFLATE' })
}
export async function downloadXlsx(rows: string[][], name: string, sheet = 'Sheet1') {
  download(await toXlsx([{ name: sheet, rows }]), `${stemOf(name)}.xlsx`)
}
